"""
向量检索引擎单元测试
"""

import hashlib
import os
import tempfile

import pytest

from harness.vector_store import VectorStore, split_by_headers
from utils.config import resolve_project_path


def _mock_embed(texts):
    """确定性 mock 嵌入函数，用于测试"""
    def _text_to_vec(text):
        # 生成 64 维确定性向量
        vec = [0.0] * 64
        for i, ch in enumerate(text):
            vec[i % 64] += ord(ch) / 1000.0
        # 归一化
        norm = sum(x * x for x in vec) ** 0.5
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec
    return [_text_to_vec(t) for t in texts]


class TestSplitByHeaders:
    """测试 Markdown 按标题切分"""

    def test_simple_split(self):
        text = "# Title\n\nParagraph 1.\n\n## Section\n\nParagraph 2."
        chunks = split_by_headers(text, max_chunk_size=300)
        assert len(chunks) >= 2
        assert chunks[0]["metadata"]["section_title"] == "Title"
        assert chunks[1]["metadata"]["section_title"] == "Section"

    def test_chunk_size_limit(self):
        text = "# Title\n\n" + "A" * 500
        chunks = split_by_headers(text, max_chunk_size=300)
        assert len(chunks) >= 1
        for c in chunks:
            assert len(c["text"]) <= 350  # 允许少量超出

    def test_empty_text(self):
        assert split_by_headers("") == []
        assert split_by_headers("   ") == []


class TestVectorStore:
    """测试向量存储与 SelfQuery 检索"""

    @pytest.fixture(autouse=True)
    def _cleanup_stores(self):
        self._stores = []
        yield
        for store in self._stores:
            try:
                store.client._system.stop()
            except Exception:
                pass

    def _make_store(self, persist_directory: str):
        store = VectorStore(persist_directory=persist_directory, embedding_fn=_mock_embed)
        self._stores.append(store)
        return store

    def test_add_and_search(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            store = self._make_store(tmpdir)
            store.add_documents(
                documents=["高炉煤气泄漏应急处理", "粉尘爆炸预防措施", "危化品储罐巡检规范"],
                metadatas=[
                    {"risk_type": "火灾爆炸", "industry": "钢铁"},
                    {"risk_type": "粉尘爆炸", "industry": "有色"},
                    {"risk_type": "危化品泄漏", "industry": "化工"},
                ],
                ids=["doc1", "doc2", "doc3"],
            )
            results = store.similarity_search("煤气泄漏", top_k=2)
            assert len(results) == 2
            assert all("text" in r for r in results)

    def test_self_query_filter(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            store = self._make_store(tmpdir)
            store.add_documents(
                documents=[
                    "高炉煤气泄漏需立即停炉并切断气源",
                    "粉尘除尘器故障应立即停机",
                    "煤气管道压力超标启动泄压",
                ],
                metadatas=[
                    {"risk_type": "火灾爆炸", "industry": "钢铁", "doc_type": "cases"},
                    {"risk_type": "粉尘爆炸", "industry": "有色", "doc_type": "cases"},
                    {"risk_type": "火灾爆炸", "industry": "钢铁", "doc_type": "physics"},
                ],
                ids=["doc1", "doc2", "doc3"],
            )
            
            # 过滤 risk_type = 火灾爆炸
            results = store.self_query_retrieve(
                query="高炉煤气泄漏",
                filters={"risk_type": "火灾爆炸"},
                top_k=5,
            )
            assert len(results) >= 1
            for r in results:
                assert r["metadata"]["risk_type"] == "火灾爆炸"
            
            # 组合过滤
            results2 = store.self_query_retrieve(
                query="煤气",
                filters={"risk_type": "火灾爆炸", "industry": "钢铁"},
                top_k=5,
            )
            assert len(results2) >= 1
            for r in results2:
                assert r["metadata"]["risk_type"] == "火灾爆炸"
                assert r["metadata"]["industry"] == "钢铁"

    def test_self_query_no_match(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            store = self._make_store(tmpdir)
            store.add_documents(
                documents=["高炉煤气泄漏"],
                metadatas=[{"risk_type": "火灾爆炸"}],
                ids=["doc1"],
            )
            results = store.self_query_retrieve(
                query="煤气",
                filters={"risk_type": "不存在"},
                top_k=5,
            )
            assert results == []

    def test_load_from_kb(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            kb_dir = os.path.join(tmpdir, "kb")
            os.makedirs(kb_dir, exist_ok=True)
            # 创建测试 markdown
            with open(os.path.join(kb_dir, "test.md"), "w", encoding="utf-8") as f:
                f.write("# 测试文档\n\n这是关于瓦斯爆炸的内容。\n\n## 子章节\n\n煤气泄漏处理。\n")
            
            store = self._make_store(os.path.join(tmpdir, "chroma"))
            count = store.load_from_kb(kb_dir)
            assert count > 0
            
            results = store.similarity_search("瓦斯", top_k=3)
            assert len(results) > 0
            assert any("瓦斯" in r["text"] for r in results)

    def test_clear(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            store = self._make_store(tmpdir)
            store.add_documents(documents=["test"], metadatas=[{"doc_type": "test"}], ids=["doc1"])
            store.clear()
            results = store.similarity_search("test", top_k=1)
            assert results == []


class TestFormalRagIndex:
    """正式 data/chroma_db 索引冒烟测试。"""

    @pytest.fixture(autouse=True)
    def _cleanup_store(self):
        self._store = None
        yield

    def _formal_store(self):
        self._store = VectorStore(
            persist_directory="data/chroma_db",
            collection_name="knowledge_base",
            embedding_backend="fallback",
        )
        return self._store

    def test_formal_index_exists_and_collection_name(self):
        persist_dir = resolve_project_path("data/chroma_db")
        assert persist_dir.exists()
        assert (persist_dir / "chroma.sqlite3").exists()

        store = self._formal_store()
        assert store.collection.name == "knowledge_base"
        assert store.collection.count() > 100

    @pytest.mark.parametrize(
        ("query", "required_terms"),
        [
            ("粉尘涉爆除尘系统异常", ("粉尘", "除尘")),
            ("危化品泄漏处置", ("危化", "泄漏")),
            ("冶金煤气报警", ("冶金", "煤气")),
            ("有限空间作业中毒窒息", ("有限空间", "中毒")),
        ],
    )
    def test_formal_index_recalls_related_text(self, query, required_terms):
        store = self._formal_store()
        results = store.similarity_search(query, top_k=5)
        assert results
        joined = "\n".join(r["text"] for r in results)
        for term in required_terms:
            assert term in joined
