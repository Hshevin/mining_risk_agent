"""
NLP实体抽取管道
基于 BERT-BiLSTM-CRF 架构
实体标签：高风险设备、风险属性、动作、法规条款

用法：
    from harness.nlp_pipeline import NERPipeline
    pipeline = NERPipeline()
    entities = pipeline.extract_entities("高炉煤气泄漏需立即停炉")
"""

import os
import re
from typing import Dict, List, Optional

import torch
import torch.nn as nn
from torchcrf import CRF
from transformers import BertModel, BertTokenizer

from utils.config import get_config
from utils.exceptions import FeatureEngineeringError
from utils.logger import get_logger

logger = get_logger(__name__)

# 实体标签定义
LABEL2ID = {
    "O": 0,
    "B-高风险设备": 1,
    "I-高风险设备": 2,
    "B-风险属性": 3,
    "I-风险属性": 4,
    "B-动作": 5,
    "I-动作": 6,
    "B-法规条款": 7,
    "I-法规条款": 8,
}

ID2LABEL = {v: k for k, v in LABEL2ID.items()}

# 规则词典（用于回退/增强）
RULE_DICT = {
    "高风险设备": [
        "高炉", "转炉", "电炉", "煤气柜", "氨罐", "反应釜", "储罐", "锅炉",
        "压力容器", "压力管道", "提升机", "通风机", "除尘器", "破碎机",
        "铸造机", "熔炼炉", "深井铸造", "钢丝绳", "液压装置", "输送带",
        "瓦斯抽采泵", "空压机", "起重机", "叉车", "电梯", "煤气发生器",
    ],
    "风险属性": [
        "泄漏", "爆炸", "火灾", "中毒", "窒息", "坍塌", "冒顶", "透水",
        "超限", "超压", "超温", "超速", "断裂", "腐蚀", "磨损", "堵塞",
        "短路", "漏电", "静电", "积聚", "超标", "失效", "故障", "异常",
    ],
    "动作": [
        "停炉", "停机", "停产", "撤离", "疏散", "切断", "关闭", "开启",
        "排放", "通风", "降温", "降压", "报警", "检测", "监测", "检查",
        "维修", "更换", "加固", "清理", "清洗", "充氮", "泄压", "堵漏",
        "动火", "吊装", "受限空间作业", "高处作业",
    ],
    "法规条款": [
        "安全生产法", "安全生产条例", "判定标准", "应急管理部令", "重大隐患",
        "三同时", "安全评价", "标准化建设", "双控机制", "隐患排查",
    ],
}


class BertBiLSTMCRF(nn.Module):
    """
    BERT-BiLSTM-CRF 模型
    """

    def __init__(
        self,
        bert_model_name: str = "bert-base-chinese",
        lstm_hidden_size: int = 256,
        num_labels: int = 9,
        dropout: float = 0.3,
    ):
        super().__init__()
        self.bert = BertModel.from_pretrained(bert_model_name)
        self.dropout = nn.Dropout(dropout)
        self.lstm = nn.LSTM(
            self.bert.config.hidden_size,
            lstm_hidden_size // 2,
            num_layers=1,
            bidirectional=True,
            batch_first=True,
        )
        self.classifier = nn.Linear(lstm_hidden_size, num_labels)
        self.crf = CRF(num_labels, batch_first=True)

    def forward(
        self,
        input_ids: torch.Tensor,
        attention_mask: torch.Tensor,
        labels: Optional[torch.Tensor] = None,
    ) -> Dict[str, torch.Tensor]:
        bert_out = self.bert(input_ids=input_ids, attention_mask=attention_mask)
        sequence_output = bert_out.last_hidden_state
        sequence_output = self.dropout(sequence_output)
        lstm_out, _ = self.lstm(sequence_output)
        emissions = self.classifier(lstm_out)

        if labels is not None:
            # CRF 损失计算需要 mask
            mask = attention_mask.bool()
            loss = -self.crf(emissions, labels, mask=mask, reduction="mean")
            return {"loss": loss, "emissions": emissions}
        else:
            mask = attention_mask.bool()
            predictions = self.crf.decode(emissions, mask=mask)
            return {"predictions": predictions, "emissions": emissions}


class NERPipeline:
    """
    NER 实体抽取管道
    支持模型推理 + 规则回退
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        bert_model_name: str = "bert-base-chinese",
        device: Optional[str] = None,
    ):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model_path = model_path
        self.bert_model_name = bert_model_name
        self.model: Optional[BertBiLSTMCRF] = None
        self.tokenizer: Optional[BertTokenizer] = None
        self._load_model()

    def _load_model(self) -> None:
        """尝试加载训练好的模型"""
        if self.model_path and os.path.exists(self.model_path):
            try:
                self.tokenizer = BertTokenizer.from_pretrained(self.bert_model_name)
                self.model = BertBiLSTMCRF(bert_model_name=self.bert_model_name)
                checkpoint = torch.load(self.model_path, map_location=self.device)
                self.model.load_state_dict(checkpoint.get("model_state_dict", checkpoint))
                self.model.to(self.device)
                self.model.eval()
                logger.info(f"NER模型已加载: {self.model_path}")
            except Exception as e:
                logger.warning(f"加载NER模型失败: {e}，将使用规则回退")
                self.model = None
        else:
            logger.info("未找到NER模型，使用规则回退模式")
            self.model = None

    def _rule_extract(self, text: str) -> List[Dict]:
        """基于规则的实体抽取（回退模式）"""
        entities = []
        for label_type, keywords in RULE_DICT.items():
            for kw in keywords:
                for match in re.finditer(re.escape(kw), text):
                    entities.append({
                        "text": kw,
                        "label": label_type,
                        "start": match.start(),
                        "end": match.end(),
                        "source": "rule",
                    })
        # 去重并排序
        entities = sorted(entities, key=lambda x: x["start"])
        # 简单去重：相同位置只保留一个
        filtered = []
        seen = set()
        for e in entities:
            key = (e["start"], e["end"], e["label"])
            if key not in seen:
                seen.add(key)
                filtered.append(e)
        return filtered

    def _model_extract(self, text: str) -> List[Dict]:
        """基于模型的实体抽取"""
        if self.model is None or self.tokenizer is None:
            return []
        
        # Tokenize
        encoding = self.tokenizer(
            text,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=512,
        )
        input_ids = encoding["input_ids"].to(self.device)
        attention_mask = encoding["attention_mask"].to(self.device)
        
        with torch.no_grad():
            outputs = self.model(input_ids=input_ids, attention_mask=attention_mask)
            predictions = outputs["predictions"][0]
        
        # 将 token 级别的预测映射回字符级别
        tokens = self.tokenizer.convert_ids_to_tokens(input_ids[0])
        entities = []
        current_entity = None
        
        for idx, (token, pred_id) in enumerate(zip(tokens, predictions)):
            if token in ["[CLS]", "[SEP]", "[PAD]"]:
                if current_entity:
                    entities.append(current_entity)
                    current_entity = None
                continue
            
            label = ID2LABEL.get(pred_id, "O")
            if label.startswith("B-"):
                if current_entity:
                    entities.append(current_entity)
                current_entity = {
                    "text": token.replace("##", ""),
                    "label": label[2:],
                    "start": idx,
                    "end": idx + 1,
                    "source": "model",
                }
            elif label.startswith("I-") and current_entity and current_entity["label"] == label[2:]:
                current_entity["text"] += token.replace("##", "")
                current_entity["end"] = idx + 1
            else:
                if current_entity:
                    entities.append(current_entity)
                    current_entity = None
        
        if current_entity:
            entities.append(current_entity)
        
        return entities

    def extract_entities(self, text: str) -> List[Dict]:
        """
        抽取实体
        
        Args:
            text: 输入文本
        
        Returns:
            List[Dict]，每个元素包含 text, label, start, end, source
        """
        if not text or not text.strip():
            return []
        
        # 优先使用模型，如果不可用则回退到规则
        if self.model is not None:
            try:
                entities = self._model_extract(text)
                if entities:
                    return entities
            except Exception as e:
                logger.warning(f"模型推理失败: {e}，回退到规则")
        
        return self._rule_extract(text)

    def extract_entities_batch(self, texts: List[str]) -> List[List[Dict]]:
        """批量抽取实体"""
        return [self.extract_entities(t) for t in texts]


def bio_decode(tokens: List[str], labels: List[str]) -> List[Dict]:
    """
    BIO 标签序列解码为实体列表
    
    Args:
        tokens: token 列表
        labels: BIO 标签列表
    
    Returns:
        实体列表
    """
    entities = []
    current = None
    for token, label in zip(tokens, labels):
        if label.startswith("B-"):
            if current:
                entities.append(current)
            current = {"text": token, "label": label[2:], "start": -1, "end": -1}
        elif label.startswith("I-") and current and current["label"] == label[2:]:
            current["text"] += token
        else:
            if current:
                entities.append(current)
                current = None
    if current:
        entities.append(current)
    return entities


def bio_encode(tokens: List[str], entities: List[Dict]) -> List[str]:
    """
    将实体列表编码为 BIO 标签序列
    
    Args:
        tokens: token 列表
        entities: 实体列表，每个元素包含 text, label, start, end（字符位置）
    
    Returns:
        BIO 标签列表
    """
    # 简单实现：假设 tokens 是字符列表，按完全匹配标注
    labels = ["O"] * len(tokens)
    text = "".join(tokens)
    for ent in entities:
        ent_text = ent["text"]
        label = ent["label"]
        idx = text.find(ent_text)
        if idx >= 0:
            # 找到 token 对应的位置
            pos = 0
            start_idx = -1
            end_idx = -1
            for i, tok in enumerate(tokens):
                if pos == idx:
                    start_idx = i
                if pos == idx + len(ent_text):
                    end_idx = i
                pos += len(tok)
            if start_idx >= 0 and end_idx < 0:
                end_idx = len(tokens)
            if start_idx >= 0 and end_idx > start_idx:
                labels[start_idx] = f"B-{label}"
                for i in range(start_idx + 1, end_idx):
                    labels[i] = f"I-{label}"
    return labels
