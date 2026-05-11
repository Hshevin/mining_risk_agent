import pytest

from scripts.audit_knowledge_system import FAIL, PASS, WARN, render_markdown_report, run_audit


@pytest.fixture(scope="module")
def audit_summary():
    """Run the read-only knowledge-system audit once for this test module."""
    return run_audit(sample_rows=3)


def _by_name(summary, name):
    for item in summary["results"]:
        if item["name"] == name:
            return item
    raise AssertionError(f"missing audit result: {name}")


def test_audit_core_gate_has_no_failures(audit_summary):
    assert audit_summary["status_counts"][FAIL] == 0
    assert audit_summary["overall_status"] in {"PASS", "PASS_WITH_WARNINGS"}


@pytest.mark.parametrize(
    "name",
    [
        "config.public_data_paths_exist",
        "dataloader.public_data_readability",
        "kb.six_main_files_exist_non_empty",
        "kb.no_duplicate_incremental_update_blocks",
        "kb.no_large_scale_empty_table_placeholders",
        "kb.no_pending_placeholder_text",
        "kb.enterprise_conditions_public_statistics",
        "kb.accident_cases_bcd_real_public_data_cases",
        "kb.rule_libraries_have_com_phy_sop_ids",
    ],
)
def test_public_data_and_kb_quality_gates_pass(audit_summary, name):
    assert _by_name(audit_summary, name)["status"] == PASS


def test_agentfs_rag_validation_and_memory_gates_pass(audit_summary):
    expected_passes = [
        "agentfs.six_kb_byte_identical",
        "rag.formal_chroma_index",
        "rag.query_returns_evidence_blocks",
        "validation.evidence_has_source_and_ids",
        "memory.p1_summary_archives_to_agentfs",
        "workflow.light_e2e_mocked_llm",
    ]
    for name in expected_passes:
        assert _by_name(audit_summary, name)["status"] == PASS

    rag = _by_name(audit_summary, "rag.formal_chroma_index")
    assert rag["evidence"]["collection_count"] >= 100

    validation = _by_name(audit_summary, "validation.evidence_has_source_and_ids")
    assert validation["evidence"]["rule_evidence"][0]["source_file"]
    assert validation["evidence"]["sop_evidence"][0]["source_file"]
    assert validation["evidence"]["case_evidence"][0]["source_file"]

    workflow = _by_name(audit_summary, "workflow.light_e2e_mocked_llm")
    assert workflow["evidence"]["external_llm_called"] is False
    assert workflow["evidence"]["memory_recall_calls"] == 1


def test_expected_production_gaps_are_warnings(audit_summary):
    expected_warnings = [
        "gap.real_bge_embedding_reranker",
        "gap.a_class_real_accident_detail",
        "gap.legal_article_number_review",
        "gap.threshold_calibration",
        "gap.agentfs_deprecated_malformed_path",
        "gap.department_real_contacts",
    ]
    for name in expected_warnings:
        assert _by_name(audit_summary, name)["status"] == WARN


def test_markdown_report_is_solution_acceptance_oriented(audit_summary):
    report = render_markdown_report(audit_summary)
    assert "方案要求 | 当前实现 | 验收证据 | 是否达标 | 剩余问题 | 改进建议" in report
    assert "当前仍使用 deterministic fallback embedding/reranker" in report
    assert "本地公开数据无法确认 A 类真实事故详案" in report
    assert "轻量工作流使用 mock LLM" in report
