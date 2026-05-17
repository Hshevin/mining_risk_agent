from pathlib import Path

from mining_risk_serve.harness.vector_store import split_by_headers


PROJECT_ROOT = Path(__file__).resolve().parents[1]
KB_FILE = PROJECT_ROOT / "knowledge_base" / "企业已具备的执行条件.md"


def test_enterprise_conditions_kb_exists_and_has_quality_sections():
    assert KB_FILE.exists()
    text = KB_FILE.read_text(encoding="utf-8")

    assert len(text.strip()) > 5000
    assert text.count("| - |") <= 5
    assert "数据来源" in text
    assert "缺失率" in text
    assert "粉尘涉爆执行条件" in text
    assert "冶金设备执行条件" in text
    assert "危化品与重大危险源执行条件" in text
    assert "有限空间执行条件" in text
    assert "高风险企业 Top 清单" in text
    assert "AgentFS 同步建议" in text
    assert "未知" in text
    assert "无记录" in text


def test_enterprise_conditions_kb_can_split_by_headers():
    text = KB_FILE.read_text(encoding="utf-8")
    chunks = split_by_headers(text, max_chunk_size=500, overlap=80)
    titles = [chunk["metadata"]["section_title"] for chunk in chunks]

    assert len(chunks) >= 10
    assert all(chunk["text"].strip() for chunk in chunks)
    assert any("粉尘涉爆" in title for title in titles)
    assert any("冶金" in title for title in titles)
    assert any("危化品" in title for title in titles)
    assert any("有限空间" in title for title in titles)
