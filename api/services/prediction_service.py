"""
风险预测与决策智能体业务服务层

将 router 中的核心业务逻辑下沉至此，router 仅负责 HTTP 绑定与异常转换。
"""

import json as _json
import asyncio
from typing import Any, AsyncGenerator, Dict, List, Optional

import pandas as pd
from fastapi import HTTPException

from api.interfaces import FeaturePipeline, RiskPredictor
from api.schemas.prediction import (
    VALID_SCENARIO_IDS,
    DecisionRequest,
    DecisionResponse,
    LLMConfigResponse,
    LLMUpdateRequest,
    PredictRequest,
    PredictResponse,
    ScenarioSwitchResponse,
)
from api.services.dependencies import ResourceRegistry, get_registry, mock_fallback_enabled
from data.field_normalizer import normalize_enterprise_record
from harness.validation import ValidationPipeline
from utils.config import LLMProviderConfig, get_config
from utils.logger import get_logger

logger = get_logger(__name__)


class PredictionService:
    """风险预测与决策工作流服务。

    Args:
        registry: 资源注册表，提供模型/流水线/工作流实例。
    """

    def __init__(self, registry: Optional[ResourceRegistry] = None) -> None:
        self._registry = registry or get_registry()

    def resolve_scenario_id(self, request: DecisionRequest) -> str:
        """从请求中解析有效场景 ID。

        Args:
            request: 决策请求。

        Returns:
            合法场景 ID。

        Raises:
            HTTPException: 场景 ID 不在允许集合内时返回 400。
        """
        scenario_id = (
            request.scenario_id
            or request.data.get("scenario_id")
            or self._registry.default_scenario_id
        )
        if scenario_id not in VALID_SCENARIO_IDS:
            raise HTTPException(
                status_code=400,
                detail="无效场景: %s，可选: chemical, metallurgy, dust" % scenario_id,
            )
        return str(scenario_id)

    def predict(
        self,
        request: PredictRequest,
        model: Optional[RiskPredictor] = None,
        pipeline: Optional[FeaturePipeline] = None,
        validator: Optional[ValidationPipeline] = None,
    ) -> PredictResponse:
        """执行传统风险预测链路。

        Args:
            request: 预测请求。
            model: 可选注入的预测模型。
            pipeline: 可选注入的特征流水线。
            validator: 可选注入的校验器。

        Returns:
            结构化预测结果。

        Raises:
            Exception: 数据标准化、特征工程或推理失败时向上抛出。
        """
        model = model or self._registry.get_model()
        pipeline = pipeline or self._registry.get_pipeline()
        validator = validator or self._registry.get_validator()

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
        features = pipeline.transform(df)
        result = model.predict(features)
        if isinstance(result, list):
            result = result[0]

        decision = {
            "predicted_level": result["predicted_level"],
            "probability_distribution": result["probability_distribution"],
            "shap_contributions": result["shap_contributions"],
            "government_advice": "",
            "enterprise_advice": "",
        }
        validation = validator.run(decision)
        suggestions = self._generate_suggestions(result, validation)

        return PredictResponse(
            enterprise_id=request.enterprise_id,
            predicted_level=result["predicted_level"],
            probability_distribution=result["probability_distribution"],
            shap_contributions=result["shap_contributions"],
            validation_result=validation,
            suggestions=suggestions,
        )

    async def run_decision(self, request: DecisionRequest) -> DecisionResponse:
        """执行完整决策工作流（含 Mock 降级策略）。

        Args:
            request: 决策请求。

        Returns:
            决策响应；失败且允许 Mock 时 ``mock=True``。

        Raises:
            HTTPException: Mock 降级关闭且工作流失败时返回 503。
        """
        scenario_id = self.resolve_scenario_id(request)
        workflow = self._registry.get_workflow(scenario_id)
        try:
            final_state = await workflow.run_async(
                enterprise_id=request.enterprise_id,
                raw_data=request.data,
            )
            prediction = final_state.get("prediction") or {}
            try:
                self._validate_workflow_state(final_state)
            except RuntimeError as invalid_err:
                if not mock_fallback_enabled():
                    raise HTTPException(status_code=503, detail=str(invalid_err)) from invalid_err
                logger.warning("Workflow 返回结果不完整，降级至 Mock: %s", invalid_err)
                mock_resp = self._generate_mock_decision(request)
                mock_resp.mock = True
                return mock_resp

            resp = self._build_decision_response(request, final_state)
            await self._try_audit_decision(request, prediction, final_state)
            return resp
        except HTTPException:
            raise
        except Exception as exc:
            if not mock_fallback_enabled():
                logger.error("决策工作流执行失败: %s", exc)
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            logger.error("决策工作流执行失败，降级至 Mock: %s", exc)
            mock_resp = self._generate_mock_decision(request)
            mock_resp.mock = True
            return mock_resp

    async def decision_stream(
        self,
        request: DecisionRequest,
    ) -> AsyncGenerator[str, None]:
        """产出决策工作流 SSE 事件流。

        Args:
            request: 决策请求。

        Yields:
            ``data: {...}\\n\\n`` 格式的 SSE 块。
        """
        scenario_id = self.resolve_scenario_id(request)
        async for chunk in self._decision_stream(
            request.enterprise_id,
            request.data,
            scenario_id,
            request,
        ):
            yield chunk

    def switch_scenario(self, scenario_id: str) -> ScenarioSwitchResponse:
        """切换默认场景并返回阈值参数。

        Args:
            scenario_id: 目标场景 ID。

        Returns:
            场景切换结果。

        Raises:
            HTTPException: 场景无效或切换失败。
        """
        if scenario_id not in VALID_SCENARIO_IDS:
            raise HTTPException(
                status_code=400,
                detail="无效场景: %s，可选: %s" % (scenario_id, ", ".join(sorted(VALID_SCENARIO_IDS))),
            )
        try:
            self._registry.set_default_scenario(scenario_id)
            workflow = self._registry.get_workflow(scenario_id)
            scenario_name = workflow.scenario.cfg["name"]
            return ScenarioSwitchResponse(
                scenario_id=scenario_id,
                scenario_name=scenario_name,
                message="场景已切换至 %s，对应知识库子集与校验阈值已更新" % scenario_name,
                confidence_threshold=workflow.scenario.confidence_threshold,
                risk_threshold=workflow.scenario.risk_threshold,
                checker_strictness=workflow.scenario.checker_strictness,
                memory_top_k=workflow.scenario.memory_top_k,
            )
        except Exception as exc:
            logger.error("场景切换失败: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def get_llm_config(self, message: str = "") -> LLMConfigResponse:
        """构建当前 LLM 配置响应。"""
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

    def switch_llm_provider(self, provider: str) -> LLMConfigResponse:
        """切换运行时 LLM 提供方。"""
        normalized = provider.lower()
        try:
            config = get_config()
            if normalized not in config.llm.providers:
                config.llm.providers[normalized] = LLMProviderConfig(model=normalized)
            config.llm.provider = normalized
            logger.info("LLM provider 已切换为: %s", normalized)
            return self.get_llm_config("LLM 已切换为 %s" % normalized)
        except Exception as exc:
            logger.error("LLM provider 切换失败: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def update_llm_config(self, request: LLMUpdateRequest) -> LLMConfigResponse:
        """更新并切换 LLM 提供方配置。"""
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
            logger.info("LLM provider 已更新并切换为: %s", provider)
            return self.get_llm_config("LLM 配置已更新为 %s" % provider)
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("LLM 配置更新失败: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def query_history(self, enterprise_id: Optional[str], risk_level: Optional[str]) -> List[Dict[str, Any]]:
        """查询预警历史（演示占位）。"""
        return [
            {
                "enterprise_id": enterprise_id or "demo",
                "timestamp": "2024-01-01T00:00:00",
                "risk_level": risk_level or "一级",
                "status": "已闭环",
            }
        ]

    # -------------------------------------------------------------------------
    # 内部辅助
    # -------------------------------------------------------------------------

    def _generate_mock_decision(self, request: DecisionRequest) -> DecisionResponse:
        scenario_id = request.scenario_id or request.data.get("scenario_id", "chemical")
        if scenario_id not in VALID_SCENARIO_IDS:
            scenario_id = "chemical"
        try:
            from frontend.demo_data import generate_mock_decision as _gen_mock

            mock_dict = _gen_mock(scenario_id, request.enterprise_id)
        except Exception:
            mock_dict = self._fallback_mock_decision(request.enterprise_id, scenario_id)
        return DecisionResponse(**mock_dict)

    @staticmethod
    def _fallback_mock_decision(enterprise_id: str, scenario_id: str) -> Dict[str, Any]:
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
                "department_primary": {
                    "name": "属地应急管理局",
                    "contact_role": "科长",
                    "action": "立即组织现场核查",
                },
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
            "monte_carlo_result": {
                "passed": True,
                "confidence": 0.95,
                "threshold": 0.90,
                "valid_count": 19,
                "total_samples": 20,
                "status": "APPROVE",
                "samples": [],
            },
            "three_d_risk": {
                "severity": "极高",
                "relevance": "极高",
                "irreversibility": "极高",
                "total_score": 3.8,
                "risk_level": "EXTREME",
                "blocked": False,
                "reason": "Mock fallback",
            },
            "node_status": [
                {"node": "data_ingestion", "status": "completed", "timestamp": 0.0, "detail": "Mock fallback"},
                {"node": "risk_assessment", "status": "completed", "timestamp": 0.0, "detail": "Mock fallback"},
                {"node": "memory_recall", "status": "completed", "timestamp": 0.0, "detail": "Mock fallback"},
                {"node": "decision_generation", "status": "completed", "timestamp": 0.0, "detail": "Mock fallback"},
                {"node": "result_push", "status": "completed", "timestamp": 0.0, "detail": "Mock fallback"},
            ],
            "mock": True,
        }

    def _build_decision_response(
        self,
        request: DecisionRequest,
        final_state: Dict[str, Any],
    ) -> DecisionResponse:
        prediction = final_state.get("prediction") or {}
        decision_data = final_state.get("decision") or {}
        return DecisionResponse(
            enterprise_id=request.enterprise_id,
            scenario_id=final_state.get("scenario_id") or self.resolve_scenario_id(request),
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

    @staticmethod
    def _validate_workflow_state(final_state: Dict[str, Any]) -> None:
        prediction = final_state.get("prediction") or {}
        if (
            not prediction.get("predicted_level")
            or final_state.get("final_status") in (None, "UNKNOWN", "")
            or final_state.get("error")
        ):
            detail = final_state.get("error") or "Workflow 返回结果不完整"
            raise RuntimeError(str(detail))

    async def _try_audit_decision(
        self,
        request: DecisionRequest,
        prediction: Dict[str, Any],
        final_state: Dict[str, Any],
    ) -> None:
        try:
            from api.routers.audit import AuditLogRequest, log_audit

            await log_audit(
                AuditLogRequest(
                    event_type="DECISION",
                    enterprise_id=request.enterprise_id,
                    risk_level=prediction.get("predicted_level", ""),
                    validation_status=final_state.get("final_status", "UNKNOWN"),
                    details="决策完成，场景=%s" % final_state.get("scenario_id", "chemical"),
                )
            )
        except Exception as audit_err:
            logger.warning("审计日志写入失败: %s", audit_err)

    async def _decision_stream(
        self,
        enterprise_id: str,
        raw_data: Dict[str, Any],
        scenario_id: str,
        request: DecisionRequest,
    ) -> AsyncGenerator[str, None]:
        try:
            workflow = self._registry.get_workflow(scenario_id)
            final_state: Dict[str, Any] = {}
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
                "scenario_id": scenario_id,
                "error": None,
            }):
                for _node_name, node_state in state.items():
                    if not isinstance(node_state, dict):
                        continue
                    final_state = node_state
                    node_status_list = node_state.get("node_status", [])
                    if node_status_list:
                        latest = node_status_list[-1]
                        yield "data: %s\n\n" % _json.dumps(latest, ensure_ascii=False)

            prediction = final_state.get("prediction") or {}
            try:
                self._validate_workflow_state(final_state)
                decision_response = self._build_decision_response(request, final_state).model_dump()
                status = "completed"
                error = None
            except RuntimeError as invalid_err:
                decision_response = None
                status = "failed"
                error = str(invalid_err)

            summary = {
                "node": "workflow",
                "status": status,
                "final_status": final_state.get("final_status"),
                "predicted_level": prediction.get("predicted_level"),
                "error": error,
                "decision_response": decision_response,
            }
            yield "data: %s\n\n" % _json.dumps(summary, ensure_ascii=False)
        except Exception as exc:
            if not mock_fallback_enabled():
                logger.error("SSE 流式输出失败: %s", exc)
                error_msg = {"node": "workflow", "status": "failed", "error": str(exc)}
                yield "data: %s\n\n" % _json.dumps(error_msg, ensure_ascii=False)
                return
            logger.error("SSE 流式输出失败，降级至 Mock 流: %s", exc)
            async for chunk in self._mock_decision_stream(enterprise_id, raw_data, scenario_id):
                yield chunk

    async def _mock_decision_stream(
        self,
        enterprise_id: str,
        raw_data: Dict[str, Any],
        scenario_id: str,
    ) -> AsyncGenerator[str, None]:
        request = DecisionRequest(enterprise_id=enterprise_id, data=raw_data, scenario_id=scenario_id)
        mock_resp = self._generate_mock_decision(request)
        mock_resp.mock = True
        mock_nodes = [
            {"node": "data_ingestion", "status": "completed", "detail": "Mock: 特征工程完成（场景=%s）" % scenario_id},
            {"node": "risk_assessment", "status": "completed", "detail": "Mock: 预测等级已生成"},
            {"node": "memory_recall", "status": "completed", "detail": "Mock: 长期记忆召回完成"},
            {"node": "decision_generation", "status": "completed", "detail": "Mock: 决策生成与校验完成"},
            {"node": "result_push", "status": "completed", "detail": "Mock: 结果推送完成"},
            {
                "node": "workflow",
                "status": "completed",
                "final_status": mock_resp.final_status,
                "predicted_level": mock_resp.predicted_level,
                "mock": True,
                "decision_response": mock_resp.model_dump(),
            },
        ]
        for item in mock_nodes:
            await asyncio.sleep(0.3)
            yield "data: %s\n\n" % _json.dumps(item, ensure_ascii=False)

    @staticmethod
    def _generate_suggestions(result: Dict[str, Any], validation: Dict[str, Any]) -> Dict[str, Any]:
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


def get_prediction_service() -> PredictionService:
    """FastAPI 依赖：预测与决策服务单例。"""
    return PredictionService(get_registry())
