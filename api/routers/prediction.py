"""
风险预测路由 + GLM-5 决策智能体 Workflow 路由
保留原有 /api/v1/prediction/predict 不变
新增 Agent 路由由 agent_router 提供，挂载到 /api/v1/agent
"""

import json as _json
import os
from typing import Any, AsyncGenerator, Dict, List, Optional

import joblib
import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from data.field_normalizer import normalize_enterprise_record
from agent.workflow import DecisionWorkflow
from data.preprocessor import FeatureEngineeringPipeline
from harness.memory import HybridMemoryManager
from harness.validation import ValidationPipeline
from model.stacking import StackingRiskModel
from utils.config import LLMProviderConfig, get_config
from utils.logger import get_logger

logger = get_logger(__name__)

# =============================================================================
# Router 定义
# =============================================================================

# 原有预测路由，挂载到 /api/v1/prediction
router = APIRouter()

# 新增智能体决策路由，挂载到 /api/v1/agent
agent_router = APIRouter()

# 全局模型/Pipeline（懒加载）
_model: Optional[StackingRiskModel] = None
_pipeline: Optional[FeatureEngineeringPipeline] = None
_memory: Optional[HybridMemoryManager] = None
_validator: Optional[ValidationPipeline] = None
_workflow: Optional[DecisionWorkflow] = None


def _load_model() -> StackingRiskModel:
    global _model
    if _model is None:
        config = get_config()
        model_path = config.model.stacking.model_path
        if os.path.exists(model_path):
            _model = StackingRiskModel()
            _model.load(model_path)
        else:
            _model = StackingRiskModel()
            logger.warning("模型文件不存在，返回未训练实例")
    return _model


def _load_pipeline() -> FeatureEngineeringPipeline:
    global _pipeline
    if _pipeline is None:
        config = get_config()
        pipeline_path = config.model.stacking.pipeline_path
        if os.path.exists(pipeline_path):
            _pipeline = FeatureEngineeringPipeline()
            _pipeline.load(pipeline_path)
        else:
            _pipeline = FeatureEngineeringPipeline()
    return _pipeline


def _get_memory() -> HybridMemoryManager:
    global _memory
    if _memory is None:
        _memory = HybridMemoryManager()
    return _memory


def _get_validator() -> ValidationPipeline:
    global _validator
    if _validator is None:
        _validator = ValidationPipeline()
    return _validator


def _get_workflow() -> DecisionWorkflow:
    global _workflow
    if _workflow is None:
        _workflow = DecisionWorkflow(scenario_id="chemical")
    return _workflow


# =============================================================================
# 原有接口模型（保持不变）
# =============================================================================

class PredictRequest(BaseModel):
    enterprise_id: str
    data: Dict[str, Any]


class PredictResponse(BaseModel):
    enterprise_id: str
    predicted_level: str
    probability_distribution: Dict[str, float]
    shap_contributions: List[Dict[str, Any]]
    validation_result: Optional[Dict[str, Any]] = None
    suggestions: Optional[Dict[str, Any]] = None


class QueryRequest(BaseModel):
    enterprise_id: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    risk_level: Optional[str] = None


# =============================================================================
# 新增接口模型
# =============================================================================

class DecisionRequest(BaseModel):
    enterprise_id: str
    data: Dict[str, Any]


class DecisionResponse(BaseModel):
    enterprise_id: str
    scenario_id: str
    final_status: str
    predicted_level: str
    probability_distribution: Dict[str, float]
    shap_contributions: List[Dict[str, Any]]
    risk_level_and_attribution: Dict[str, Any]
    government_intervention: Dict[str, Any]
    enterprise_control: Dict[str, Any]
    march_result: Optional[Dict[str, Any]] = None
    monte_carlo_result: Optional[Dict[str, Any]] = None
    three_d_risk: Optional[Dict[str, Any]] = None
    node_status: List[Dict[str, Any]] = Field(default_factory=list)
    mock: bool = False


class ScenarioSwitchResponse(BaseModel):
    scenario_id: str
    scenario_name: str
    message: str
    confidence_threshold: float
    risk_threshold: float
    checker_strictness: str
    memory_top_k: int


class LLMConfigResponse(BaseModel):
    provider: str
    model: str
    base_url: str
    default_temperature: float
    default_max_tokens: int
    max_retries: int
    has_api_key: bool
    available_providers: List[str] = Field(default_factory=list)
    message: str = ""


class LLMUpdateRequest(BaseModel):
    provider: str
    model: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    api_key_env: Optional[str] = None
    default_temperature: Optional[float] = None
    default_max_tokens: Optional[int] = None
    max_retries: Optional[int] = None


# =============================================================================
# Mock 数据生成器（当 Workflow 不可用时降级返回）
# =============================================================================

def _generate_mock_decision(request: DecisionRequest) -> DecisionResponse:
    """生成严格对齐 README 示例格式的 Mock 决策响应，支持场景化差异"""
    # 优先从请求数据中推断场景，否则默认 chemical
    scenario_id = request.data.get("scenario_id", "chemical")
    if scenario_id not in ("chemical", "metallurgy", "dust"):
        scenario_id = "chemical"

    # 复用 frontend/demo_data.py 中的生成器，保持前后端一致
    try:
        from frontend.demo_data import generate_mock_decision as _gen_mock
        mock_dict = _gen_mock(scenario_id, request.enterprise_id)
    except Exception:
        mock_dict = _fallback_mock_decision(request.enterprise_id, scenario_id)

    return DecisionResponse(**mock_dict)


def _fallback_mock_decision(enterprise_id: str, scenario_id: str) -> Dict[str, Any]:
    """极端降级：frontend/demo_data.py 也不可用时的兜底"""
    return {
        "enterprise_id": enterprise_id,
        "scenario_id": scenario_id,
        "final_status": "APPROVE",
        "predicted_level": "红",
        "probability_distribution": {"红": 0.85, "橙": 0.12, "黄": 0.02, "蓝": 0.01},
        "shap_contributions": [
            {"feature": "瓦斯浓度", "contribution": 0.45},
            {"feature": "通风系统状态", "contribution": 0.28},
            {"feature": "专职安全生产管理人员数", "contribution": -0.12},
        ],
        "risk_level_and_attribution": {"level": "红", "root_cause": "关键风险指标异常"},
        "government_intervention": {
            "department_primary": {"name": "属地应急管理局", "contact_role": "科长", "action": "立即组织现场核查"},
            "actions": ["24小时内登门核查"],
            "deadline_hours": 24,
            "follow_up": "整改完成后复查",
        },
        "enterprise_control": {
            "equipment_id": "关键设备",
            "operation": "立即执行紧急停车",
            "parameters": {"target_values": "安全参数"},
            "emergency_resources": ["应急物资"],
            "personnel_actions": ["撤离非必要人员"],
        },
        "march_result": {"passed": True, "reason": "Mock fallback", "retry_count": 0},
        "monte_carlo_result": {"passed": True, "confidence": 0.95, "threshold": 0.90, "valid_count": 19, "total_samples": 20, "status": "APPROVE", "samples": []},
        "three_d_risk": {"severity": "极高", "relevance": "极高", "irreversibility": "极高", "total_score": 3.8, "risk_level": "EXTREME", "blocked": False, "reason": "Mock fallback"},
        "node_status": [
            {"node": "data_ingestion", "status": "completed", "timestamp": 0.0, "detail": "Mock fallback"},
            {"node": "risk_assessment", "status": "completed", "timestamp": 0.0, "detail": "Mock fallback"},
            {"node": "memory_recall", "status": "completed", "timestamp": 0.0, "detail": "Mock fallback"},
            {"node": "decision_generation", "status": "completed", "timestamp": 0.0, "detail": "Mock fallback"},
            {"node": "result_push", "status": "completed", "timestamp": 0.0, "detail": "Mock fallback"},
        ],
        "mock": True,
    }


# =============================================================================
# 原有接口（保持不变）
# =============================================================================

@router.post("/predict", response_model=PredictResponse)
async def predict(request: PredictRequest) -> PredictResponse:
    """风险预测接口（原有接口，保持不变）"""
    try:
        model = _load_model()
        pipeline = _load_pipeline()

        normalized, report = normalize_enterprise_record(
            request.data,
            enterprise_id=request.enterprise_id,
        )
        logger.info(
            "预测输入字段标准化完成: mapped=%s defaulted_count=%s",
            report.mapped_fields,
            len(report.defaulted_fields),
        )

        df = pd.DataFrame([normalized])
        
        X = pipeline.transform(df)
        
        result = model.predict(X)
        if isinstance(result, list):
            result = result[0]
        
        decision = {
            "predicted_level": result["predicted_level"],
            "probability_distribution": result["probability_distribution"],
            "shap_contributions": result["shap_contributions"],
            "government_advice": "",
            "enterprise_advice": "",
        }
        validator = _get_validator()
        validation = validator.run(decision)
        
        suggestions = _generate_suggestions(result, validation)
        
        return PredictResponse(
            enterprise_id=request.enterprise_id,
            predicted_level=result["predicted_level"],
            probability_distribution=result["probability_distribution"],
            shap_contributions=result["shap_contributions"],
            validation_result=validation,
            suggestions=suggestions,
        )
    except Exception as e:
        logger.error(f"预测失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query")
async def query_history(request: QueryRequest) -> List[Dict[str, Any]]:
    """预警历史查询"""
    return [
        {
            "enterprise_id": request.enterprise_id or "demo",
            "timestamp": "2024-01-01T00:00:00",
            "risk_level": request.risk_level or "一级",
            "status": "已闭环",
        }
    ]


def _generate_suggestions(result: Dict[str, Any], validation: Dict[str, Any]) -> Dict[str, Any]:
    """生成决策建议（原有辅助函数，保持不变）"""
    level = result["predicted_level"]
    
    gov_suggestions = {
        "一级": {
            "main_department": "属地应急管理局-危化品安全监督管理科",
            "assist_department": "应急管理综合行政执法大队",
            "action": "立即签发《重大事故隐患整改通知书》，24小时内组织联合执法小组登门核查",
        },
        "二级": {
            "main_department": "属地应急管理局",
            "assist_department": "行业主管部门",
            "action": "3日内组织专项检查，责令限期整改",
        },
        "三级": {
            "main_department": "区县级安监部门",
            "assist_department": "乡镇街道",
            "action": "7日内现场核查，跟踪整改闭环",
        },
        "四级": {
            "main_department": "企业安全管理部门",
            "assist_department": "",
            "action": "企业自查自纠，记录归档",
        },
    }
    
    ent_suggestions = {
        "一级": "立即切断相关设备电源，撤离非必要人员，启动最高级别应急响应",
        "二级": "暂停相关作业，全面排查隐患，整改完成前不得恢复生产",
        "三级": "加强巡检频次，限期完成隐患整改",
        "四级": "按常规安全管理制度执行，保持记录",
    }
    
    return {
        "government": gov_suggestions.get(level, gov_suggestions["四级"]),
        "enterprise": ent_suggestions.get(level, ent_suggestions["四级"]),
        "validation_status": validation.get("final_decision", "UNKNOWN"),
    }


# =============================================================================
# 新增：决策智能体 Workflow 接口（挂载到 /api/v1/agent）
# =============================================================================

@agent_router.post("/decision", response_model=DecisionResponse)
async def decision(request: DecisionRequest) -> Any:
    """
    触发完整决策工作流
    返回包含政府干预（department_primary/actions/deadline_hours）
    与企业管控（equipment_id/operation/parameters）的结构化决策

    若 Workflow 初始化失败（如 GLM-5 API 不可用、模型未训练），
    降级返回 Mock 数据，HTTP 200，并附加 mock=true 标记。
    """
    try:
        workflow = _get_workflow()
        final_state = await workflow.run_async(
            enterprise_id=request.enterprise_id,
            raw_data=request.data,
        )

        prediction = final_state.get("prediction") or {}
        decision_data = final_state.get("decision") or {}

        # 判定是否真正可用：prediction 必须有 predicted_level，且 final_status 不为 UNKNOWN
        # 若模型未训练、Pipeline 缺失、GLM-5 返回空等导致结果为空，强制降级 Mock
        is_valid = (
            prediction.get("predicted_level")
            and final_state.get("final_status") not in (None, "UNKNOWN", "")
            and not final_state.get("error")
        )

        if not is_valid:
            logger.warning("Workflow 返回结果不完整，降级至 Mock")
            mock_resp = _generate_mock_decision(request)
            mock_resp.mock = True
            return mock_resp

        resp = DecisionResponse(
            enterprise_id=request.enterprise_id,
            scenario_id=final_state.get("scenario_id", "chemical"),
            final_status=final_state.get("final_status", "UNKNOWN"),
            predicted_level=prediction.get("predicted_level", ""),
            probability_distribution=prediction.get("probability_distribution", {}),
            shap_contributions=prediction.get("shap_contributions", []),
            risk_level_and_attribution=decision_data.get("risk_level_and_attribution", {}),
            government_intervention=decision_data.get("government_intervention", {}),
            enterprise_control=decision_data.get("enterprise_control", {}),
            march_result=final_state.get("march_result"),
            monte_carlo_result=final_state.get("monte_carlo_result"),
            three_d_risk=final_state.get("three_d_risk"),
            node_status=final_state.get("node_status", []),
        )
        # 写入审计日志
        try:
            from api.routers.audit import AuditLogRequest, log_audit
            await log_audit(AuditLogRequest(
                event_type="DECISION",
                enterprise_id=request.enterprise_id,
                risk_level=prediction.get("predicted_level", ""),
                validation_status=final_state.get("final_status", "UNKNOWN"),
                details=f"决策完成，场景={final_state.get('scenario_id', 'chemical')}",
            ))
        except Exception as audit_err:
            logger.warning(f"审计日志写入失败: {audit_err}")
        return resp
    except Exception as e:
        logger.error(f"决策工作流执行失败，降级至 Mock: {e}")
        mock_resp = _generate_mock_decision(request)
        mock_resp.mock = True
        return mock_resp


async def _mock_decision_stream(
    enterprise_id: str,
    raw_data: Dict[str, Any],
) -> AsyncGenerator[str, None]:
    """Mock SSE 流，当 Workflow 不可用时使用"""
    import asyncio
    scenario_id = raw_data.get("scenario_id", "chemical")
    if scenario_id not in ("chemical", "metallurgy", "dust"):
        scenario_id = "chemical"
    
    mock_nodes = [
        {"node": "data_ingestion", "status": "completed", "detail": f"Mock: 特征工程完成（场景={scenario_id}）"},
        {"node": "risk_assessment", "status": "completed", "detail": "Mock: 预测等级已生成"},
        {"node": "memory_recall", "status": "completed", "detail": "Mock: 长期记忆召回完成"},
        {"node": "decision_generation", "status": "completed", "detail": "Mock: 决策生成与校验完成"},
        {"node": "result_push", "status": "completed", "detail": "Mock: 结果推送完成"},
        {"node": "workflow", "status": "completed", "final_status": "APPROVE", "predicted_level": "红", "mock": True},
    ]
    for item in mock_nodes:
        await asyncio.sleep(0.3)
        yield f"data: {_json.dumps(item, ensure_ascii=False)}\n\n"


async def _decision_stream(
    enterprise_id: str,
    raw_data: Dict[str, Any],
) -> AsyncGenerator[str, None]:
    """SSE 流式输出决策工作流节点状态"""
    try:
        workflow = _get_workflow()
        final_state: Dict[str, Any] = {}
        # 使用 astream 获取中间状态流
        async for state in workflow.graph.astream({
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
            "scenario_id": workflow.scenario.scenario_id,
            "error": None,
        }):
            # state 是 dict，key 为节点名，value 为 AgentState
            for node_name, node_state in state.items():
                if not isinstance(node_state, dict):
                    continue
                final_state = node_state
                node_status_list = node_state.get("node_status", [])
                if node_status_list:
                    latest = node_status_list[-1]
                    yield f"data: {_json.dumps(latest, ensure_ascii=False)}\n\n"

        # astream 已经执行完整工作流，避免再次 run_async 造成重复日志与重复模型调用。
        prediction = final_state.get("prediction") or {}
        summary = {
            "node": "workflow",
            "status": "failed" if final_state.get("error") else "completed",
            "final_status": final_state.get("final_status"),
            "predicted_level": prediction.get("predicted_level"),
            "error": final_state.get("error"),
        }
        yield f"data: {_json.dumps(summary, ensure_ascii=False)}\n\n"
    except Exception as e:
        logger.error(f"SSE 流式输出失败，降级至 Mock 流: {e}")
        async for chunk in _mock_decision_stream(enterprise_id, raw_data):
            yield chunk


@agent_router.post("/decision/stream")
async def decision_stream(request: DecisionRequest) -> StreamingResponse:
    """SSE 流式输出决策工作流节点状态"""
    return StreamingResponse(
        _decision_stream(request.enterprise_id, request.data),
        media_type="text/event-stream",
    )


def _build_llm_config_response(message: str = "") -> LLMConfigResponse:
    config = get_config()
    llm_cfg = config.llm.active
    return LLMConfigResponse(
        provider=config.llm.provider,
        model=llm_cfg.model,
        base_url=llm_cfg.base_url,
        default_temperature=llm_cfg.default_temperature,
        default_max_tokens=llm_cfg.default_max_tokens,
        max_retries=llm_cfg.max_retries,
        has_api_key=bool(llm_cfg.api_key),
        available_providers=config.llm.available_provider_names,
        message=message,
    )


@agent_router.get("/llm", response_model=LLMConfigResponse)
async def get_llm_config() -> LLMConfigResponse:
    """返回当前 LLM 提供方与模型配置，供前端展示。"""
    return _build_llm_config_response()


@agent_router.post("/llm/{provider}", response_model=LLMConfigResponse)
async def switch_llm_provider(provider: str) -> LLMConfigResponse:
    """
    切换当前运行时 LLM 提供方。
    provider 来自配置中的 llm.providers，或由前端自定义创建。
    该切换只影响当前后端进程，重启后仍以配置文件或环境变量为准。
    """
    normalized = provider.lower()

    try:
        config = get_config()
        if normalized not in config.llm.providers:
            config.llm.providers[normalized] = LLMProviderConfig(model=normalized)
        config.llm.provider = normalized
        logger.info(f"LLM provider 已切换为: {normalized}")
        return _build_llm_config_response(f"LLM 已切换为 {normalized}")
    except Exception as e:
        logger.error(f"LLM provider 切换失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@agent_router.post("/llm", response_model=LLMConfigResponse)
async def update_llm_config(request: LLMUpdateRequest) -> LLMConfigResponse:
    """
    创建或更新任意 OpenAI 兼容 LLM provider，并切换为当前运行时配置。
    不持久化写回 config.yaml；如需重启后保留，请同步写入配置文件或环境变量。
    """
    provider = request.provider.strip().lower()
    if not provider:
        raise HTTPException(status_code=400, detail="provider 不能为空")

    try:
        config = get_config()
        current = config.llm.providers.get(provider, LLMProviderConfig())
        updates = request.model_dump(exclude_unset=True)
        updates.pop("provider", None)
        for key, value in updates.items():
            if value is not None:
                setattr(current, key, value)
        config.llm.providers[provider] = current
        config.llm.provider = provider
        logger.info(f"LLM provider 已更新并切换为: {provider}")
        return _build_llm_config_response(f"LLM 配置已更新为 {provider}")
    except Exception as e:
        logger.error(f"LLM 配置更新失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@agent_router.post("/scenario/{scenario_id}", response_model=ScenarioSwitchResponse)
async def switch_scenario(scenario_id: str) -> ScenarioSwitchResponse:
    """
    切换当前场景配置
    支持: chemical（危化品）/ metallurgy（冶金）/ dust（粉尘涉爆）
    返回当前场景阈值参数，供前端展示
    """
    valid_scenarios = {"chemical", "metallurgy", "dust"}
    if scenario_id not in valid_scenarios:
        raise HTTPException(
            status_code=400,
            detail=f"无效场景: {scenario_id}，可选: {', '.join(valid_scenarios)}"
        )
    
    try:
        workflow = _get_workflow()
        workflow.set_scenario(scenario_id)
        scenario_name = workflow.scenario.cfg["name"]
        
        return ScenarioSwitchResponse(
            scenario_id=scenario_id,
            scenario_name=scenario_name,
            message=f"场景已切换至 {scenario_name}，对应知识库子集与校验阈值已更新",
            confidence_threshold=workflow.scenario.confidence_threshold,
            risk_threshold=workflow.scenario.risk_threshold,
            checker_strictness=workflow.scenario.checker_strictness,
            memory_top_k=workflow.scenario.memory_top_k,
        )
    except Exception as e:
        logger.error(f"场景切换失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
