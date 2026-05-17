"""
手动验证脚本：长短期混合记忆系统 Step 4

验证项：
1. 插入 100 条模拟记录（总 token > 144k）
2. 触发清理后确认 P0 保留、P3 清空
3. P1 摘要归档成功，长期记忆文件增大
"""

import asyncio
import sys
import tempfile
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
from _bootstrap import setup_project_paths

setup_project_paths()

from mining_risk_serve.harness.agentfs import AgentFS
from mining_risk_serve.harness.memory import HybridMemoryManager, ShortTermMemory, LongTermMemory


def short_term_validation():
    """验证短期记忆清理策略"""
    print("=" * 60)
    print("[1/3] 短期记忆清理验证")
    print("=" * 60)

    mem = ShortTermMemory(max_tokens=180000, safety_threshold=0.8)
    print(f"Token 上限: {mem.max_tokens}")
    print(f"安全阈值: {mem.safety_threshold}")
    print(f"实际限制: {mem.token_limit} tokens")

    # 插入 P0（永久保留），大小接近 144k 限制
    p0_content = "P0核心指令：严禁瓦斯浓度超限作业，通风系统擅自停运或改造属于重大事故隐患。" * 3000
    mem.add(p0_content, priority="P0")
    print(f"\n已插入 P0: {len(p0_content)} chars, ~{mem._count_tokens(p0_content)} tokens")

    # 再插入少量 P1/P2
    for i in range(3):
        mem.add(f"P1高优先级记忆内容{i}: " + "重要安全规定，必须严格遵守。" * 500, priority="P1")
    for i in range(5):
        mem.add(f"P2中优先级记忆内容{i}: " + "一般巡检记录，日常检查。" * 500, priority="P2")

    # 插入 100 条 P3（低优先级）
    # 由于非 P3 部分已接近限制，每条 P3 加入后都会立即触发清理并被移除
    print("\n正在插入 100 条 P3 模拟记录...")
    for i in range(100):
        content = f"P3冗余记录{i:03d}: 日常巡检日志。" + "检查设备运行状态。" * 100
        mem.add(content, priority="P3")

    all_entries = mem.get_all()
    total_tokens = sum(e["tokens"] for e in all_entries)

    p0_count = len([e for e in all_entries if e["priority"] == "P0"])
    p1_count = len([e for e in all_entries if e["priority"] == "P1"])
    p2_count = len([e for e in all_entries if e["priority"] == "P2"])
    p3_count = len([e for e in all_entries if e["priority"] == "P3"])

    print(f"\n--- 清理后状态 ---")
    print(f"总条目数: {len(all_entries)}")
    print(f"总 tokens: {total_tokens} / {mem.token_limit}")
    print(f"P0 条目: {p0_count}")
    print(f"P1 条目: {p1_count}")
    print(f"P2 条目: {p2_count}")
    print(f"P3 条目: {p3_count}")

    assert p0_count == 1, "P0 必须保留"
    assert p3_count == 0, "P3 应被清空"

    print("\n[PASS] 短期记忆清理验证通过")
    return mem


async def archive_validation(mem: ShortTermMemory):
    """验证 P1 摘要归档"""
    print("\n" + "=" * 60)
    print("[2/3] P1 摘要归档验证")
    print("=" * 60)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        fs = AgentFS(
            db_path=os.path.join(tmpdir, "test.db"),
            git_repo_path=os.path.join(tmpdir, "git"),
        )
        long_term = LongTermMemory(agentfs=fs)
        manager = HybridMemoryManager(short_term=mem, long_term=long_term)

        # 获取归档前文件大小
        archive_path = "memory/风险事件归档.md"
        before_content = fs.read(archive_path)
        before_size = len(before_content)
        print(f"归档前文件大小: {before_size} bytes")

        # 执行归档
        await manager.archive_experience()

        after_content = fs.read(archive_path)
        after_size = len(after_content)
        print(f"归档后文件大小: {after_size} bytes")

        assert after_size > before_size, "归档后文件应增大"
        print("\n[PASS] P1 摘要归档验证通过")


async def long_term_recall_validation():
    """验证长期记忆 RAG 召回"""
    print("\n" + "=" * 60)
    print("[3/3] 长期记忆 RAG 召回验证")
    print("=" * 60)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        from mining_risk_serve.harness.vector_store import VectorStore

        def _mock_embed(texts):
            def _vec(t):
                v = [0.0] * 64
                for i, ch in enumerate(t):
                    v[i % 64] += ord(ch) / 1000.0
                n = sum(x * x for x in v) ** 0.5
                return [x / n for x in v] if n > 0 else v
            return [_vec(t) for t in texts]

        vs = VectorStore(
            persist_directory=os.path.join(tmpdir, "chroma"),
            embedding_fn=_mock_embed,
        )
        vs.add_documents(
            documents=[
                "瓦斯浓度超限事故应急处理",
                "粉尘爆炸预防措施",
                "高温熔融金属喷溅处置",
            ],
            metadatas=[
                {"risk_type": "火灾爆炸", "source_file": "cases.md"},
                {"risk_type": "粉尘爆炸", "source_file": "cases.md"},
                {"risk_type": "高温灼烫", "source_file": "cases.md"},
            ],
            ids=["d1", "d2", "d3"],
        )

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

        results = await ltm.recall("瓦斯浓度", risk_level="火灾爆炸", top_k=3)
        print(f"召回结果数: {len(results)}")
        for r in results:
            print(f"  - {r['text'][:40]}... (score: {r.get('rerank_score', 'N/A')})")

        assert len(results) > 0, "RAG 召回应非空"
        print("\n[PASS] 长期记忆 RAG 召回验证通过")


async def main():
    print("开始 Step 4 长短期混合记忆系统手动验证\n")
    mem = short_term_validation()
    await archive_validation(mem)
    await long_term_recall_validation()
    print("\n" + "=" * 60)
    print("[DONE] 全部验证通过！")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
