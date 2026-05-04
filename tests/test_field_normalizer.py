import os

from data.field_normalizer import normalize_enterprise_record


os.environ.setdefault("GLM5_API_KEY", "test-key")


def test_normalize_chinese_demo_fields_to_training_columns():
    normalized, report = normalize_enterprise_record(
        {
            "企业ID": "CHEM-001",
            "企业名称": "测试危化企业",
            "企业职工总人数": 320,
            "安全生产标准化建设情况": 2,
            "行业监管大类": "危险化学品",
            "国民经济大类": "化学原料和化学制品制造业",
            "是否发生事故": 1,
            "是否发现问题隐患 0-否 1-是": 1,
            "重大危险源数量": 3,
        },
        enterprise_id="REQ-001",
        scenario_id="chemical",
    )

    assert normalized["enterprise_id"] == "REQ-001"
    assert normalized["enterprise_name"] == "测试危化企业"
    assert normalized["staff_num"] == 320
    assert normalized["safety_build"] == 2
    assert normalized["supervision_large"] == "危险化学品"
    assert normalized["indus_type_large"] == "化学原料和化学制品制造业"
    assert normalized["risk_accident_flag"] == 1
    assert normalized["has_risk_item"] == 1
    assert normalized["is_major_hazards"] == 1
    assert normalized["dangerous_chemical_enterprise"] == 1
    assert normalized["risk_whp_flag"] == 1
    assert "staff_num" not in report.defaulted_fields


def test_normalize_preserves_english_field_precedence():
    normalized, _ = normalize_enterprise_record(
        {
            "staff_num": 99,
            "企业职工总人数": 320,
            "supervision_large": "冶金",
            "行业监管大类": "危险化学品",
        },
        enterprise_id="ENT-001",
        scenario_id="chemical",
    )

    assert normalized["staff_num"] == 99
    assert normalized["supervision_large"] == "冶金"


def test_normalize_fills_pipeline_required_columns():
    normalized, report = normalize_enterprise_record(
        {"企业名称": "最小输入企业"},
        enterprise_id="ENT-MIN",
        scenario_id="dust",
    )

    assert normalized["enterprise_id"] == "ENT-MIN"
    assert normalized["staff_num"] == 0
    assert normalized["safety_build"] == "未知"
    assert normalized["cf_source"] == "API输入"
    assert normalized["is_explosive_dust"] == 1
    assert "staff_num" in report.defaulted_fields
