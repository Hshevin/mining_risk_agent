"""
Harness 子模块单元测试：三维风险评估、Proposer 拆解。
"""

from __future__ import annotations

import json

import pytest

from harness.proposer import Proposer
from harness.risk_assessment import RiskAssessor, RiskAssessmentResult


class TestRiskAssessor:
    def test_assess_low_level_not_blocked(self):
        r = RiskAssessor(threshold=10.0)
        res = r.assess({"predicted_level": "蓝"})
        assert isinstance(res, RiskAssessmentResult)
        assert res.blocked is False
        assert res.total_score > 0

    def test_assess_high_level_blocked_with_low_threshold(self):
        r = RiskAssessor(threshold=0.1)
        res = r.assess({"predicted_level": "红"})
        assert res.blocked is True

    def test_assess_tool_call_high_risk(self):
        r = RiskAssessor()
        out = r.assess_tool_call("filesystem_delete", (), {})
        assert out["blocked"] is True

    def test_assess_tool_call_medium_risk(self):
        r = RiskAssessor()
        out = r.assess_tool_call("config_write", (), {})
        assert out["blocked"] is False
        assert out["severity"] in ("高", "中", "低", "极高")


class TestProposer:
    def test_decompose_empty_decision(self):
        props = Proposer.decompose({})
        assert props == []

    def test_decompose_full_decision(self):
        decision = {
            "predicted_level": "橙",
            "government_advice": "加强监察" * 5,
            "enterprise_advice": "停产整顿",
            "shap_contributions": [{"feature": "瓦斯", "c": 1}],
            "probability_distribution": {"蓝": 0.1, "橙": 0.6, "红": 0.3},
        }
        props = Proposer.decompose(decision)
        ids = {p["id"] for p in props}
        assert "prop_001" in ids
        assert "prop_005" in ids
        assert any("橙" in p["proposition"] for p in props)

    def test_to_json_roundtrip(self):
        props = [{"id": "1", "proposition": "p", "category": "c"}]
        s = Proposer.to_json(props)
        assert json.loads(s) == props
