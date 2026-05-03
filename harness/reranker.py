"""
重排序模块
基于 BGE-Reranker-large，对检索结果进行精排

用法：
    from harness.reranker import Reranker
    reranker = Reranker()
    ranked = reranker.rerank("高炉煤气泄漏", passages, top_k=5)
"""

from typing import Dict, List, Optional

from sentence_transformers import CrossEncoder

from utils.config import get_config
from utils.logger import get_logger

logger = get_logger(__name__)


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
        self._model: Optional[CrossEncoder] = None

    def _load_model(self) -> CrossEncoder:
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
            logger.warning(f"重排序模型推理失败: {e}，回退到原始顺序")
            # 回退：保持原始顺序，给每个结果一个默认分数
            for i, p in enumerate(passages):
                p["rerank_score"] = 1.0 - i * 0.01
            return passages[:top_k]


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
