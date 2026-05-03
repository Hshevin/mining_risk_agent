"""
模型迭代 API 路由
"""

import os
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from iteration.approval_fsm import ApprovalFSM, ApprovalStatus
from iteration.canary import CanaryDeployment
from iteration.monitor import ModelMonitor
from iteration.pipeline import TrainingPipeline
from iteration.regression_test import RegressionTester
from iteration.staging_monitor import StagingMonitor
from utils.config import get_config
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

# =============================================================================
# 请求/响应模型
# =============================================================================


class TriggerRequest(BaseModel):
    model_version: Optional[str] = None
    raw_data_path: Optional[str] = None


class TriggerResponse(BaseModel):
    status: str
    model_version: Optional[str] = None
    model_path: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = None
    message: str = ""


# 状态中文映射
_STATE_MAP = {
    "IDLE": "空闲",
    "MONITORING": "监控中",
    "TRAINING": "训练中",
    "REVIEWING": "审批中",
    "STAGING": "试运行中",
    "CANARY": "灰度发布中",
    "PRODUCTION": "生产",
}


class StatusResponse(BaseModel):
    current_state: str
    current_state_cn: str
    monitor_summary: Dict[str, Any]
    pending_approvals: List[Dict[str, Any]] = Field(default_factory=list)


class ApproveRequest(BaseModel):
    record_id: str
    approver_role: str  # security 或 tech
    approver_name: str


class ApproveResponse(BaseModel):
    record_id: str
    status: str
    message: str


class CanaryRequest(BaseModel):
    model_version: str
    ratio: float
    operator: str = "api_user"
    note: str = ""


class CanaryResponse(BaseModel):
    model_version: str
    previous_ratio: float
    current_ratio: float
    timestamp: float


# =============================================================================
# 全局状态（简化内存状态，生产环境应使用 Redis/DB）
# =============================================================================

_iteration_state = {
    "state": "IDLE",  # IDLE / MONITORING / TRAINING / REVIEWING / STAGING / CANARY / PRODUCTION
    "current_model_version": None,
    "last_training_result": None,
    "approval_record_id": None,
}

_staging_monitor_instance: Optional[StagingMonitor] = None


# =============================================================================
# 路由
# =============================================================================


@router.post("/trigger", response_model=TriggerResponse)
async def trigger_iteration(request: TriggerRequest) -> TriggerResponse:
    """
    手动触发迭代流水线
    """
    try:
        _iteration_state["state"] = "TRAINING"

        pipeline = TrainingPipeline(raw_data_path=request.raw_data_path)
        result = pipeline.run(model_version=request.model_version)

        _iteration_state["state"] = "REVIEWING"
        _iteration_state["last_training_result"] = result
        _iteration_state["current_model_version"] = result["model_version"]

        # 自动创建审批记录
        fsm = ApprovalFSM()
        record_id = f"approval_{result['model_version']}_{int(time.time())}"
        fsm.create_record(record_id, result["model_version"])
        _iteration_state["approval_record_id"] = record_id

        return TriggerResponse(
            status="SUCCESS",
            model_version=result["model_version"],
            model_path=result["model_path"],
            metrics=result.get("metrics"),
            message=f"训练完成，等待审批。记录ID: {record_id}",
        )
    except Exception as e:
        _iteration_state["state"] = "IDLE"
        logger.error(f"迭代触发失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status", response_model=StatusResponse)
async def get_status() -> StatusResponse:
    """
    查询当前迭代状态
    """
    monitor = ModelMonitor()
    summary = monitor.get_monitoring_summary()

    # 查询待审批记录
    pending = []
    # 简化：从内存状态获取
    if _iteration_state.get("approval_record_id"):
        fsm = ApprovalFSM()
        rec = fsm.load_record(_iteration_state["approval_record_id"])
        if rec and rec.status not in (ApprovalStatus.PRODUCTION, ApprovalStatus.ARCHIVED, ApprovalStatus.REJECTED):
            pending.append({
                "record_id": rec.record_id,
                "model_version": rec.model_version,
                "status": rec.status.value,
            })

    return StatusResponse(
        current_state=_iteration_state["state"],
        current_state_cn=_STATE_MAP.get(_iteration_state["state"], _iteration_state["state"]),
        monitor_summary=summary,
        pending_approvals=pending,
    )


@router.post("/approve", response_model=ApproveResponse)
async def approve(request: ApproveRequest) -> ApproveResponse:
    """
    审批人提交审批结果（security/tech 两级）
    """
    try:
        fsm = ApprovalFSM()
        record = fsm.approve(
            record_id=request.record_id,
            approver_role=request.approver_role,
            approver_name=request.approver_name,
        )

        # 如果技术审批通过，自动推进到 STAGING
        if record.status == ApprovalStatus.TECH_APPROVED:
            record = fsm.promote_to_staging(request.record_id)
            _iteration_state["state"] = "STAGING"

            # 启动预生产监控
            global _staging_monitor_instance
            _staging_monitor_instance = StagingMonitor(
                model_version=record.model_version,
                duration_hours=24,
            )
            _staging_monitor_instance.start()

        return ApproveResponse(
            record_id=record.record_id,
            status=record.status.value,
            message=f"审批通过，当前状态: {record.status.value}",
        )
    except Exception as e:
        logger.error(f"审批失败: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/canary", response_model=CanaryResponse)
async def canary(request: CanaryRequest) -> CanaryResponse:
    """
    调整灰度流量比例
    """
    try:
        cd = CanaryDeployment()
        result = cd.set_traffic_ratio(
            model_version=request.model_version,
            ratio=request.ratio,
            operator=request.operator,
            note=request.note,
        )

        if request.ratio == 1.0:
            _iteration_state["state"] = "PRODUCTION"
        elif request.ratio == 0.0:
            _iteration_state["state"] = "IDLE"
        else:
            _iteration_state["state"] = "CANARY"

        return CanaryResponse(
            model_version=result["model_version"],
            previous_ratio=result["previous_ratio"],
            current_ratio=result["current_ratio"],
            timestamp=result["timestamp"],
        )
    except Exception as e:
        logger.error(f"灰度切换失败: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/regression")
async def run_regression(
    old_model_path: str,
    new_model_path: str,
    test_data_path: str,
    output_path: str = "regression_report.json",
) -> Dict:
    """
    手动触发回归测试
    """
    try:
        tester = RegressionTester(
            old_model_path=old_model_path,
            new_model_path=new_model_path,
            test_data_path=test_data_path,
        )
        report = tester.run(output_path=output_path)
        return report
    except Exception as e:
        logger.error(f"回归测试失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
