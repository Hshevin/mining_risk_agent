import json
from pathlib import Path

from harness.vector_store import split_by_headers
from scripts.sync_kb_to_agentfs import get_paths, verify_agentfs_content


PROJECT_ROOT = Path(__file__).resolve().parents[1]
KB_FILE = PROJECT_ROOT / "knowledge_base" / "类似事故处理案例.md"
REPORT_FILE = PROJECT_ROOT / "reports" / "accident_cases_kb_rebuild_run.json"


def _read_text() -> str:
    return KB_FILE.read_text(encoding="utf-8")


def test_accident_cases_kb_exists_and_replaces_template_library():
    assert KB_FILE.exists()
    text = _read_text()

    assert len(text.strip()) > 30000
    assert "当前数据集中暂无 ACCIDENT=1 或 EVENT=1 的记录" not in text
    assert "增量更新" not in text
    assert "证据来源文件和字段" in text
    assert "本轮不生成 A 类真实事故/事件详案" in text
    assert "真实性口径：本库不伪造事故" in text


def test_accident_cases_kb_has_real_b_c_d_cases_and_separate_templates():
    text = _read_text()

    assert text.count("### B-") >= 12
    assert text.count("### C-") >= 12
    assert text.count("### D-") >= 12
    assert text.count("### E-") == 3
    assert "| 真实公开数据案例 | 36 |" in text
    assert "| B 类重大隐患与未整改闭环案例 |" in text
    assert "| C 类执法处罚与违法行为案例 |" in text
    assert "| D 类高风险企业风险组合案例 |" in text
    assert "模板案例，未从本地公开数据确认具体事故" in text


def test_each_real_case_class_contains_required_rag_fields():
    text = _read_text()
    sections = [section for section in text.split("\n### ") if section.startswith(("B-", "C-", "D-"))]

    assert len(sections) >= 36
    required = [
        "case_id：",
        "企业名称/脱敏 ID：",
        "行业/监管类别：",
        "风险场景：",
        "触发信号：",
        "证据来源文件和字段：",
        "风险链条：",
        "推荐处置流程：",
        "整改/复查建议：",
        "可检索关键词：",
    ]
    for section in sections[:36]:
        for marker in required:
            assert marker in section


def test_accident_cases_report_records_counts_and_sources():
    assert REPORT_FILE.exists()
    report = json.loads(REPORT_FILE.read_text(encoding="utf-8"))

    assert report["readable_tables"] == 66
    assert report["case_counts"]["A_real_accident_event"] == 0
    assert report["case_counts"]["B_hidden_danger_real"] >= 12
    assert report["case_counts"]["C_penalty_real"] >= 12
    assert report["case_counts"]["D_risk_combination_real"] >= 12
    assert report["case_counts"]["E_templates"] == 3
    assert report["candidate_stats"]["B"]["major_hidden_danger_candidates"] >= 1
    assert report["candidate_stats"]["C"]["deduplicated_candidates"] >= 10
    assert report["candidate_stats"]["D"]["deduplicated_candidates"] >= 10


def test_accident_cases_kb_can_split_by_headers():
    chunks = split_by_headers(_read_text(), max_chunk_size=700, overlap=100)
    titles = [chunk["metadata"]["section_title"] for chunk in chunks]

    assert len(chunks) >= 80
    assert all(chunk["text"].strip() for chunk in chunks)
    assert any("B-001" in title for title in titles)
    assert any("C-001" in title for title in titles)
    assert any("D-001" in title for title in titles)
    assert any("模板/外部待补案例" in title for title in titles)


def test_accident_cases_agentfs_matches_filesystem_after_sync():
    db_path, _, _, kb_dir = get_paths()
    verification = verify_agentfs_content(db_path, kb_dir)
    target = next(item for item in verification if item["path"].endswith("类似事故处理案例.md"))

    assert target["matches"]
