"""
Step 5 三重校验与高风险阻断机制测试
覆盖：合规红线拦截、蒙特卡洛低置信度触发、三维高风险阻断
"""

import os
import tempfile

import pytest

from mining_risk_serve.harness.agentfs import AgentFS
from mining_risk_serve.harness.knowledge_base import KnowledgeBaseManager
from mining_risk_serve.harness.monte_carlo import MonteCarloResult, MonteCarloValidator, SamplingNode
from mining_risk_serve.harness.proposer import Proposer
from mining_risk_serve.harness.risk_assessment import RiskAssessor, RiskAssessmentResult
from mining_risk_serve.harness.rks import RecursiveKnowledgeSynthesizer
from mining_risk_serve.harness.validation import (
    Checker,
    EvidenceRetriever,
    ToolCallInterceptor,
    ValidationPipeline,
    ValidationResult,
    compliance_checker,
    feasibility_checker,
    logic_checker,
    run_march_validation,
)
from mining_risk_common.utils.exceptions import HighRiskBlockedError


def _evidence_items(vr):
    return [item.model_dump() if hasattr(item, "model_dump") else item for item in vr.evidence]


class TestComplianceChecker:
    """合规红线 Checker 测试"""

    def test_blocks_destruction_of_monitoring_records(self):
        """手动验证：构造违规决策"建议企业自行销毁监控记录"，确认 MARCH 在 compliance_checker 阶段拦截"""
        state = {
            "atomic_propositions": [
                {
                    "id": "p1",
                    "proposition": "建议企业自行销毁监控记录",
                    "category": "企业管控",
                },
            ],
            "raw_data": {"should_not_access": True},
            "decision": {"should_not_access": True},
        }
        result = compliance_checker(state)
        vr = result["validation_result"]
        assert vr.pass_ is False
        assert "p1" in vr.violated_propositions
        assert "销毁" in vr.reason or "监控" in vr.reason
        evidence = _evidence_items(vr)
        assert evidence
        assert any(e.get("rule_id", "").startswith("COM-") or e.get("source_file") == "builtin_fallback_rules" for e in evidence)
        assert "证据：" in vr.reason

    def test_blocks_closing_alarm_device_with_evidence(self):
        """关闭报警设备继续生产必须被合规红线拦截并返回证据"""
        state = {
            "atomic_propositions": [
                {
                    "id": "p_alarm",
                    "proposition": "建议关闭报警设备继续生产",
                    "category": "企业管控",
                },
            ],
        }
        result = compliance_checker(state)
        vr = result["validation_result"]
        assert vr.pass_ is False
        assert "p_alarm" in vr.violated_propositions
        evidence = _evidence_items(vr)
        assert evidence
        assert any(e.get("rule_id") == "COM-RED-005" or e.get("source_file") == "builtin_fallback_rules" for e in evidence)

    def test_blocks_red_line_keywords(self):
        """测试合规红线关键词拦截"""
        state = {
            "atomic_propositions": [
                {
                    "id": "p2",
                    "proposition": "瓦斯浓度超限情况下继续作业",
                    "category": "企业管控",
                },
            ],
        }
        result = compliance_checker(state)
        vr = result["validation_result"]
        assert vr.pass_ is False
        assert "瓦斯浓度超限" in vr.reason

    def test_passes_valid_advice(self):
        """正常建议应通过合规校验"""
        state = {
            "atomic_propositions": [
                {
                    "id": "p3",
                    "proposition": "建议企业加强通风管理并定期检测瓦斯浓度",
                    "category": "企业管控",
                },
            ],
        }
        result = compliance_checker(state)
        vr = result["validation_result"]
        assert vr.pass_ is True
        assert vr.reason == "合规红线校验通过"
        assert vr.evidence == []

    def test_information_isolation(self):
        """Checker 节点禁止访问 state["raw_data"] 与 state["decision"]"""
        state = {
            "atomic_propositions": [
                {"id": "p1", "proposition": "测试命题", "category": "测试"},
            ],
            "raw_data": {"secret": "do_not_access"},
            "decision": {"secret": "do_not_access"},
        }
        # 校验器应仅读取 atomic_propositions，不因 raw_data/decision 中的内容改变行为
        result = compliance_checker(state)
        vr = result["validation_result"]
        assert vr.pass_ is True  # 测试命题不触发任何红线


class TestLogicChecker:
    """工况逻辑 Checker 测试"""

    def test_blocks_physics_conflict(self):
        state = {
            "atomic_propositions": [
                {
                    "id": "p1",
                    "proposition": "环境温度超过 100°C 正常",
                    "category": "风险定级",
                },
            ],
        }
        result = logic_checker(state)
        vr = result["validation_result"]
        assert vr.pass_ is False
        assert "100°C" in vr.reason

    def test_blocks_zero_gas_normal_production_with_phy_evidence(self):
        """瓦斯浓度 0% 且正常生产必须被 PHY 证据拦截"""
        state = {
            "atomic_propositions": [
                {
                    "id": "p_gas0",
                    "proposition": "瓦斯浓度 0% 且正常生产",
                    "category": "风险定级",
                },
            ],
        }
        result = logic_checker(state)
        vr = result["validation_result"]
        assert vr.pass_ is False
        evidence = _evidence_items(vr)
        assert evidence
        assert any(e.get("rule_id", "").startswith("PHY-") or e.get("source_file") == "builtin_fallback_rules" for e in evidence)

    def test_passes_valid_logic(self):
        state = {
            "atomic_propositions": [
                {
                    "id": "p1",
                    "proposition": "瓦斯浓度 0.8% 触发预警",
                    "category": "风险定级",
                },
            ],
        }
        result = logic_checker(state)
        vr = result["validation_result"]
        assert vr.pass_ is True


class TestFeasibilityChecker:
    """处置可行性 Checker 测试"""

    def test_blocks_micro_enterprise_shutdown(self):
        state = {
            "atomic_propositions": [
                {
                    "id": "p1",
                    "proposition": "建议微型企业立即停产",
                    "category": "企业管控",
                },
            ],
        }
        result = feasibility_checker(state)
        vr = result["validation_result"]
        assert vr.pass_ is False
        assert "微型企业" in vr.reason

    def test_blocks_micro_enterprise_large_system_purchase_with_evidence(self):
        """微型企业立即购置大型成套系统必须被可行性校验拦截"""
        state = {
            "atomic_propositions": [
                {
                    "id": "p_micro_purchase",
                    "proposition": "建议微型企业立即购置大型成套系统",
                    "category": "企业管控",
                },
            ],
        }
        result = feasibility_checker(state)
        vr = result["validation_result"]
        assert vr.pass_ is False
        evidence = _evidence_items(vr)
        assert evidence
        assert any(
            e.get("doc_type") in ("conditions", "sop", "cases")
            or e.get("source_file") == "builtin_fallback_rules"
            for e in evidence
        )

    def test_passes_feasible_advice(self):
        state = {
            "atomic_propositions": [
                {
                    "id": "p1",
                    "proposition": "建议大型企业立即停产并撤离人员",
                    "category": "企业管控",
                },
            ],
        }
        result = feasibility_checker(state)
        vr = result["validation_result"]
        assert vr.pass_ is True


class TestGradedSequence:
    """分级顺序执行测试：合规红线→工况逻辑→处置可行性"""

    def test_compliance_failure_stops_at_level1(self):
        """合规红线失败应立即暂停，不再执行后续校验"""
        state = {
            "atomic_propositions": [
                {
                    "id": "p1",
                    "proposition": "建议企业自行销毁监控记录",
                    "category": "企业管控",
                },
                {
                    "id": "p2",
                    "proposition": "温度超过 100°C 正常",
                    "category": "风险定级",
                },
            ],
        }
        result = run_march_validation(state)
        vr = result["validation_result"]
        assert vr.pass_ is False
        assert "合规红线" in vr.reason
        # 由于 p1 已触发拦截，不应出现 p2 的物理常识错误
        assert "100°C" not in vr.reason

    def test_logic_failure_stops_at_level2(self):
        """工况逻辑失败应立即暂停，不再执行处置可行性"""
        state = {
            "atomic_propositions": [
                {
                    "id": "p1",
                    "proposition": "企业风险等级判定为三级",
                    "category": "风险定级",
                },
                {
                    "id": "p2",
                    "proposition": "温度超过 100°C 正常",
                    "category": "风险定级",
                },
                {
                    "id": "p3",
                    "proposition": "建议微型企业立即停产",
                    "category": "企业管控",
                },
            ],
        }
        result = run_march_validation(state)
        vr = result["validation_result"]
        assert vr.pass_ is False
        assert "[工况逻辑]" in vr.reason
        assert "100°C" in vr.reason
        # 不应出现可行性错误
        assert "微型企业" not in vr.reason

    def test_all_passed(self):
        state = {
            "atomic_propositions": [
                {
                    "id": "p1",
                    "proposition": "企业风险等级判定为四级",
                    "category": "风险定级",
                },
            ],
        }
        result = run_march_validation(state)
        vr = result["validation_result"]
        assert vr.pass_ is True
        assert "全部通过" in vr.reason


class TestValidationResultModel:
    """Pydantic 模型测试"""

    def test_construct_with_pass_alias(self):
        """支持 pass 别名构造（通过 **kwargs 绕过关键字限制）"""
        vr = ValidationResult(**{"pass": True}, violated_propositions=[], reason="ok")
        assert vr.pass_ is True

    def test_construct_with_pass_underscore(self):
        vr = ValidationResult(pass_=False, violated_propositions=["p1"], reason="fail")
        assert vr.pass_ is False

    def test_serialization(self):
        vr = ValidationResult(pass_=True, reason="ok")
        data = vr.model_dump(by_alias=True)
        assert "pass" in data
        assert data["pass"] is True
        assert "evidence" in data


class TestEvidenceFallback:
    """RAG 关闭或索引缺失时仍应能用 Markdown / builtin fallback 跑通。"""

    def test_checker_works_when_rag_disabled(self, monkeypatch):
        monkeypatch.setenv("HARNESS_RAG_ENABLED", "false")
        state = {
            "atomic_propositions": [
                {
                    "id": "p_no_rag",
                    "proposition": "建议企业自行销毁监控记录",
                    "category": "企业管控",
                },
            ],
        }
        result = compliance_checker(state)
        vr = result["validation_result"]
        assert vr.pass_ is False
        assert vr.evidence

    def test_retriever_falls_back_when_index_missing(self, monkeypatch):
        monkeypatch.delenv("HARNESS_RAG_ENABLED", raising=False)
        missing_index = os.path.join("tmp_pytest", "validation_missing_chroma_no_index")
        retriever = EvidenceRetriever(persist_directory=missing_index)
        evidence = retriever.retrieve(
            query="销毁监控记录 COM-RED-018",
            layer="compliance",
            doc_types=["compliance"],
            preferred_ids=["COM-RED-018"],
            top_k=2,
            proposition_id="p_missing_index",
        )
        assert evidence
        assert any(item.source_file.endswith("工矿风险预警智能体合规执行书.md") for item in evidence)


class TestMonteCarlo:
    """蒙特卡洛置信度检验测试"""

    def test_low_confidence_triggers_human_review(self):
        """手动验证：蒙特卡洛 20 次采样，置信度 < 0.85 时状态流转至 HUMAN_REVIEW"""
        node = SamplingNode(n_samples=20, confidence_threshold=0.85)

        # 构造自定义 validator：前 8 次失败，后 12 次通过 -> 置信度 0.6 < 0.85
        def failing_validator(state):
            sample_id = state.get("sample_id", 0)
            passed = sample_id >= 8
            return {
                "validation_result": ValidationResult(
                    pass_=passed,
                    reason="ok" if passed else "fail",
                )
            }

        result = node.sample({"predicted_level": "蓝"}, validator=failing_validator)
        assert isinstance(result, MonteCarloResult)
        assert result.status == "HUMAN_REVIEW"
        assert result.confidence == 0.6
        assert result.passed is False

    def test_high_confidence_approves(self):
        node = SamplingNode(n_samples=20, confidence_threshold=0.85)

        def passing_validator(state):
            return {
                "validation_result": ValidationResult(
                    pass_=True,
                    reason="ok",
                )
            }

        result = node.sample({"predicted_level": "蓝"}, validator=passing_validator)
        assert result.status == "APPROVE"
        assert result.confidence == 1.0
        assert result.passed is True

    def test_legacy_monte_carlo_validator(self):
        """兼容旧接口的 MonteCarloValidator"""
        validator = MonteCarloValidator(n_samples=5, confidence_threshold=0.6)
        checker = Checker()
        decision = {"predicted_level": "红"}
        result = validator.validate(decision, checker)
        assert "confidence" in result
        assert "risk_assessment" in result
        assert "samples" in result


class TestRiskAssessor:
    """三维风险评估测试"""

    def test_high_risk_blocked(self):
        """一级/红 风险应触发阻断"""
        assessor = RiskAssessor()
        decision = {"predicted_level": "红"}
        result = assessor.assess(decision)
        assert isinstance(result, RiskAssessmentResult)
        assert result.blocked is True
        assert result.risk_level in ("HIGH", "EXTREME")
        assert result.severity == "极高"

    def test_medium_risk(self):
        assessor = RiskAssessor()
        decision = {"predicted_level": "黄"}
        result = assessor.assess(decision)
        assert result.risk_level == "MEDIUM"
        # 中=2, weighted = 2*0.5 + 2*0.3 + 2*0.2 = 2.0, threshold=2.5 -> blocked=False
        assert result.blocked is False

    def test_low_risk_passes(self):
        assessor = RiskAssessor()
        decision = {"predicted_level": "蓝"}
        result = assessor.assess(decision)
        assert result.blocked is False
        assert result.risk_level == "LOW"
        assert result.severity == "低"


class TestToolCallInterceptor:
    """工具调用拦截器测试"""

    def test_intercepts_high_risk_tool(self):
        interceptor = ToolCallInterceptor()

        def delete_tool():
            return "deleted"

        with pytest.raises(HighRiskBlockedError):
            interceptor.intercept("delete_database", delete_tool)

        assert len(interceptor.intercepted_calls) == 1
        assert interceptor.intercepted_calls[0]["risk"]["blocked"] is True

    def test_allows_safe_tool(self):
        interceptor = ToolCallInterceptor()

        def read_tool():
            return "data"

        result = interceptor.intercept("read_data", read_tool)
        assert result == "data"
        assert interceptor.intercepted_calls[0]["risk"]["blocked"] is False

    def test_wrap_decorator(self):
        interceptor = ToolCallInterceptor()

        def write_tool(content: str) -> str:
            return f"wrote {content}"

        wrapped = interceptor.wrap("write_file", write_tool)
        # write_file 属于中风险，不应阻断
        result = wrapped("hello")
        assert result == "wrote hello"


class TestBackwardCompatibility:
    """向后兼容测试：确保旧接口仍然可用"""

    def test_proposer_decompose(self):
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

    def test_checker_compat(self):
        checker = Checker()
        props = [
            {"id": "p1", "proposition": "企业风险等级判定为红级", "category": "风险定级"},
        ]
        result = checker.check(props)
        assert "passed" in result
        assert "feedback" in result

    def test_validation_pipeline_compat(self):
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


class TestRKS:
    """递归知识合成测试"""

    def test_synthesize_rejection(self):
        tmpdir = tempfile.mkdtemp()
        try:
            fs = AgentFS(
                db_path=os.path.join(tmpdir, "test.db"),
                git_repo_path=os.path.join(tmpdir, "git"),
            )
            kb = KnowledgeBaseManager(agentfs=fs)
            rks = RecursiveKnowledgeSynthesizer(kb_manager=kb)

            result = rks.synthesize_rejection(
                scenario="瓦斯超限未撤人",
                wrong_decision="继续作业",
                correct_decision="立即断电撤人",
                basis_clause="《安全生产法》第四十一条",
                agent_id="test_agent",
            )

            assert result["commit_id"] is not None
            assert any("类似事故处理案例.md" in f for f in result["files_updated"])
            assert any("预警历史经验与短期记忆摘要.md" in f for f in result["files_updated"])
            assert result["quadruple"]["问题场景"] == "瓦斯超限未撤人"

            # 验证文件已写入
            case_content = kb.read("类似事故处理案例.md")
            assert "瓦斯超限未撤人" in case_content
            assert "立即断电撤人" in case_content

            history_content = kb.read("预警历史经验与短期记忆摘要.md")
            assert "瓦斯超限未撤人" in history_content
        finally:
            # Windows 下 Git 句柄可能导致清理失败，忽略
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
