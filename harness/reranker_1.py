"""
重排序模块
基于 BGE-Reranker-large，对检索结果进行精排

用法：
    from harness.reranker import Reranker
    reranker = Reranker()
    ranked = reranker.rerank("高炉煤气泄漏", passages, top_k=5)
"""

import re
from typing import Any, Dict, List, Optional

try:
    from sentence_transformers import CrossEncoder
    _CROSS_ENCODER_IMPORT_ERROR = None
except Exception as e:
    CrossEncoder = None
    _CROSS_ENCODER_IMPORT_ERROR = e

from utils.config import get_config
from utils.logger import get_logger

logger = get_logger(__name__)


def _lexical_score(query: str, text: str) -> float:
    query_norm = re.sub(r"\s+", "", query.lower())
    text_norm = re.sub(r"\s+", "", text.lower())
    if not query_norm or not text_norm:
        return 0.0

    score = 0.0
    domain_phrases = [
        "粉尘涉爆", "粉尘爆炸", "除尘系统", "除尘", "危化品", "危险化学品",
        "泄漏", "储罐", "冶金", "煤气", "报警", "有限空间", "中毒窒息",
        "中毒和窒息", "通风", "检测", "动火", "联锁",
    ]
    for phrase in domain_phrases:
        if phrase in query_norm and phrase in text_norm:
            score += 4.0

    for n, weight in ((4, 1.5), (3, 1.2), (2, 0.7), (1, 0.1)):
        if len(query_norm) < n:
            continue
        grams = {query_norm[i:i + n] for i in range(len(query_norm) - n + 1)}
        if not grams:
            continue
        hits = sum(1 for gram in grams if gram in text_norm)
        score += weight * hits / len(grams)
    return score


class Reranker:
    """
    重排序器
    使用 BGE-Reranker-large 或配置的交叉编码模型对候选段落重新排序
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        device: Optional[str] = None,
    ):
        config = get_config()
        self.model_name = model_name or config.harness.memory.long_term.rag.get(
            "reranker_model", "BAAI/bge-reranker-large"
        )
        self.device = device
        self._model: Optional[Any] = None
        self._fallback_warned = False

    def _load_model(self) -> Any:
        if CrossEncoder is None:
            detail = f" 原始错误: {_CROSS_ENCODER_IMPORT_ERROR}" if _CROSS_ENCODER_IMPORT_ERROR else ""
            raise ImportError(
                "Reranker 需要可选依赖 sentence-transformers。"
                "请安装 `pip install -r requirements-rag.txt` 或 `pip install -r requirements-full.txt`。"
                f"{detail}"
            )
        if self._model is None:
            logger.info(f"加载重排序模型: {self.model_name}")
            self._model = CrossEncoder(self.model_name, device=self.device)
        return self._model

    def rerank(
        self,
        query: str,
        passages: List[Dict],
        top_k: int = 5,
    ) -> List[Dict]:
        """
        对候选段落进行重排序
        
        Args:
            query: 查询文本
            passages: 候选段落列表，每个元素至少包含 "text" 字段
            top_k: 返回前 k 个结果
        
        Returns:
            按相关性降序排列的段落列表，新增 "rerank_score" 字段
        """
        if not passages:
            return []

        if CrossEncoder is None:
            if not self._fallback_warned:
                detail = f": {_CROSS_ENCODER_IMPORT_ERROR}" if _CROSS_ENCODER_IMPORT_ERROR else ""
                logger.warning(f"真实 reranker 不可用，使用 deterministic fallback{detail}")
                self._fallback_warned = True
            return self._fallback_rerank(query, passages, top_k)
        
        try:
            model = self._load_model()
            texts = [p.get("text", "") for p in passages]
            pairs = [(query, t) for t in texts]
            scores = model.predict(pairs)
            
            # 将分数附加到结果
            scored_passages = []
            for passage, score in zip(passages, scores):
                item = dict(passage)
                item["rerank_score"] = float(score)
                scored_passages.append(item)
            
            # 按分数降序排列
            scored_passages.sort(key=lambda x: x["rerank_score"], reverse=True)
            return scored_passages[:top_k]
        except Exception as e:
            logger.warning(f"重排序模型推理失败: {e}，使用 deterministic fallback")
            return self._fallback_rerank(query, passages, top_k)

    def _fallback_rerank(self, query: str, passages: List[Dict], top_k: int) -> List[Dict]:
        scored_passages = []
        for i, passage in enumerate(passages):
            item = dict(passage)
            item["rerank_score"] = _lexical_score(query, item.get("text", "")) - i * 0.0001
            scored_passages.append(item)
        scored_passages.sort(key=lambda x: x["rerank_score"], reverse=True)
        return scored_passages[:top_k]


def rerank(
    query: str,
    passages: List[Dict],
    top_k: int = 5,
    model_name: Optional[str] = None,
) -> List[Dict]:
    """
    便捷函数：快速重排序
    """
    r = Reranker(model_name=model_name)
    return r.rerank(query, passages, top_k=top_k)
