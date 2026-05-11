"""
决策智能体 Workflow 测试
覆盖：正常通过流、MARCH拦截回环、蒙特卡洛阻断、场景切换
"""

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.workflow import (
    AgentState,
    DecisionWorkflow,
    ScenarioConfig,
    node_data_ingestion,
    node_decision_generation,
    node_memory_recall,
    node_result_push,
    node_risk_assessment,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_prediction():
    """模拟预测结果"""
    return {
        "predicted_level": "红",
        "probability_distribution": {"红": 0.85, "橙": 0.12, "黄": 0.02, "蓝": 0.01},
        "shap_contributions": [
            {"feature": "瓦斯浓度", "contribution": 0.45},
            {"feature": "通风系统状态", "contribution": 0.30},
            {"feature": "温度异常", "contribution": 0.15},
        ],
    }


@pytest.fixture
def mock_raw_data():
    """模拟原始输入数据"""
    return {
        "企业ID": "E001",
        "瓦斯浓度": 1.2,
        "通风系统状态": 0,
        "温度异常": 1,
    }


@pytest.fixture
def base_state(mock_raw_data, mock_prediction):
    """基础 AgentState"""
    return {
        "enterprise_id": "E001",
        "raw_data": mock_raw_data,
        "features": None,
        "prediction": mock_prediction,
        "memory_results": None,
        "decision": None,
        "march_result": None,
        "monte_carlo_result": None,
        "three_d_risk": None,
        "retry_count": 0,
        "final_status": "UNKNOWN",
        "node_status": [],
        "scenario_id": "chemical",
        "error": None,
    }


# =============================================================================
# 测试：memory_recall RAG 开关
# =============================================================================

@pytest.mark.asyncio
class TestMemoryRecallNode:
    """测试 memory_recall 对长期记忆 RAG 开关的处理。"""

    @patch("agent.workflow._get_memory")
    async def test_memory_recall_enabled_calls_rag(self, mock_get_memory, base_state):
        mock_memory = MagicMock()
        mock_memory.is_long_term_rag_enabled.return_value = True
        mock_memory.recall_long_term = AsyncMock(return_value=[
            {"text": "粉尘涉爆除尘系统异常处置证据", "metadata": {"source_file": "knowledge_base/test.md"}}
        ])
        mock_get_memory.return_value = mock_memory

        state = base_state.copy()
        state["node_status"] = []
        result = await node_memory_recall(state)

        assert result["memory_results"]
        mock_memory.recall_long_term.assert_awaited_once()
        status = result["node_status"][-1]
        assert status["node"] == "memory_recall"
        assert status["status"] == "completed"
        assert "召回 1 条记忆" in status["detail"]

    @patch("agent.workflow._get_memory")
    async def test_memory_recall_disabled_skips_safely(self, mock_get_memory, base_state):
        mock_memory = MagicMock()
        mock_memory.is_long_term_rag_enabled.return_value = False
        mock_memory.recall_long_term = AsyncMock(return_value=[])
        mock_get_memory.return_value = mock_memory

        state = base_state.copy()
        state["node_status"] = []
        result = await node_memory_recall(state)

        assert result["memory_results"] == []
        mock_memory.recall_long_term.assert_not_called()
        status = result["node_status"][-1]
        assert status["node"] == "memory_recall"
        assert status["status"] == "skipped"


# =============================================================================
# 测试：正常通过流
# =============================================================================

@pytest.mark.asyncio
class TestNormalFlow:
    """测试正常通过流"""

    @patch("agent.workflow._load_pipeline")
    @patch("agent.workflow._load_model")
    @patch("agent.workflow._get_memory")
    @patch("agent.workflow.OpenAICompatibleClient")
    @patch("agent.workflow.SamplingNode")
    @patch("agent.workflow.RiskAssessor")
    async def test_full_workflow_approve(
        self,
        mock_risk_assessor_cls,
        mock_sampling_node_cls,
        mock_llm_client,
        mock_get_memory,
        mock_load_model,
        mock_load_pipeline,
        mock_raw_data,
    ):
        """完整工作流：所有校验通过，最终状态为 APPROVE"""
        # Mock Pipeline
        mock_pipeline = MagicMock()
        mock_pipeline.transform.return_value = [[1.0, 2.0, 3.0]]
        mock_load_pipeline.return_value = mock_pipeline

        # Mock Model
        mock_model = MagicMock()
        mock_model.predict.return_value = {
            "predicted_level": "红",
            "probability_distribution": {"红": 0.85, "橙": 0.12, "黄": 0.02, "蓝": 0.01},
            "shap_contributions": [
                {"feature": "瓦斯浓度", "contribution": 0.45},
            ],
        }
        mock_load_model.return_value = mock_model

        # Mock Memory
        mock_memory = MagicMock()
        mock_memory.recall_long_term = AsyncMock(return_value=[
            {"text": "某煤矿瓦斯超限事故案例", "source": "类似事故处理案例", "score": 0.92}
        ])
        mock_get_memory.return_value = mock_memory

        # Mock LLM
        mock_client = MagicMock()
        mock_client.generate_json = AsyncMock(return_value={
            "risk_level_and_attribution": {
                "level": "红",
                "top_features": [{"feature": "瓦斯浓度", "contribution": 0.45}],
                "root_cause": "瓦斯浓度超限且通风系统异常",
            },
            "government_intervention": {
                "department_primary": {
                    "name": "属地应急管理局-危化品安全监督管理科",
                    "contact_role": "科长",
                    "action": "立即签发整改通知书",
                },
                "department_assist": {"name": "执法大队", "action": "协同执法"},
                "actions": ["24小时内组织联合执法"],
                "deadline_hours": 24,
                "follow_up": "3个工作日内复查",
            },
            "enterprise_control": {
                "equipment_id": "2号反应釜",
                "operation": "紧急停车",
                "parameters": {
                    "dcs_tag": "FIC-201",
                    "target_values": "进料=0",
                    "monitoring_interval_minutes": 30,
                },
                "emergency_resources": ["消防站全员在岗"],
                "personnel_actions": ["撤离非必要人员"],
            },
        })
        mock_llm_client.return_value = mock_client

        # Mock SamplingNode（蒙特卡洛通过）
        mock_mc_result = MagicMock()
        mock_mc_result.passed = True
        mock_mc_result.confidence = 0.95
        mock_mc_result.model_dump.return_value = {
            "passed": True, "confidence": 0.95, "threshold": 0.90
        }
        mock_sampling_node = MagicMock()
        mock_sampling_node.sample.return_value = mock_mc_result
        mock_sampling_node_cls.return_value = mock_sampling_node

        # Mock RiskAssessor（三维风险通过）
        mock_risk_result = MagicMock()
        mock_risk_result.blocked = False
        mock_risk_result.total_score = 1.8
        mock_risk_result.model_dump.return_value = {
            "blocked": False, "total_score": 1.8, "threshold": 2.2
        }
        mock_risk_assessor = MagicMock()
        mock_risk_assessor.assess.return_value = mock_risk_result
        mock_risk_assessor_cls.return_value = mock_risk_assessor

        # 执行工作流
        workflow = DecisionWorkflow(scenario_id="chemical")
        result = await workflow.run_async(enterprise_id="E001", raw_data=mock_raw_data)

        # 验证节点状态流包含 key 节点
        node_names = [ns["node"] for ns in result["node_status"]]
        assert "data_ingestion" in node_names
        assert "risk_assessment" in node_names
        assert "memory_recall" in node_names
        assert "decision_generation" in node_names
        assert "result_push" in node_names

        # 验证最终状态
        assert result["final_status"] == "APPROVE"
        assert result["march_result"]["passed"] is True
        assert result["monte_carlo_result"]["passed"] is True
        assert result["three_d_risk"]["blocked"] is False

        # 验证决策 JSON 结构完整
        decision = result["decision"]
        assert "risk_level_and_attribution" in decision
        assert "government_intervention" in decision
        assert "enterprise_control" in decision

        gov = decision["government_intervention"]
        assert "department_primary" in gov
        assert "actions" in gov
        assert "deadline_hours" in gov

        ent = decision["enterprise_control"]
        assert "equipment_id" in ent
        assert "operation" in ent
        assert "parameters" in ent


# =============================================================================
# 测试：MARCH 拦截回环
# =============================================================================

@pytest.mark.asyncio
class TestMarchRetryLoop:
    """测试 MARCH 校验失败后的回环重试"""

    @patch("agent.workflow._load_pipeline")
    @patch("agent.workflow._load_model")
    @patch("agent.workflow._get_memory")
    @patch("agent.workflow.OpenAICompatibleClient")
    @patch("agent.workflow.run_march_validation")
    @patch("agent.workflow.SamplingNode")
    @patch("agent.workflow.RiskAssessor")
    async def test_march_retry_then_pass(
        self,
        mock_risk_assessor_cls,
        mock_sampling_node_cls,
        mock_run_march,
        mock_llm_client,
        mock_get_memory,
        mock_load_model,
        mock_load_pipeline,
        mock_raw_data,
    ):
        """MARCH 第一次失败，第二次通过，验证 retry_count > 0"""
        mock_pipeline = MagicMock()
        mock_pipeline.transform.return_value = [[1.0]]
        mock_load_pipeline.return_value = mock_pipeline

        mock_model = MagicMock()
        mock_model.predict.return_value = {
            "predicted_level": "红",
            "probability_distribution": {"红": 0.9},
            "shap_contributions": [{"feature": "瓦斯浓度", "contribution": 0.5}],
        }
        mock_load_model.return_value = mock_model

        mock_memory = MagicMock()
        mock_memory.recall_long_term = AsyncMock(return_value=[])
        mock_get_memory.return_value = mock_memory

        # LLM 返回两次不同结果
        mock_client = MagicMock()
        mock_client.generate_json = AsyncMock(side_effect=[
            {"government_intervention": {"actions": ["建议销毁监控记录"]}, "enterprise_control": {}},
            {"government_intervention": {"actions": ["立即整改"]}, "enterprise_control": {}},
        ])
        mock_llm_client.return_value = mock_client

        # MARCH：第一次失败，第二次通过
        vr_fail = MagicMock()
        vr_fail.pass_ = False
        vr_fail.reason = "触发合规红线：严禁销毁监控记录"
        vr_pass = MagicMock()
        vr_pass.pass_ = True
        vr_pass.reason = "MARCH 三重校验全部通过"

        mock_run_march.side_effect = [
            {"validation_result": vr_fail},
            {"validation_result": vr_pass},
        ]

        # 蒙特卡洛通过
        mock_mc_result = MagicMock()
        mock_mc_result.passed = True
        mock_mc_result.confidence = 0.95
        mock_mc_result.model_dump.return_value = {"passed": True, "confidence": 0.95}
        mock_sampling_node_cls.return_value = MagicMock(sample=MagicMock(return_value=mock_mc_result))

        # 三维风险通过
        mock_risk_result = MagicMock()
        mock_risk_result.blocked = False
        mock_risk_result.total_score = 1.5
        mock_risk_result.model_dump.return_value = {"blocked": False, "total_score": 1.5}
        mock_risk_assessor_cls.return_value = MagicMock(assess=MagicMock(return_value=mock_risk_result))

        workflow = DecisionWorkflow(scenario_id="chemical")
        result = await workflow.run_async(enterprise_id="E001", raw_data=mock_raw_data)

        assert result["retry_count"] == 1
        assert result["march_result"]["passed"] is True
        assert result["final_status"] == "APPROVE"

    @patch("agent.workflow._load_pipeline")
    @patch("agent.workflow._load_model")
    @patch("agent.workflow._get_memory")
    @patch("agent.workflow.OpenAICompatibleClient")
    @patch("agent.workflow.run_march_validation")
    async def test_march_final_reject(
        self,
        mock_run_march,
        mock_llm_client,
        mock_get_memory,
        mock_load_model,
        mock_load_pipeline,
        mock_raw_data,
    ):
        """MARCH 连续 3 次失败，最终 REJECT"""
        mock_pipeline = MagicMock()
        mock_pipeline.transform.return_value = [[1.0]]
        mock_load_pipeline.return_value = mock_pipeline

        mock_model = MagicMock()
        mock_model.predict.return_value = {
            "predicted_level": "红",
            "probability_distribution": {"红": 0.9},
            "shap_contributions": [{"feature": "瓦斯浓度", "contribution": 0.5}],
        }
        mock_load_model.return_value = mock_model

        mock_memory = MagicMock()
        mock_memory.recall_long_term = AsyncMock(return_value=[])
        mock_get_memory.return_value = mock_memory

        mock_client = MagicMock()
        mock_client.generate_json = AsyncMock(return_value={
            "government_intervention": {"actions": ["建议销毁监控记录"]},
            "enterprise_control": {},
        })
        mock_llm_client.return_value = mock_client

        vr_fail = MagicMock()
        vr_fail.pass_ = False
        vr_fail.reason = "触发合规红线"
        mock_run_march.return_value = {"validation_result": vr_fail}

        workflow = DecisionWorkflow(scenario_id="chemical")
        result = await workflow.run_async(enterprise_id="E001", raw_data=mock_raw_data)

        assert result["retry_count"] == 3
        assert result["march_result"]["passed"] is False
        assert result["final_status"] == "REJECT"


# =============================================================================
# 测试：蒙特卡洛阻断
# =============================================================================

@pytest.mark.asyncio
class TestMonteCarloBlock:
    """测试蒙特卡洛置信度不足导致人工审核"""

    @patch("agent.workflow._load_pipeline")
    @patch("agent.workflow._load_model")
    @patch("agent.workflow._get_memory")
    @patch("agent.workflow.OpenAICompatibleClient")
    @patch("agent.workflow.SamplingNode")
    @patch("agent.workflow.RiskAssessor")
    async def test_monte_carlo_human_review(
        self,
        mock_risk_assessor_cls,
        mock_sampling_node_cls,
        mock_llm_client,
        mock_get_memory,
        mock_load_model,
        mock_load_pipeline,
        mock_raw_data,
    ):
        """MARCH 通过，但蒙特卡洛置信度 < 0.90，最终 HUMAN_REVIEW"""
        mock_pipeline = MagicMock()
        mock_pipeline.transform.return_value = [[1.0]]
        mock_load_pipeline.return_value = mock_pipeline

        mock_model = MagicMock()
        mock_model.predict.return_value = {
            "predicted_level": "红",
            "probability_distribution": {"红": 0.9},
            "shap_contributions": [{"feature": "瓦斯浓度", "contribution": 0.5}],
        }
        mock_load_model.return_value = mock_model

        mock_memory = MagicMock()
        mock_memory.recall_long_term = AsyncMock(return_value=[])
        mock_get_memory.return_value = mock_memory

        mock_client = MagicMock()
        mock_client.generate_json = AsyncMock(return_value={
            "government_intervention": {"actions": ["立即整改"]}, "enterprise_control": {}},
        )
        mock_llm_client.return_value = mock_client

        # 蒙特卡洛失败
        mock_mc_result = MagicMock()
        mock_mc_result.passed = False
        mock_mc_result.confidence = 0.75
        mock_mc_result.model_dump.return_value = {
            "passed": False, "confidence": 0.75, "threshold": 0.90
        }
        mock_sampling_node_cls.return_value = MagicMock(sample=MagicMock(return_value=mock_mc_result))

        # 三维风险通过（不被执行，因为蒙特卡洛已失败）
        mock_risk_result = MagicMock()
        mock_risk_result.blocked = False
        mock_risk_result.model_dump.return_value = {"blocked": False}
        mock_risk_assessor_cls.return_value = MagicMock(assess=MagicMock(return_value=mock_risk_result))

        workflow = DecisionWorkflow(scenario_id="chemical")
        result = await workflow.run_async(enterprise_id="E001", raw_data=mock_raw_data)

        assert result["march_result"]["passed"] is True
        assert result["monte_carlo_result"]["passed"] is False
        assert result["final_status"] == "HUMAN_REVIEW"


# =============================================================================
# 测试：场景切换
# =============================================================================

class TestScenarioSwitch:
    """测试场景化配置切换"""

    def test_scenario_config_initial(self):
        """验证默认场景配置"""
        cfg = ScenarioConfig(scenario_id="chemical")
        assert cfg.scenario_id == "chemical"
        assert cfg.checker_strictness == "strict"
        assert cfg.confidence_threshold == 0.90
        assert cfg.risk_threshold == 2.2
        assert "chemical" in cfg.knowledge_base_subdir

    def test_scenario_switch_metallurgy(self):
        """切换到冶金场景，验证阈值变化"""
        cfg = ScenarioConfig(scenario_id="chemical")
        cfg.set_scenario("metallurgy")
        assert cfg.scenario_id == "metallurgy"
        assert cfg.checker_strictness == "standard"
        assert cfg.confidence_threshold == 0.85
        assert cfg.risk_threshold == 2.5
        assert "metallurgy" in cfg.knowledge_base_subdir
        assert "metallurgy" in cfg.prompt_template_path

    def test_scenario_switch_dust(self):
        """切换到粉尘场景，验证阈值变化"""
        cfg = ScenarioConfig(scenario_id="chemical")
        cfg.set_scenario("dust")
        assert cfg.scenario_id == "dust"
        assert cfg.checker_strictness == "standard"
        assert cfg.confidence_threshold == 0.85
        assert cfg.risk_threshold == 2.5
        assert "dust" in cfg.knowledge_base_subdir
        assert "dust" in cfg.prompt_template_path

    def test_scenario_kb_file_exists(self):
        """验证场景切换后知识库子集文件存在"""
        base_dir = Path(__file__).resolve().parent.parent
        for sid in ["chemical", "metallurgy", "dust"]:
            cfg = ScenarioConfig(scenario_id=sid)
            kb_subdir = base_dir / cfg.cfg["kb_subdir"]
            physics_file = kb_subdir / "工业物理常识及传感器时间序列逻辑.md"
            assert physics_file.exists(), f"{sid} 场景知识库文件不存在"

    def test_workflow_set_scenario(self):
        """验证 DecisionWorkflow 场景切换后图重建"""
        wf = DecisionWorkflow(scenario_id="chemical")
        assert wf.scenario.scenario_id == "chemical"
        wf.set_scenario("dust")
        assert wf.scenario.scenario_id == "dust"


# =============================================================================
# 测试：节点状态 SSE 格式
# =============================================================================

class TestNodeStatus:
    """测试节点状态记录格式"""

    def test_node_status_format(self, base_state):
        state = base_state.copy()
        state["node_status"] = []
        from agent.workflow import _push_node_status
        _push_node_status(state, "risk_assessment", "completed", "预测等级: 红")
        
        assert len(state["node_status"]) == 1
        status = state["node_status"][0]
        assert status["node"] == "risk_assessment"
        assert status["status"] == "completed"
        assert "timestamp" in status
        assert status["detail"] == "预测等级: 红"


# =============================================================================
# 测试：Prompt 模板渲染
# =============================================================================

class TestPromptTemplate:
    """测试 Prompt 模板渲染"""

    def test_chemical_prompt_exists(self):
        base_dir = Path(__file__).resolve().parent.parent
        path = base_dir / "prompts" / "decision_v1_chemical.txt"
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "government_intervention" in content
        assert "enterprise_control" in content
        assert "DCS" in content

    def test_metallurgy_prompt_exists(self):
        base_dir = Path(__file__).resolve().parent.parent
        path = base_dir / "prompts" / "decision_v1_metallurgy.txt"
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "炉体" in content
        assert "熔融金属" in content

    def test_dust_prompt_exists(self):
        base_dir = Path(__file__).resolve().parent.parent
        path = base_dir / "prompts" / "decision_v1_dust.txt"
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "粉尘" in content
        assert "泄爆口" in content
