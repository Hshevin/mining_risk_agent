import asyncio
import os
import tempfile

from fastapi.testclient import TestClient

from mining_risk_serve.api.main import create_app
from mining_risk_serve.api.routers import memory as memory_router
from mining_risk_serve.harness.agentfs import AgentFS
from mining_risk_serve.harness.memory import LongTermMemory, ShortTermMemory
from mining_risk_serve.harness.memory_statistics import MemoryStatsFilters, build_statistics_payload


def _char_tokens(text: str) -> int:
    return len(text)


def _temp_agentfs(tmpdir: str) -> AgentFS:
    return AgentFS(
        db_path=os.path.join(tmpdir, "agentfs.db"),
        git_repo_path=os.path.join(tmpdir, "git"),
    )


def test_short_term_add_visible_in_memory_statistics():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        fs = _temp_agentfs(tmpdir)
        short = ShortTermMemory(max_tokens=1000, safety_threshold=1.0, token_counter=_char_tokens)
        short.add("粉尘涉爆除尘系统异常，按 P0 核心指令保留", priority="P0", metadata={"risk_type": "粉尘涉爆"})

        payload = build_statistics_payload(agentfs=fs, short_term=short)

        assert payload["short_term"]["total"] == 1
        assert payload["short_term"]["priority_distribution"]["P0"] == 1
        assert payload["charts"]["priority_bar"]
        assert any(record["module"] == "short_term" for record in payload["recent_records"])


def test_p1_archive_updates_long_term_statistics_and_write_log():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        fs = _temp_agentfs(tmpdir)
        long_term = LongTermMemory(agentfs=fs)

        asyncio.run(long_term.summarize_and_archive([
            {
                "summary": "P1 摘要：粉尘涉爆除尘压差异常，已生成复查经验",
                "metadata": {"risk_type": "粉尘涉爆", "risk_level": "红"},
                "timestamp": 0,
            }
        ]))

        payload = build_statistics_payload(agentfs=fs)

        assert payload["long_term"]["total_entries"] >= 1
        assert payload["long_term"]["risk_type_distribution"].get("粉尘涉爆", 0) >= 1
        assert payload["agentfs_operations"]["counts"]["WRITE"] >= 1


def test_memory_statistics_and_export_api(monkeypatch):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        fs = _temp_agentfs(tmpdir)
        long_term = LongTermMemory(agentfs=fs)
        asyncio.run(long_term.summarize_and_archive([
            {
                "summary": "P1 摘要：危化品泄漏处置经验",
                "metadata": {"risk_type": "危化品", "risk_level": "橙"},
                "timestamp": 0,
            }
        ]))
        short = ShortTermMemory(max_tokens=1000, safety_threshold=1.0, token_counter=_char_tokens)
        short.add("短期记忆：冶金煤气报警 P2", priority="P2", metadata={"risk_type": "冶金煤气"})

        monkeypatch.setattr(memory_router, "_get_agentfs", lambda: fs)
        monkeypatch.setattr(memory_router, "_get_runtime_short_term", lambda: short)
        client = TestClient(create_app())

        stats_resp = client.get("/api/v1/memory/statistics", params={"refresh": "true"})
        assert stats_resp.status_code == 200
        stats = stats_resp.json()
        assert stats["short_term"]["total"] == 1
        assert stats["long_term"]["total_entries"] >= 1

        csv_resp = client.get("/api/v1/memory/export", params={"format": "csv", "module": "all"})
        assert csv_resp.status_code == 200
        assert "text/csv" in csv_resp.headers["content-type"]
        assert "危化品" in csv_resp.content.decode("utf-8-sig")

        pdf_resp = client.get("/api/v1/memory/export", params={"format": "pdf", "module": "all"})
        assert pdf_resp.status_code == 200
        assert pdf_resp.content.startswith(b"%PDF")
