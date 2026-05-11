"""
重排序模块单元测试
"""

import pytest

from harness.reranker import Reranker, rerank


class TestReranker:
    """测试重排序器"""

    def test_rerank_empty(self):
        r = Reranker()
        assert r.rerank("query", [], top_k=5) == []

    def test_rerank_fallback(self):
        """测试模型加载失败时的回退逻辑"""
        r = Reranker(model_name="nonexistent-model")
        passages = [
            {"text": "高炉煤气泄漏处理", "metadata": {"a": 1}},
            {"text": "粉尘爆炸预防", "metadata": {"a": 2}},
            {"text": "危化品储罐规范", "metadata": {"a": 3}},
        ]
        results = r.rerank("煤气泄漏", passages, top_k=2)
        assert len(results) == 2
        assert "rerank_score" in results[0]
        assert results[0]["text"] == "高炉煤气泄漏处理"

    def test_rerank_top_k(self):
        r = Reranker(model_name="nonexistent-model")
        passages = [{"text": f"doc{i}"} for i in range(10)]
        results = r.rerank("query", passages, top_k=3)
        assert len(results) == 3

    def test_rerank_convenience_function(self):
        passages = [{"text": "test"}]
        results = rerank("query", passages, top_k=1, model_name="nonexistent-model")
        assert len(results) == 1
