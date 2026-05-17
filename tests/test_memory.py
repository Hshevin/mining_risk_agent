"""
长短期混合记忆系统单元测试

检查点：
- token 超限清理后 P0 仍在、P3 清空
- P1 摘要降级（ConversationSummaryMemory 或兼容层）成功
- P1 摘要归档成功
- RAG 召回非空（VectorStore SelfQuery + BGE-Reranker）
"""

import os
import tempfile

import pytest

from mining_risk_serve.harness.agentfs import AgentFS
from mining_risk_serve.harness.memory import ShortTermMemory, LongTermMemory, HybridMemoryManager
from mining_risk_serve.harness.vector_store import VectorStore


def _char_tokens(text: str) -> int:
    """测试专用确定性 token 计数，避免 tiktoken/fallback 环境差异。"""
    return len(text)


def _short_memory(max_tokens: int, safety_threshold: float = 1.0, llm=None) -> ShortTermMemory:
    return ShortTermMemory(
        max_tokens=max_tokens,
        safety_threshold=safety_threshold,
        llm=llm,
        token_counter=_char_tokens,
    )


# ---------------------------------------------------------------------------
# Mock 嵌入函数（与 test_vector_store.py 保持一致）
# ---------------------------------------------------------------------------
def _mock_embed(texts):
    def _text_to_vec(text):
        vec = [0.0] * 64
        for i, ch in enumerate(text):
            vec[i % 64] += ord(ch) / 1000.0
        norm = sum(x * x for x in vec) ** 0.5
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec
    return [_text_to_vec(t) for t in texts]


class TestShortTermMemory:
    """测试短期记忆：P0-P3 清理策略、tiktoken 计数、LRU"""

    def test_add_and_basic_query(self):
        mem = ShortTermMemory(max_tokens=1000, safety_threshold=0.8)
        mem.add("核心指令", priority="P0")
        mem.add("高优先级", priority="P1")
        mem.add("中优先级", priority="P2")
        mem.add("低优先级", priority="P3")

        assert len(mem.get_all()) == 4
        context = mem.get_context()
        assert "核心指令" in context

    def test_token_cleanup_p0_retained_p3_cleared(self):
        """检查点：token 超限清理后 P0 仍在、P3 清空"""
        mem = _short_memory(max_tokens=30)
        mem.add("0" * 10, priority="P0")
        mem.add("1" * 8, priority="P1")
        mem.add("2" * 10, priority="P2")

        # 非 P3 已接近限值，任何 P3 加入后都应被最先清掉。
        for i in range(20):
            mem.add(f"p3-{i}", priority="P3")

        all_entries = mem.get_all()
        p0_entries = [e for e in all_entries if e["priority"] == "P0"]
        p3_entries = [e for e in all_entries if e["priority"] == "P3"]

        assert len(p0_entries) == 1, "P0 必须保留"
        assert len(p3_entries) == 0, "P3 应被清空"

        total_tokens = sum(e["tokens"] for e in all_entries)
        assert total_tokens <= mem.token_limit

    def test_p2_lossless_compression(self):
        """P2 在超限时应被无损压缩"""
        mem = _short_memory(max_tokens=80)
        mem.add("0" * 10, priority="P0")
        mem.add("2" * 120, priority="P2")

        # P3 先被清理；清理后仍超限，P2 进入压缩阶段。
        mem.add("3" * 20, priority="P3")

        p2_entries = [e for e in mem.get_all() if e["priority"] == "P2"]
        assert len(p2_entries) == 1
        assert "...[压缩]" in p2_entries[0]["content"]
        assert sum(e["tokens"] for e in mem.get_all()) <= mem.token_limit

    def test_p1_summary_downgrade_with_fallback(self):
        """P1 在超限时应被摘要降级（fallback 模式也验证）"""
        mem = _short_memory(max_tokens=80)
        mem.add("0" * 10, priority="P0")
        mem.add("P1" * 60, priority="P1")

        p1_entries = [e for e in mem.get_all() if e["priority"] == "P1"]
        assert len(p1_entries) == 1
        assert "...[摘要]" in p1_entries[0]["content"]

        summaries = mem.get_p1_summaries()
        assert len(summaries) >= 1, "应记录 P1 摘要"
        mem.clear_p1_summaries()
        assert mem.get_p1_summaries() == []

    def test_p1_summary_with_fake_llm(self):
        """检查点：P1 摘要降级使用 LLM（FakeListLLM 测试）"""
        pytest.importorskip("langchain_community", reason="需要 langchain_community")
        from langchain_community.llms.fake import FakeListLLM

        fake_llm = FakeListLLM(responses=["这是P1记忆的摘要结果"])
        mem = _short_memory(max_tokens=80, llm=fake_llm)
        mem.add("0" * 10, priority="P0")
        mem.add("P1" * 60, priority="P1")

        p1_entries = [e for e in mem.get_all() if e["priority"] == "P1"]
        assert len(p1_entries) == 1
        assert "...[摘要]" in p1_entries[0]["content"]

        summaries = mem.get_p1_summaries()
        assert len(summaries) >= 1

    def test_lru_order_within_same_priority(self):
        """同优先级应按 LRU 清理（时间戳老的先处理）"""
        mem = ShortTermMemory(max_tokens=80, safety_threshold=0.8)
        mem.add("P3 oldest", priority="P3")
        mem.add("P3 middle", priority="P3")
        mem.add("P3 newest", priority="P3")
        mem.add("P0 anchor", priority="P0")

        # 再添加大量 P3 触发清理
        for i in range(20):
            mem.add(f"P3 flood {i}" * 5, priority="P3")

        # oldest 应该最先被清理掉
        remaining_contents = [e["content"] for e in mem.get_all() if e["priority"] == "P3"]
        assert "P3 oldest" not in remaining_contents


class TestLongTermMemory:
    """测试长期记忆：AgentFS 归档、VectorStore SelfQuery + Reranker 召回"""

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

    @pytest.mark.asyncio
    async def test_summarize_and_archive(self):
        """检查点：P1 摘要归档成功，长期记忆文件增大"""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            fs = AgentFS(
                db_path=os.path.join(tmpdir, "test.db"),
                git_repo_path=os.path.join(tmpdir, "git"),
            )
            ltm = LongTermMemory(agentfs=fs)

            p1_memories = [
                {"summary": "测试摘要1：瓦斯浓度超限", "metadata": {"risk": "高"}, "timestamp": 0},
                {"summary": "测试摘要2：粉尘爆炸预防", "metadata": {"risk": "中"}, "timestamp": 0},
            ]
            await ltm.summarize_and_archive(p1_memories)

            content = fs.read("memory/风险事件归档.md").decode("utf-8")
            assert "测试摘要1" in content
            assert "测试摘要2" in content
            assert "瓦斯浓度超限" in content

    @pytest.mark.asyncio
    async def test_recall_non_empty(self):
        """检查点：RAG 召回非空（VectorStore SelfQuery + BGE-Reranker）"""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            # 1. 创建 VectorStore 并注入 mock 嵌入
            vs = self._make_store(os.path.join(tmpdir, "chroma"))
            vs.add_documents(
                documents=[
                    "瓦斯浓度超限事故应急处理流程",
                    "粉尘爆炸预防措施与除尘规范",
                    "危化品储罐泄漏巡检要点",
                ],
                metadatas=[
                    {"risk_type": "火灾爆炸", "industry": "煤炭", "source_file": "test.md"},
                    {"risk_type": "粉尘爆炸", "industry": "有色", "source_file": "test.md"},
                    {"risk_type": "危化品泄漏", "industry": "化工", "source_file": "test.md"},
                ],
                ids=["doc1", "doc2", "doc3"],
            )

            # 2. Mock Reranker（避免加载真实模型）
            class MockReranker:
                def rerank(self, query, passages, top_k=5):
                    for i, p in enumerate(passages):
                        p["rerank_score"] = 1.0 - i * 0.01
                    return passages[:top_k]

            fs = AgentFS(
                db_path=os.path.join(tmpdir, "test.db"),
                git_repo_path=os.path.join(tmpdir, "git"),
            )
            ltm = LongTermMemory(agentfs=fs, vector_store=vs, reranker=MockReranker())

            # 3. 召回
            results = await ltm.recall("瓦斯浓度", risk_level="火灾爆炸", top_k=3)
            assert len(results) > 0, "RAG 召回结果应非空"
            assert "rerank_score" in results[0]
            # 由于 SelfQuery 过滤了 risk_type=火灾爆炸，应返回对应文档
            assert any("瓦斯" in r["text"] for r in results)

    @pytest.mark.asyncio
    async def test_recall_with_empty_query(self):
        """空查询应返回空列表"""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            fs = AgentFS(
                db_path=os.path.join(tmpdir, "test.db"),
                git_repo_path=os.path.join(tmpdir, "git"),
            )
            ltm = LongTermMemory(agentfs=fs)
            results = await ltm.recall("")
            assert results == []

    def test_trace_event(self):
        """事故溯源应返回正确结构"""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            fs = AgentFS(
                db_path=os.path.join(tmpdir, "test.db"),
                git_repo_path=os.path.join(tmpdir, "git"),
            )
            ltm = LongTermMemory(agentfs=fs)
            # 先创建一个快照
            commit_id = fs.snapshot("test snapshot")
            result = ltm.trace_event(commit_id)
            assert result["commit_id"] == commit_id
            assert result["status"] == "rollback_completed"


class TestHybridMemoryManager:
    """测试混合记忆管理器"""

    @pytest.mark.asyncio
    async def test_archive_experience(self):
        """端到端：P1 摘要 → 归档 → 清空"""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            fs = AgentFS(
                db_path=os.path.join(tmpdir, "test.db"),
                git_repo_path=os.path.join(tmpdir, "git"),
            )
            short = _short_memory(max_tokens=80)
            long = LongTermMemory(agentfs=fs)
            manager = HybridMemoryManager(short_term=short, long_term=long)

            short.add("0" * 10, priority="P0")
            short.add("P1归档摘要" * 12, priority="P1", metadata={"risk": "高"})

            assert len(short.get_p1_summaries()) >= 1
            await manager.archive_experience()
            assert len(short.get_p1_summaries()) == 0

            content = fs.read(long.memory_files[1]).decode("utf-8")
            assert "P1归档摘要" in content
            assert "...[摘要]" in content

    @pytest.mark.asyncio
    async def test_formal_rag_recall_enabled(self, monkeypatch):
        """RAG 开启时应从正式 var/chroma 返回证据块。"""
        monkeypatch.setenv("RAG_ENABLED", "true")
        manager = HybridMemoryManager()
        try:
            assert manager.is_long_term_rag_enabled() is True
            results = await manager.recall_long_term("粉尘涉爆除尘系统异常", risk_level="红", top_k=3)
            assert results
            joined = "\n".join(r["text"] for r in results)
            assert "粉尘" in joined
            assert "除尘" in joined
        finally:
            store = getattr(manager.long_term, "_vector_store", None)
            if store is not None:
                try:
                    store.client._system.stop()
                except Exception:
                    pass

    @pytest.mark.asyncio
    async def test_rag_disabled_returns_empty(self, monkeypatch):
        """RAG 关闭时长期记忆召回应安全返回空列表。"""
        monkeypatch.setenv("RAG_ENABLED", "false")
        manager = HybridMemoryManager()
        assert manager.is_long_term_rag_enabled() is False
        results = await manager.recall_long_term("粉尘涉爆除尘系统异常", top_k=3)
        assert results == []
