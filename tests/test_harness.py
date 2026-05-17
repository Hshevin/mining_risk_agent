"""
Harness 模块单元测试
"""

import os
import tempfile

import pytest

from mining_risk_serve.harness.agentfs import AgentFS
from mining_risk_serve.harness.knowledge_base import KnowledgeBaseManager
from mining_risk_serve.harness.memory import ShortTermMemory
from mining_risk_serve.harness.validation import Checker, MonteCarloValidator, Proposer, ValidationPipeline


class TestKnowledgeBase:
    """测试知识库管理"""

    def test_read_write(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fs = AgentFS(db_path=os.path.join(tmpdir, "test.db"), git_repo_path=os.path.join(tmpdir, "git"))
            kb = KnowledgeBaseManager(agentfs=fs)
            kb.write("test.md", "# Hello")
            content = kb.read("test.md")
            assert "Hello" in content


class TestShortTermMemory:
    """测试短期记忆"""

    def test_add_and_cleanup(self):
        mem = ShortTermMemory(max_tokens=100, safety_threshold=0.8)
        mem.add("这是一条P0级别的核心指令", priority="P0")
        mem.add("这是一条P3级别的冗余信息", priority="P3")
        assert len(mem.get_all()) == 2
        
        # 添加大量 P3 触发清理
        for i in range(20):
            mem.add(f"冗余信息 {i}" * 10, priority="P3")
        
        # P0 应保留
        p0_entries = [e for e in mem.get_all() if e["priority"] == "P0"]
        assert len(p0_entries) == 1


class TestValidation:
    """测试校验系统"""

    def test_proposer(self):
        decision = {
            "predicted_level": "红",
            "probability_distribution": {"红": 0.9, "橙": 0.1, "黄": 0, "蓝": 0},
            "shap_contributions": [{"feature": "瓦斯浓度", "contribution": 0.5}],
            "government_advice": "立即停产",
            "enterprise_advice": "撤离人员",
        }
        props = Proposer.decompose(decision)
        assert len(props) >= 3
        assert props[0]["category"] == "风险定级"

    def test_checker(self):
        checker = Checker()
        props = [
            {"id": "p1", "proposition": "企业风险等级判定为红级", "category": "风险定级"},
        ]
        result = checker.check(props)
        assert "passed" in result
        assert "feedback" in result

    def test_monte_carlo(self):
        validator = MonteCarloValidator(n_samples=5, confidence_threshold=0.6)
        checker = Checker()
        decision = {"predicted_level": "红"}
        result = validator.validate(decision, checker)
        assert "confidence" in result
        assert "risk_assessment" in result

    def test_validation_pipeline(self):
        pipeline = ValidationPipeline()
        decision = {
            "predicted_level": "蓝",
            "probability_distribution": {"蓝": 0.9, "黄": 0.1, "橙": 0, "红": 0},
            "shap_contributions": [],
            "government_advice": "",
            "enterprise_advice": "",
        }
        result = pipeline.run(decision)
        assert "final_decision" in result
        assert result["final_decision"] in ("APPROVE", "MANUAL_REVIEW", "BLOCK", "REJECT")
