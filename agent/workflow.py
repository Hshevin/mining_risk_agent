"""
GLM-5 决策智能体 LangGraph 工作流
5 节点 DAG：data_ingestion → risk_assessment → memory_recall → decision_generation → result_push
场景化配置驱动，支持 chemical / metallurgy / dust 三场景切换
"""

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import joblib
import pandas as pd
from jinja2 import Template
from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

from data.field_normalizer import normalize_enterprise_record
from data.preprocessor import FeatureEngineeringPipeline
from harness.knowledge_base import KnowledgeBaseManager
from harness.memory import HybridMemoryManager
from harness.monte_carlo import SamplingNode
from harness.proposer import Proposer
from harness.risk_assessment import RiskAssessor
from harness.validation import run_march_validation
from llm.glm5_client import OpenAICompatibleClient
from model.stacking import StackingRiskModel
from utils.config import get_config
from utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# AgentState：工作流全局状态
# =============================================================================

class AgentState(TypedDict):
    enterprise_id: str
    raw_data: Dict[str, Any]
    features: Optional[Any]
    prediction: Optional[Dict[str, Any]]
    memory_results: Optional[List[Dict[str, Any]]]
    decision: Optional[Dict[str, Any]]
    march_result: Optional[Dict[str, Any]]
    monte_carlo_result: Optional[Dict[str, Any]]
    three_d_risk: Optional[Dict[str, Any]]
    retry_count: int
    final_status: str
    node_status: List[Dict[str, Any]]
    scenario_id: str
    error: Optional[str]


# =============================================================================
# 场景化配置管理
# =============================================================================

class ScenarioConfig:
    """场景化配置管理器

    优先从 config.yaml 的 scenarios 节读取配置，若不存在则使用硬编码默认值。
    """

    DEFAULT_SCENARIOS = {
        "chemical": {
            "name": "危险化学品",
            "kb_subdir": "knowledge_base/chemical",
            "prompt_template": "prompts/decision_v1_chemical.txt",
            "checker_strictness": "strict",
            "confidence_threshold": 0.90,
            "risk_threshold": 2.2,
            "memory_top_k": 5,
        },
        "metallurgy": {
            "name": "冶金",
            "kb_subdir": "knowledge_base/metallurgy",
            "prompt_template": "prompts/decision_v1_metallurgy.txt",
            "checker_strictness": "standard",
            "confidence_threshold": 0.85,
            "risk_threshold": 2.5,
            "memory_top_k": 5,
        },
        "dust": {
            "name": "粉尘涉爆",
            "kb_subdir": "knowledge_base/dust",
            "prompt_template": "prompts/decision_v1_dust.txt",
            "checker_strictness": "standard",
            "confidence_threshold": 0.85,
            "risk_threshold": 2.5,
            "memory_top_k": 5,
        },
    }

    @classmethod
    def _load_scenarios(cls) -> Dict[str, Dict[str, Any]]:
        """从 config.yaml 加载 scenarios 配置，若不存在则返回默认值"""
        try:
            config = get_config()
            scenarios: Dict[str, Any] = {}
            for sid, raw in config.scenarios.model_dump().items():
                scenarios[sid] = {
                    "name": raw.get("name", cls.DEFAULT_SCENARIOS.get(sid, {}).get("name", sid)),
                    "kb_subdir": raw.get("kb_subdir", cls.DEFAULT_SCENARIOS.get(sid, {}).get("kb_subdir", f"knowledge_base/{sid}")),
                    "prompt_template": raw.get("prompt_template", cls.DEFAULT_SCENARIOS.get(sid, {}).get("prompt_template", f"prompts/decision_v1_{sid}.txt")),
                    "checker_strictness": raw.get("checker_strictness", "standard"),
                    "confidence_threshold": raw.get("confidence_threshold", 0.85),
                    "risk_threshold": raw.get("risk_threshold", 2.5),
                    "memory_top_k": raw.get("memory_top_k", 5),
                }
            return scenarios if scenarios else cls.DEFAULT_SCENARIOS
        except Exception as e:
            logger.warning(f"从 config.yaml 加载 scenarios 失败: {e}，使用默认值")
        return cls.DEFAULT_SCENARIOS

    def __init__(self, scenario_id: str = "chemical"):
        self._scenarios = self._load_scenarios()
        self.scenario_id = scenario_id
        self.cfg = self._scenarios.get(scenario_id, self._scenarios["chemical"])

    def set_scenario(self, scenario_id: str) -> None:
        if scenario_id not in self._scenarios:
            raise ValueError(f"未知场景: {scenario_id}, 可选: {list(self._scenarios.keys())}")
        self.scenario_id = scenario_id
        self.cfg = self._scenarios[scenario_id]
        logger.info(f"场景已切换至: {scenario_id} ({self.cfg['name']})")

    @property
    def prompt_template_path(self) -> str:
        base_dir = Path(__file__).resolve().parent.parent
        return str(base_dir / self.cfg["prompt_template"])

    @property
    def knowledge_base_subdir(self) -> str:
        base_dir = Path(__file__).resolve().parent.parent
        return str(base_dir / self.cfg["kb_subdir"])

    @property
    def checker_strictness(self) -> str:
        return self.cfg["checker_strictness"]

    @property
    def confidence_threshold(self) -> float:
        return self.cfg["confidence_threshold"]

    @property
    def risk_threshold(self) -> float:
        return self.cfg["risk_threshold"]

    @property
    def memory_top_k(self) -> int:
        return self.cfg["memory_top_k"]


# =============================================================================
# 辅助函数
# =============================================================================

def _push_node_status(state: AgentState, node: str, status: str, detail: str = "") -> None:
    """记录节点状态，供 SSE 流式输出使用"""
    state["node_status"].append({
        "node": node,
        "status": status,
        "timestamp": time.time(),
        "detail": detail,
    })


def _get_project_base() -> Path:
    return Path(__file__).resolve().parent.parent


_model: Optional[StackingRiskModel] = None
_pipeline: Optional[FeatureEngineeringPipeline] = None
_memory: Optional[HybridMemoryManager] = None


def _load_model() -> StackingRiskModel:
    global _model
    if _model is None:
        config = get_config()
        model_path = config.model.stacking.model_path
        _model = StackingRiskModel()
        if os.path.exists(model_path):
            _model.load(model_path)
        else:
            logger.warning("模型文件不存在，返回未训练实例")
    return _model


def _load_pipeline() -> FeatureEngineeringPipeline:
    global _pipeline
    if _pipeline is None:
        config = get_config()
        pipeline_path = config.model.stacking.pipeline_path
        _pipeline = FeatureEngineeringPipeline()
        if os.path.exists(pipeline_path):
            _pipeline.load(pipeline_path)
        else:
            logger.warning("Pipeline 文件不存在，返回未训练实例")
    return _pipeline


def _get_memory() -> HybridMemoryManager:
    global _memory
    if _memory is None:
        _memory = HybridMemoryManager()
    return _memory


def _load_physics_context(scenario: ScenarioConfig) -> str:
    """加载物理常识上下文，优先从场景化知识库子集读取"""
    kb_dir = scenario.knowledge_base_subdir
    physics_file = os.path.join(kb_dir, "工业物理常识及传感器时间序列逻辑.md")

    # 若场景子集不存在，回退到主知识库
    if not os.path.exists(physics_file):
        base_dir = _get_project_base()
        physics_file = str(base_dir / "knowledge_base" / "工业物理常识及传感器时间序列逻辑.md")

    if os.path.exists(physics_file):
        with open(physics_file, "r", encoding="utf-8") as f:
            return f.read()[:2000]  # 截取前 2000 字符
    return "（物理常识知识库暂不可用）"


# =============================================================================
# 节点函数（async，兼容 LangGraph ainvoke）
# =============================================================================

async def node_data_ingestion(state: AgentState) -> AgentState:
    """数据接入节点：构造 DataFrame，特征工程"""
    _push_node_status(state, "data_ingestion", "started")
    try:
        pipeline = _load_pipeline()
        normalized, report = normalize_enterprise_record(
            state["raw_data"],
            enterprise_id=state["enterprise_id"],
            scenario_id=state.get("scenario_id"),
        )
        logger.info(
            "Workflow 输入字段标准化完成: mapped=%s defaulted_count=%s",
            report.mapped_fields,
            len(report.defaulted_fields),
        )
        state["raw_data"] = normalized
        df = pd.DataFrame([normalized])
        X = pipeline.transform(df)
        state["features"] = X
        _push_node_status(state, "data_ingestion", "completed", "特征工程完成")
    except Exception as e:
        logger.error(f"数据接入失败: {e}")
        state["error"] = str(e)
        _push_node_status(state, "data_ingestion", "failed", str(e))
    return state


async def node_risk_assessment(state: AgentState) -> AgentState:
    """风险评估节点：Stacking 模型预测"""
    _push_node_status(state, "risk_assessment", "started")
    try:
        if state.get("error") or state.get("features") is None:
            detail = state.get("error") or "缺少特征矩阵，跳过模型推理"
            _push_node_status(state, "risk_assessment", "skipped", detail)
            return state
        model = _load_model()
        X = state["features"]
        result = model.predict(X)
        if isinstance(result, list):
            result = result[0]
        state["prediction"] = result
        _push_node_status(
            state, "risk_assessment", "completed",
            f"预测等级: {result.get('predicted_level', 'unknown')}"
        )
    except Exception as e:
        logger.error(f"风险评估失败: {e}")
        state["error"] = str(e)
        _push_node_status(state, "risk_assessment", "failed", str(e))
    return state


async def node_memory_recall(state: AgentState) -> AgentState:
    """记忆召回节点：基于 Top3 特征生成 query，调用 memory.recall()（含 SelfQuery 过滤）"""
    _push_node_status(state, "memory_recall", "started")
    try:
        prediction = state.get("prediction")
        if not prediction:
            state["memory_results"] = []
            _push_node_status(state, "memory_recall", "completed", "无预测结果，跳过召回")
            return state

        shap = prediction.get("shap_contributions", [])
        top_features = [s.get("feature", "") for s in shap[:3]]
        query = "、".join(top_features) if top_features else "风险预警处置"

        memory = _get_memory()
        if not memory.is_long_term_rag_enabled():
            state["memory_results"] = []
            logger.info("长期记忆 RAG 已关闭，memory_recall 跳过向量召回")
            _push_node_status(state, "memory_recall", "skipped", "长期记忆 RAG 已关闭，跳过向量召回")
            return state

        risk_level = prediction.get("predicted_level", "")
        results = await memory.recall_long_term(query, risk_level=risk_level, top_k=5)

        state["memory_results"] = results
        _push_node_status(
            state, "memory_recall", "completed",
            f"召回 {len(results)} 条记忆"
        )
    except ImportError as e:
        logger.warning(f"记忆召回跳过: {e}")
        state["memory_results"] = []
        _push_node_status(state, "memory_recall", "skipped", str(e))
    except Exception as e:
        logger.error(f"记忆召回失败: {e}")
        state["memory_results"] = []
        _push_node_status(state, "memory_recall", "failed", str(e))
    return state


async def node_decision_generation(state: AgentState, scenario: ScenarioConfig) -> AgentState:
    """
    决策生成节点：
    1. 加载 Prompt 模板，注入变量
    2. 调用 GLM-5 生成 JSON
    3. MARCH 校验，不通过回环重试最多 3 次
    4. 蒙特卡洛采样
    5. 三维风险评估
    """
    _push_node_status(state, "decision_generation", "started")
    try:
        prediction = state.get("prediction")
        if not prediction:
            state["error"] = "缺少预测结果，无法生成决策"
            _push_node_status(state, "decision_generation", "failed", state["error"])
            return state

        # 读取 Prompt 模板
        template_path = scenario.prompt_template_path
        if not os.path.exists(template_path):
            template_path = str(_get_project_base() / "prompts/decision_v1_chemical.txt")
        with open(template_path, "r", encoding="utf-8") as f:
            template = Template(f.read())

        # 构造记忆上下文
        memory_results = state.get("memory_results", [])
        memory_context = "\n".join(
            f"- [{r.get('source', '未知')}] {r.get('content', r.get('text', ''))[:300]}"
            for r in memory_results
        ) if memory_results else "暂无相关历史案例"

        physics_context = _load_physics_context(scenario)

        prompt = template.render(
            enterprise_id=state["enterprise_id"],
            predicted_level=prediction.get("predicted_level", ""),
            probability_distribution=json.dumps(
                prediction.get("probability_distribution", {}), ensure_ascii=False
            ),
            shap_contributions=json.dumps(
                prediction.get("shap_contributions", []), ensure_ascii=False
            ),
            memory_context=memory_context,
            physics_context=physics_context,
        )

        config = get_config()
<<<<<<< HEAD
        llm_cfg = config.llm.active
        client = OpenAICompatibleClient(
            api_key=llm_cfg.api_key or None,
            base_url=llm_cfg.base_url or None,
            model=llm_cfg.model or None,
            provider_name=config.llm.provider,
            api_key_env=llm_cfg.api_key_env or None,
            max_retries=llm_cfg.max_retries,
            default_max_tokens=llm_cfg.default_max_tokens,
        )
        decision = await client.generate_json(
            prompt,
            temperature=llm_cfg.default_temperature,
            max_tokens=llm_cfg.default_max_tokens,
        )
=======
        llm_cfg = config.llm.glm5
        client = GLM5Client(
            api_key=llm_cfg.api_key or None,
            base_url=llm_cfg.base_url or None,
            model=llm_cfg.model or None,
        )
        decision = await client.generate_json(prompt, temperature=llm_cfg.default_temperature)
>>>>>>> e7cc200 (some changes)
        state["decision"] = decision

        # ------------------------------------------------------------------
        # MARCH 校验回环（最多 3 次）
        # ------------------------------------------------------------------
        retry_count = state.get("retry_count", 0)
        march_passed = False
        march_reason = ""

        while retry_count < 3:
            compat_decision = {
                "predicted_level": prediction.get("predicted_level", ""),
                "probability_distribution": prediction.get("probability_distribution", {}),
                "shap_contributions": prediction.get("shap_contributions", []),
                "government_advice": json.dumps(
                    decision.get("government_intervention", {}), ensure_ascii=False
                ),
                "enterprise_advice": json.dumps(
                    decision.get("enterprise_control", {}), ensure_ascii=False
                ),
            }
            propositions = Proposer.decompose(compat_decision)
            march_state = {"atomic_propositions": propositions}
            march_result = run_march_validation(march_state)
            vr = march_result["validation_result"]
            march_passed = vr.pass_ if hasattr(vr, "pass_") else vr.get("pass_", False)
            march_reason = vr.reason if hasattr(vr, "reason") else vr.get("reason", "")

            if march_passed:
                break

            retry_count += 1
            logger.warning(f"MARCH 校验未通过，第 {retry_count} 次重试: {march_reason}")

            correction_prompt = (
                f"{prompt}\n\n"
                f"【修正反馈】上一轮决策未通过安全校验，原因如下：\n"
                f"{march_reason}\n\n"
                f"请根据上述反馈修正决策方案，确保符合安全规范，重新输出 JSON。"
            )
            decision = await client.generate_json(
                correction_prompt,
                temperature=llm_cfg.default_temperature,
                max_tokens=llm_cfg.default_max_tokens,
            )
            state["decision"] = decision

        state["retry_count"] = retry_count
        state["march_result"] = {
            "passed": march_passed,
            "reason": march_reason,
            "retry_count": retry_count,
        }

        if not march_passed:
            state["final_status"] = "REJECT"
            _push_node_status(
                state, "decision_generation", "completed",
                f"MARCH 校验最终未通过，重试 {retry_count} 次"
            )
            return state

        # ------------------------------------------------------------------
        # 蒙特卡洛采样
        # ------------------------------------------------------------------
        mc_threshold = scenario.confidence_threshold
        mc_node = SamplingNode(n_samples=20, confidence_threshold=mc_threshold)
        mc_result = mc_node.sample(compat_decision)
        state["monte_carlo_result"] = mc_result.model_dump()

        # ------------------------------------------------------------------
        # 三维风险评估
        # ------------------------------------------------------------------
        risk_threshold = scenario.risk_threshold
        assessor = RiskAssessor(threshold=risk_threshold)
        risk_result = assessor.assess(compat_decision)
        state["three_d_risk"] = risk_result.model_dump()

        # ------------------------------------------------------------------
        # 综合判定
        # ------------------------------------------------------------------
        if not mc_result.passed:
            state["final_status"] = "HUMAN_REVIEW"
            _push_node_status(
                state, "decision_generation", "completed",
                f"蒙特卡洛置信度 {mc_result.confidence} < 阈值 {mc_threshold}"
            )
        elif risk_result.blocked:
            state["final_status"] = "HUMAN_REVIEW"
            _push_node_status(
                state, "decision_generation", "completed",
                f"三维风险评分 {risk_result.total_score} >= 阈值 {risk_threshold}"
            )
        else:
            state["final_status"] = "APPROVE"
            _push_node_status(
                state, "decision_generation", "completed",
                "决策生成并通过全部校验"
            )

    except Exception as e:
        logger.error(f"决策生成失败: {e}")
        state["error"] = str(e)
        _push_node_status(state, "decision_generation", "failed", str(e))
    return state


async def node_result_push(state: AgentState) -> AgentState:
    """结果推送节点：封装最终输出"""
    _push_node_status(state, "result_push", "started")
    try:
        decision = state.get("decision") or {}
        final_status = state.get("final_status", "UNKNOWN")

        if "government_intervention" not in decision:
            decision["government_intervention"] = {
                "department_primary": {"name": "", "contact_role": "", "action": ""},
                "department_assist": {"name": "", "action": ""},
                "actions": [],
                "deadline_hours": 24,
                "follow_up": "",
            }
        if "enterprise_control" not in decision:
            decision["enterprise_control"] = {
                "equipment_id": "",
                "operation": "",
                "parameters": {},
                "emergency_resources": [],
                "personnel_actions": [],
            }

        state["decision"] = decision
        _push_node_status(
            state, "result_push", "completed",
            f"最终状态: {final_status}"
        )
    except Exception as e:
        logger.error(f"结果推送失败: {e}")
        state["error"] = str(e)
        _push_node_status(state, "result_push", "failed", str(e))
    return state


# =============================================================================
# DecisionWorkflow：工作流编排器
# =============================================================================

class DecisionWorkflow:
    """
    LangGraph 决策工作流编排器

    使用方式：
        wf = DecisionWorkflow(scenario_id="chemical")
        result = await wf.run_async(enterprise_id="E001", raw_data={...})
    """

    def __init__(self, scenario_id: str = "chemical"):
        self.scenario = ScenarioConfig(scenario_id)
        self.graph = self._build_graph()

    def set_scenario(self, scenario_id: str) -> None:
        """切换场景配置，重建工作流图"""
        self.scenario.set_scenario(scenario_id)
        self.graph = self._build_graph()

    def _build_graph(self) -> Any:
        """构建 LangGraph 状态图"""
        workflow = StateGraph(AgentState)

        # 由于 decision_generation 需要注入 scenario，使用闭包包装
        async def _decision_wrapper(state: AgentState) -> AgentState:
            return await node_decision_generation(state, self.scenario)

        def _route_after_data(state: AgentState) -> str:
            return "continue" if state.get("features") is not None and not state.get("error") else "end"

        def _route_after_risk(state: AgentState) -> str:
            return "continue" if state.get("prediction") is not None and not state.get("error") else "end"

        def _route_after_decision(state: AgentState) -> str:
            return "continue" if state.get("decision") is not None and not state.get("error") else "end"

        workflow.add_node("data_ingestion", node_data_ingestion)
        workflow.add_node("risk_assessment", node_risk_assessment)
        workflow.add_node("memory_recall", node_memory_recall)
        workflow.add_node("decision_generation", _decision_wrapper)
        workflow.add_node("result_push", node_result_push)

        workflow.set_entry_point("data_ingestion")
        workflow.add_conditional_edges(
            "data_ingestion",
            _route_after_data,
            {"continue": "risk_assessment", "end": END},
        )
        workflow.add_conditional_edges(
            "risk_assessment",
            _route_after_risk,
            {"continue": "memory_recall", "end": END},
        )
        workflow.add_edge("memory_recall", "decision_generation")
        workflow.add_conditional_edges(
            "decision_generation",
            _route_after_decision,
            {"continue": "result_push", "end": END},
        )
        workflow.add_edge("result_push", END)

        return workflow.compile()

    async def run_async(
        self,
        enterprise_id: str,
        raw_data: Dict[str, Any],
    ) -> AgentState:
        """
        异步运行完整决策工作流

        Args:
            enterprise_id: 企业ID
            raw_data: 原始输入数据字典

        Returns:
            最终 AgentState
        """
        initial_state: AgentState = {
            "enterprise_id": enterprise_id,
            "raw_data": raw_data,
            "features": None,
            "prediction": None,
            "memory_results": None,
            "decision": None,
            "march_result": None,
            "monte_carlo_result": None,
            "three_d_risk": None,
            "retry_count": 0,
            "final_status": "UNKNOWN",
            "node_status": [],
            "scenario_id": self.scenario.scenario_id,
            "error": None,
        }
        return await self.graph.ainvoke(initial_state)

    def run(
        self,
        enterprise_id: str,
        raw_data: Dict[str, Any],
    ) -> AgentState:
        """同步运行完整决策工作流（包装 async 入口）"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(
                        asyncio.run, self.run_async(enterprise_id, raw_data)
                    )
                    return future.result()
            return loop.run_until_complete(self.run_async(enterprise_id, raw_data))
        except RuntimeError:
            return asyncio.run(self.run_async(enterprise_id, raw_data))
