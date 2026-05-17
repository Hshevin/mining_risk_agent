"""
风险预测路由 + GLM-5 决策智能体 Workflow 路由

Router 层仅负责 HTTP 绑定；业务逻辑见 ``api.services.prediction_service``。
"""

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from mining_risk_serve.api.schemas.prediction import (
    DecisionRequest,
    DecisionResponse,
    LLMConfigResponse,
    LLMUpdateRequest,
    PredictRequest,
    PredictResponse,
    QueryRequest,
    ScenarioSwitchResponse,
)
from mining_risk_serve.api.security import require_admin_token
from mining_risk_serve.api.services.prediction_service import PredictionService, get_prediction_service
from mining_risk_common.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()
agent_router = APIRouter()


@router.post("/predict", response_model=PredictResponse)
async def predict(
    request: PredictRequest,
    service: PredictionService = Depends(get_prediction_service),
) -> PredictResponse:
    """风险预测接口（传统堆叠模型链路）。"""
    try:
        return service.predict(request)
    except Exception as exc:
        logger.error("预测失败: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/query")
async def query_history(
    request: QueryRequest,
    service: PredictionService = Depends(get_prediction_service),
) -> List[Dict[str, Any]]:
    """预警历史查询（演示占位）。"""
    return service.query_history(request.enterprise_id, request.risk_level)


@agent_router.post("/decision", response_model=DecisionResponse)
async def decision(
    request: DecisionRequest,
    service: PredictionService = Depends(get_prediction_service),
) -> DecisionResponse:
    """
    触发完整决策工作流。

    默认保留演示降级；生产环境可设置 ``MRA_ENABLE_MOCK_FALLBACK=false``，
    使 Workflow 失败时返回 503，避免真实故障被 HTTP 200 掩盖。
    """
    return await service.run_decision(request)


@agent_router.post("/decision/stream")
async def decision_stream(
    request: DecisionRequest,
    service: PredictionService = Depends(get_prediction_service),
) -> StreamingResponse:
    """SSE 流式输出决策工作流节点状态。"""
    return StreamingResponse(
        service.decision_stream(request),
        media_type="text/event-stream",
    )


@agent_router.get("/llm", response_model=LLMConfigResponse)
async def get_llm_config(
    _: None = Depends(require_admin_token),
    service: PredictionService = Depends(get_prediction_service),
) -> LLMConfigResponse:
    """返回当前 LLM 提供方与模型配置。"""
    return service.get_llm_config()


@agent_router.post("/llm/{provider}", response_model=LLMConfigResponse)
async def switch_llm_provider(
    provider: str,
    _: None = Depends(require_admin_token),
    service: PredictionService = Depends(get_prediction_service),
) -> LLMConfigResponse:
    """切换当前运行时 LLM 提供方。"""
    return service.switch_llm_provider(provider)


@agent_router.post("/llm", response_model=LLMConfigResponse)
async def update_llm_config(
    request: LLMUpdateRequest,
    _: None = Depends(require_admin_token),
    service: PredictionService = Depends(get_prediction_service),
) -> LLMConfigResponse:
    """创建或更新 OpenAI 兼容 LLM provider 并切换为当前运行时配置。"""
    return service.update_llm_config(request)


@agent_router.post("/scenario/{scenario_id}", response_model=ScenarioSwitchResponse)
async def switch_scenario(
    scenario_id: str,
    _: None = Depends(require_admin_token),
    service: PredictionService = Depends(get_prediction_service),
) -> ScenarioSwitchResponse:
    """切换当前场景配置（chemical / metallurgy / dust）。"""
    return service.switch_scenario(scenario_id)
