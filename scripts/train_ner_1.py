"""
NER 训练脚本：支持 BIO 自动转换与 BERT-BiLSTM-CRF 模型训练

用法：
    python scripts/train_ner.py --data data/ner_train.json --output models/ner_model.pt --epochs 10
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset
from tqdm import tqdm
from transformers import BertTokenizer

# 将项目根目录加入 sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from harness.nlp_pipeline import BertBiLSTMCRF, LABEL2ID, ID2LABEL, bio_encode
from utils.logger import get_logger

logger = get_logger(__name__)


def char_tokenize(text: str) -> List[str]:
    """按字符分词"""
    return list(text)


class NERDataset(Dataset):
    """
    NER 数据集
    数据格式：List[{"text": str, "entities": List[{"text": str, "label": str, "start": int, "end": int}]}]
    """

    def __init__(
        self,
        data: List[Dict],
        tokenizer: BertTokenizer,
        max_length: int = 512,
    ):
        self.data = data
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __len__(self) -> int:
        return len(self.data)

    def __getitem__(self, idx: int) -> Dict[str, torch.Tensor]:
        item = self.data[idx]
        text = item["text"]
        entities = item.get("entities", [])
        
        # 字符分词并 BIO 标注
        tokens = char_tokenize(text)
        labels = bio_encode(tokens, entities)
        
        # 使用 BertTokenizer 编码
        encoding = self.tokenizer(
            text,
            max_length=self.max_length,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        )
        
        input_ids = encoding["input_ids"].squeeze(0)
        attention_mask = encoding["attention_mask"].squeeze(0)
        
        # 将字符级别的 BIO 标签对齐到 token 级别
        # 简化处理：使用 tokenizer 的 word_ids
        tokenized = self.tokenizer(text, add_special_tokens=True)
        word_ids = tokenized.word_ids()
        
        label_ids = []
        previous_word_idx = None
        for word_idx in word_ids:
            if word_idx is None:
                label_ids.append(-100)  # 特殊 token 忽略
            elif word_idx != previous_word_idx:
                # 取该字符对应的标签
                if word_idx < len(labels):
                    label_ids.append(LABEL2ID.get(labels[word_idx], 0))
                else:
                    label_ids.append(0)
            else:
                # 子词：如果是 I- 标签则延续，否则设为 -100
                if word_idx < len(labels):
                    lbl = labels[word_idx]
                    if lbl.startswith("I-"):
                        label_ids.append(LABEL2ID.get(lbl, 0))
                    else:
                        label_ids.append(-100)
                else:
                    label_ids.append(-100)
            previous_word_idx = word_idx
        
        # 补齐到 max_length
        while len(label_ids) < self.max_length:
            label_ids.append(-100)
        label_ids = label_ids[:self.max_length]
        
        return {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "labels": torch.tensor(label_ids, dtype=torch.long),
        }


def collate_fn(batch: List[Dict]) -> Dict[str, torch.Tensor]:
    """批次合并"""
    input_ids = torch.stack([b["input_ids"] for b in batch])
    attention_mask = torch.stack([b["attention_mask"] for b in batch])
    labels = torch.stack([b["labels"] for b in batch])
    return {
        "input_ids": input_ids,
        "attention_mask": attention_mask,
        "labels": labels,
    }


def train_epoch(
    model: BertBiLSTMCRF,
    dataloader: DataLoader,
    optimizer: torch.optim.Optimizer,
    device: str,
) -> float:
    model.train()
    total_loss = 0.0
    for batch in tqdm(dataloader, desc="Training"):
        input_ids = batch["input_ids"].to(device)
        attention_mask = batch["attention_mask"].to(device)
        labels = batch["labels"].to(device)
        
        optimizer.zero_grad()
        outputs = model(input_ids=input_ids, attention_mask=attention_mask, labels=labels)
        loss = outputs["loss"]
        loss.backward()
        optimizer.step()
        
        total_loss += loss.item()
    return total_loss / len(dataloader)


def evaluate(model: BertBiLSTMCRF, dataloader: DataLoader, device: str) -> Dict[str, float]:
    model.eval()
    total_loss = 0.0
    correct = 0
    total = 0
    with torch.no_grad():
        for batch in tqdm(dataloader, desc="Evaluating"):
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            labels = batch["labels"].to(device)
            
            outputs = model(input_ids=input_ids, attention_mask=attention_mask, labels=labels)
            loss = outputs["loss"]
            total_loss += loss.item()
            
            predictions = model(input_ids=input_ids, attention_mask=attention_mask)["predictions"]
            for pred, label, mask in zip(predictions, labels, attention_mask):
                for p, l, m in zip(pred, label, mask):
                    if m.item() == 1 and l.item() != -100:
                        total += 1
                        if p == l.item():
                            correct += 1
    
    avg_loss = total_loss / len(dataloader)
    accuracy = correct / total if total > 0 else 0.0
    return {"loss": avg_loss, "accuracy": accuracy}


def main():
    parser = argparse.ArgumentParser(description="训练 NER 模型")
    parser.add_argument("--data", type=str, required=True, help="训练数据 JSON 路径")
    parser.add_argument("--output", type=str, default="models/ner_model.pt", help="模型输出路径")
    parser.add_argument("--bert", type=str, default="bert-base-chinese", help="预训练BERT模型名")
    parser.add_argument("--epochs", type=int, default=10, help="训练轮数")
    parser.add_argument("--batch-size", type=int, default=8, help="批次大小")
    parser.add_argument("--lr", type=float, default=2e-5, help="学习率")
    parser.add_argument("--max-length", type=int, default=512, help="最大序列长度")
    parser.add_argument("--val-ratio", type=float, default=0.1, help="验证集比例")
    args = parser.parse_args()
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info(f"使用设备: {device}")
    
    # 加载数据
    with open(args.data, "r", encoding="utf-8") as f:
        all_data = json.load(f)
    logger.info(f"加载数据: {len(all_data)} 条")
    
    # 划分训练/验证集
    val_size = int(len(all_data) * args.val_ratio)
    train_data = all_data[val_size:]
    val_data = all_data[:val_size]
    
    # 初始化 tokenizer 和模型
    tokenizer = BertTokenizer.from_pretrained(args.bert)
    model = BertBiLSTMCRF(bert_model_name=args.bert)
    model.to(device)
    
    train_dataset = NERDataset(train_data, tokenizer, max_length=args.max_length)
    val_dataset = NERDataset(val_data, tokenizer, max_length=args.max_length)
    
    train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True, collate_fn=collate_fn)
    val_loader = DataLoader(val_dataset, batch_size=args.batch_size, shuffle=False, collate_fn=collate_fn)
    
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)
    
    best_val_loss = float("inf")
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    
    for epoch in range(1, args.epochs + 1):
        logger.info(f"Epoch {epoch}/{args.epochs}")
        train_loss = train_epoch(model, train_loader, optimizer, device)
        val_metrics = evaluate(model, val_loader, device)
        logger.info(f"  Train Loss: {train_loss:.4f} | Val Loss: {val_metrics['loss']:.4f} | Val Acc: {val_metrics['accuracy']:.4f}")
        
        if val_metrics["loss"] < best_val_loss:
            best_val_loss = val_metrics["loss"]
            torch.save({
                "epoch": epoch,
                "model_state_dict": model.state_dict(),
                "optimizer_state_dict": optimizer.state_dict(),
                "val_loss": best_val_loss,
            }, args.output)
            logger.info(f"  模型已保存: {args.output}")
    
    logger.info("训练完成")


if __name__ == "__main__":
    main()
