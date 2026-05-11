from pathlib import Path

from harness.validation import (
    COMPLIANCE_RULE_REFERENCES,
    FEASIBILITY_RULE_REFERENCES,
    LOGIC_RULE_REFERENCES,
)
from harness.vector_store import split_by_headers
from scripts.rebuild_rule_kbs import (
    COMPLIANCE_FILE,
    PHYSICS_FILE,
    SOP_FILE,
    quality_check,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
KB_DIR = PROJECT_ROOT / "knowledge_base"


def _read(filename: str) -> str:
    return (KB_DIR / filename).read_text(encoding="utf-8")


def test_rule_kb_quality_check_passes():
    summary = quality_check()
    assert summary["all_ok"] is True


def test_three_rule_kbs_have_required_structure():
    for filename in (COMPLIANCE_FILE, PHYSICS_FILE, SOP_FILE):
        text = _read(filename)
        assert text.strip()
        assert "增量更新" not in text
        assert "待填写" not in text
        assert "数据来源" in text
        assert "规则来源" in text
        assert "rule_id" in text or "sop_id" in text


def test_vector_store_can_split_rule_kbs_by_headers():
    for filename in (COMPLIANCE_FILE, PHYSICS_FILE, SOP_FILE):
        chunks = split_by_headers(_read(filename), max_chunk_size=500, overlap=80)
        assert len(chunks) >= 10
        assert all(chunk["metadata"]["section_title"] for chunk in chunks)
        assert any("规则" in chunk["metadata"]["section_title"] for chunk in chunks)


def test_validation_rule_anchors_exist_in_kbs():
    compliance = _read(COMPLIANCE_FILE)
    physics = _read(PHYSICS_FILE)
    sop = _read(SOP_FILE)

    for item in COMPLIANCE_RULE_REFERENCES:
        assert item["rule_id"] in compliance

    for rule_id in LOGIC_RULE_REFERENCES.values():
        assert rule_id in physics

    for rule_id in FEASIBILITY_RULE_REFERENCES.values():
        assert rule_id in sop


def test_rule_kbs_include_local_fact_boundaries():
    joined = "\n".join(_read(filename) for filename in (COMPLIANCE_FILE, PHYSICS_FILE, SOP_FILE))
    assert "public_data_inventory_report.md" in joined
    assert "企业已具备的执行条件.md" in joined
    assert "类似事故处理案例.md" in joined
    assert "A 类真实事故/事件案例为 0" in joined
