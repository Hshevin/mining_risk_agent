"""
模型迭代 API 路由
"""

import csv
import io
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from mining_risk_serve.api.security import require_admin_token
from mining_risk_serve.iteration.approval_fsm import ApprovalFSM, ApprovalStatus
from mining_risk_serve.iteration.canary import CanaryDeployment
from mining_risk_serve.iteration.data_source import BatchMetadata
from mining_risk_serve.iteration.demo_replay import DemoReplayService
from mining_risk_serve.iteration.demo_runner import DemoIterationError, DemoIterationRunner
from mining_risk_serve.iteration.monitor import ModelMonitor
from mining_risk_train.iteration.pipeline import TrainingPipeline
from mining_risk_train.iteration.regression_test import RegressionTester
from mining_risk_serve.iteration.staging_monitor import StagingMonitor
from mining_risk_common.utils.config import get_config, resolve_project_path
from mining_risk_common.utils.logger import get_logger

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
    "BLOCKED": "门禁阻断",
}


class StatusResponse(BaseModel):
    current_state: str
    current_state_cn: str
    monitor_summary: Dict[str, Any]
    pending_approvals: List[Dict[str, Any]] = Field(default_factory=list)
    data_source: Optional[Dict[str, Any]] = None
    last_demo_replay: Optional[Dict[str, Any]] = None
    latest_iteration: Optional[Dict[str, Any]] = None


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


class DemoBatchResponse(BaseModel):
    metadata: Dict[str, Any]
    source: str
    record_count: int
    records: List[Dict[str, Any]] = Field(default_factory=list)
    gates: Dict[str, Any] = Field(default_factory=dict)


class DemoReplayResponse(BaseModel):
    status: str
    retrain_required: bool
    blocked: bool
    triggered: Optional[bool] = None
    trigger_reasons: List[str] = Field(default_factory=list)
    blocked_gates: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any]
    report_path: str
    iteration_id: Optional[str] = None
    current_status: Optional[str] = None
    timeline: List[Dict[str, Any]] = Field(default_factory=list)
    next_actions: List[Dict[str, Any]] = Field(default_factory=list)
    iteration: Optional[Dict[str, Any]] = None
    report: Dict[str, Any]
    message: str


class IterationRecordResponse(BaseModel):
    iteration_id: str
    batch_id: str
    data_source: Dict[str, Any]
    batch: Dict[str, Any]
    sample_count: int
    risk_sample_count: int
    recent_f1: float
    trigger_threshold_samples: int
    trigger_threshold_f1: float
    thresholds: Dict[str, Any]
    triggered: bool
    retrain_required: bool
    trigger_reasons: List[str] = Field(default_factory=list)
    current_status: str
    timeline: List[Dict[str, Any]] = Field(default_factory=list)
    report_path: str
    next_actions: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: str
    updated_at: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    demo_mode: bool = False
    training_report: Optional[Dict[str, Any]] = None
    training_report_path: Optional[str] = None
    candidate_model_path: Optional[str] = None
    model_version: Optional[str] = None
    regression_report: Optional[Dict[str, Any]] = None
    regression_report_path: Optional[str] = None
    drift_report: Optional[Dict[str, Any]] = None
    drift_report_path: Optional[str] = None
    pr_metadata: Optional[Dict[str, Any]] = None
    pr_metadata_path: Optional[str] = None
    local_pr_metadata_path: Optional[str] = None
    ci_report: Optional[Dict[str, Any]] = None
    ci_report_path: Optional[str] = None
    approval_logs: List[Dict[str, Any]] = Field(default_factory=list)
    staging_report: Optional[Dict[str, Any]] = None
    staging_report_path: Optional[str] = None
    canary_percentage: float = 0.0
    canary_events: List[Dict[str, Any]] = Field(default_factory=list)
    audit_archive_path: Optional[str] = None
    blocked_reason: Optional[str] = None


class IterationTimelineResponse(BaseModel):
    iteration_id: str
    batch_id: str
    current_status: str
    triggered: bool
    timeline: List[Dict[str, Any]] = Field(default_factory=list)


class UploadBatchResponse(BaseModel):
    status: str
    batch_id: str
    original_filename: str
    dataset_kind: str
    detected_encoding: str
    header_row_index: int
    detected_columns: List[str] = Field(default_factory=list)
    risk_column_used: Optional[str] = None
    risk_detection_strategy: str
    parsing_warnings: List[str] = Field(default_factory=list)
    sample_count: int
    risk_sample_count: int
    recent_f1: float
    triggered: bool
    retrain_required: bool
    trigger_reasons: List[str] = Field(default_factory=list)
    current_status: str
    report_path: str
    upload_report_path: str
    iteration_id: str
    timeline: List[Dict[str, Any]] = Field(default_factory=list)
    next_actions: List[Dict[str, Any]] = Field(default_factory=list)
    iteration: Dict[str, Any]
    upload_report: Dict[str, Any]
    message: str


class DemoResetResponse(BaseModel):
    status: str
    archived_iterations: int
    archived_runs: int
    latest_iteration: Optional[Dict[str, Any]] = None
    latest_run: Optional[Dict[str, Any]] = None
    message: str


class DemoApprovalRequest(BaseModel):
    approver: str = "demo_reviewer"
    note: str = ""


class DemoCanaryAdvanceRequest(BaseModel):
    target_percentage: Optional[float] = None
    operator: str = "demo_operator"


class DemoIterationStepResponse(BaseModel):
    iteration_id: str
    batch_id: str
    current_status: str
    timeline: List[Dict[str, Any]] = Field(default_factory=list)
    next_actions: List[Dict[str, Any]] = Field(default_factory=list)
    iteration: Dict[str, Any]
    report: Optional[Dict[str, Any]] = None
    message: str


class IterationAuditResponse(BaseModel):
    audit_archive_path: str
    audit: Dict[str, Any]


class IterationReportsResponse(BaseModel):
    iteration_id: str
    batch_id: str
    current_status: str
    reports: Dict[str, Any]


class IterationReportResponse(BaseModel):
    iteration_id: str
    batch_id: str
    report_type: str
    path: str
    content: Dict[str, Any]


# =============================================================================
# 全局状态（简化内存状态，生产环境应使用 Redis/DB）
# =============================================================================

_iteration_state = {
    "state": "IDLE",  # IDLE / MONITORING / TRAINING / REVIEWING / STAGING / CANARY / PRODUCTION
    "current_model_version": None,
    "last_training_result": None,
    "approval_record_id": None,
    "last_demo_replay": None,
}

_staging_monitor_instance: Optional[StagingMonitor] = None

_F1_COLUMNS = ("recent_f1", "f1", "f1_score")


def _safe_filename(filename: str) -> str:
    name = Path(filename or "upload.csv").name
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "upload.csv"


def _recent_f1_from_rows(rows: List[Dict[str, Any]], fallback: float) -> float:
    values: List[float] = []
    for row in rows:
        for column in _F1_COLUMNS:
            raw = row.get(column)
            if raw in (None, ""):
                continue
            try:
                values.append(float(raw))
            except (TypeError, ValueError):
                continue
            break
    if not values:
        return fallback
    return round(sum(values) / len(values), 4)


# Upload parser definitions for manual labels and public accident CSV files.
_DATASET_KINDS = {"auto", "public_accident", "manual_labeled"}
_CANONICAL_RISK_COLUMNS = ("risk_label", "label", "risk_level")
_RISK_FIELD_ALIASES = (
    *_CANONICAL_RISK_COLUMNS,
    "分类分级",
    "风险等级",
    "最新风险等级",
    "事故",
    "是否事故",
    "是否发生事故",
    "案件名称",
    "处罚次数",
    "重大事故隐患",
    "隐患等级",
    "问题隐患",
    "执法处罚",
    "事故概述",
    "latest_risk_level",
    "accident",
    "is_accident",
    "case_level",
    "penalty_count",
    "major_hazard",
    "hidden_danger",
    "trouble_count",
    "risk_with_accident_count",
)
_SUGGESTED_RISK_COLUMNS = list(_RISK_FIELD_ALIASES)
_RISK_POSITIVE_VALUES = {
    "1",
    "true",
    "yes",
    "y",
    "risk",
    "high",
    "critical",
    "red",
    "orange",
    "yellow",
    "是",
    "有",
    "发生",
    "已发生",
    "风险",
    "高",
    "较高",
    "中",
    "重大",
    "严重",
    "红",
    "橙",
    "黄",
}
_RISK_NEGATIVE_VALUES = {
    "",
    "0",
    "false",
    "no",
    "n",
    "normal",
    "low",
    "blue",
    "green",
    "none",
    "safe",
    "否",
    "无",
    "未发生",
    "正常",
    "低",
    "蓝",
    "绿",
    "安全",
}


def _decode_csv(content: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return content.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise HTTPException(
        status_code=400,
        detail={
            "message": "CSV 文件编码无法识别，请使用 UTF-8、UTF-8-SIG 或 GB18030。",
            "detected_columns": [],
            "header_row_index": None,
            "suggested_columns": _SUGGESTED_RISK_COLUMNS,
        },
    )


def _risk_value(value: Any) -> bool:
    text = str(value if value is not None else "").strip().lower()
    if text in _RISK_NEGATIVE_VALUES:
        return False
    if text in _RISK_POSITIVE_VALUES:
        return True
    try:
        return float(text) > 0
    except ValueError:
        pass
    if any(marker in text for marker in ("事故", "隐患", "处罚", "违法", "高风险", "重大")):
        return True
    return bool(text)


def _normalize_column_name(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lstrip("\ufeff")).lower()


def _is_placeholder_header(columns: List[str]) -> bool:
    usable = [column.strip() for column in columns if column and column.strip()]
    return bool(usable) and all(re.fullmatch(r"(?i)column\d+", column) for column in usable)


def _deduplicate_columns(columns: List[str]) -> List[str]:
    seen: Dict[str, int] = {}
    result: List[str] = []
    for index, raw in enumerate(columns, start=1):
        base = str(raw or "").strip().lstrip("\ufeff") or f"Column{index}"
        count = seen.get(base, 0)
        seen[base] = count + 1
        result.append(base if count == 0 else f"{base}.{count}")
    return result


def _find_risk_column(columns: List[str]) -> tuple[Optional[str], str]:
    normalized_to_original = {_normalize_column_name(column): column for column in columns}
    for column in _CANONICAL_RISK_COLUMNS:
        normalized = _normalize_column_name(column)
        if normalized in normalized_to_original:
            return normalized_to_original[normalized], "explicit_label_column"
    for alias in _RISK_FIELD_ALIASES:
        normalized = _normalize_column_name(alias)
        if normalized in normalized_to_original:
            return normalized_to_original[normalized], "risk_alias_column"
    return None, "not_detected"


def _csv_error(
    message: str,
    *,
    detected_columns: Optional[List[str]] = None,
    header_row_index: Optional[int] = None,
) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={
            "message": message,
            "detected_columns": detected_columns or [],
            "header_row_index": header_row_index,
            "suggested_columns": _SUGGESTED_RISK_COLUMNS,
        },
    )


def _read_uploaded_csv(content: bytes, *, dataset_kind: str) -> Dict[str, Any]:
    decoded, detected_encoding = _decode_csv(content)
    reader = csv.reader(io.StringIO(decoded))
    raw_rows = [row for row in reader if any(str(cell).strip() for cell in row)]
    if not raw_rows:
        raise _csv_error("CSV 没有可入库的数据行。")

    header_row_index = 1
    parsing_warnings: List[str] = []
    header = raw_rows[0]
    if _is_placeholder_header(header) and len(raw_rows) >= 2:
        header = raw_rows[1]
        header_row_index = 2
        parsing_warnings.append("检测到第一行是 Column1/Column2 占位表头，已自动使用第二行作为真实表头。")
    elif _is_placeholder_header(header):
        raise _csv_error(
            "CSV 第一行是 Column1/Column2 占位表头，但没有第二行真实表头。",
            detected_columns=_deduplicate_columns(header),
            header_row_index=header_row_index,
        )

    columns = _deduplicate_columns(header)
    if not columns:
        raise _csv_error("CSV 缺少表头。", header_row_index=header_row_index)

    rows: List[Dict[str, Any]] = []
    for raw in raw_rows[header_row_index:]:
        rows.append(
            {
                column: (raw[index] if index < len(raw) else "")
                for index, column in enumerate(columns)
            }
        )
    if not rows:
        raise _csv_error(
            "CSV 没有可入库的数据行。",
            detected_columns=columns,
            header_row_index=header_row_index,
        )

    risk_column, strategy = _find_risk_column(columns)
    if dataset_kind == "manual_labeled" and not risk_column:
        raise _csv_error(
            "手动标注 CSV 必须包含明确标签字段，例如 risk_label、label、risk_level、风险等级或是否事故。",
            detected_columns=columns,
            header_row_index=header_row_index,
        )
    if dataset_kind == "auto" and not risk_column:
        raise _csv_error(
            "自动识别未找到可用于判断风险的字段。请选择“公开新增事故数据”，或增加 risk_label/label/risk_level/风险等级/是否事故 等字段。",
            detected_columns=columns,
            header_row_index=header_row_index,
        )

    if dataset_kind == "public_accident":
        risk_sample_count = len(rows)
        strategy = (
            "public_accident_all_rows_with_detected_reference"
            if risk_column
            else "public_accident_all_rows"
        )
        parsing_warnings.append("公开新增事故数据模式下，每一行默认按新增风险历史样本入库。")
    else:
        risk_sample_count = sum(1 for row in rows if _risk_value(row.get(risk_column)))
        strategy = (
            f"auto_alias_column:{risk_column}"
            if strategy == "risk_alias_column"
            else f"explicit_label_column:{risk_column}"
        )

    return {
        "rows": rows,
        "detected_encoding": detected_encoding,
        "header_row_index": header_row_index,
        "detected_columns": columns,
        "risk_column_used": risk_column,
        "risk_detection_strategy": strategy,
        "risk_sample_count": risk_sample_count,
        "parsing_warnings": parsing_warnings,
    }


def _demo_runner() -> DemoIterationRunner:
    return DemoIterationRunner(replay_service=DemoReplayService())


def _sync_iteration_state(iteration: Dict[str, Any]) -> None:
    current_status = iteration.get("current_status") or "IDLE"
    _iteration_state["state"] = current_status
    _iteration_state["current_model_version"] = iteration.get("model_version")
    _iteration_state["last_demo_replay"] = {
        "batch_id": iteration.get("batch_id"),
        "iteration_id": iteration.get("iteration_id"),
        "status": current_status,
        "retrain_required": iteration.get("retrain_required", False),
        "blocked": current_status in {"REGRESSION_BLOCKED", "DRIFT_BLOCKED", "CI_FAILED"},
        "trigger_reasons": iteration.get("trigger_reasons", []),
        "blocked_gates": iteration.get("metadata", {}).get("initial_blocked_gates", []),
        "report_path": iteration.get("report_path", ""),
        "metadata": iteration.get("batch", {}),
        "iteration": iteration,
    }


def _handle_demo_error(error: DemoIterationError) -> None:
    if error.record is not None:
        _sync_iteration_state(error.record.to_dict())
    raise HTTPException(status_code=error.status_code, detail=str(error))


# =============================================================================
# 路由
# =============================================================================


@router.get("/data-source")
async def get_data_source() -> Dict[str, Any]:
    """
    查询当前模型迭代数据源。
    """
    service = DemoReplayService()
    return service.data_source.describe()


@router.get("/demo-batches")
async def list_demo_batches() -> List[Dict[str, Any]]:
    """
    列出 datasets/demo 中的演示回放批次。
    """
    service = DemoReplayService()
    return service.list_batches()


@router.get("/demo-batches/{batch_id}", response_model=DemoBatchResponse)
async def load_demo_batch(batch_id: str) -> DemoBatchResponse:
    """
    加载某个演示批次，不触发训练。
    """
    try:
        batch = DemoReplayService().load_batch(batch_id)
        payload = batch.to_dict(include_records=True)
        return DemoBatchResponse(**payload)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"demo batch not found: {batch_id}")


@router.post("/demo-batches/{batch_id}/load", response_model=DemoReplayResponse)
async def replay_demo_batch(batch_id: str) -> DemoReplayResponse:
    """
    回放演示批次，写入后端状态、报告与可追踪记录。
    """
    try:
        service = DemoReplayService()
        report = service.replay_batch(batch_id)
        evaluation = report["evaluation"]

        if evaluation["blocked"]:
            _iteration_state["state"] = "BLOCKED"
        elif evaluation["retrain_required"]:
            _iteration_state["state"] = "MONITORING"
        else:
            _iteration_state["state"] = "IDLE"

        _iteration_state["last_demo_replay"] = {
            "batch_id": report["metadata"]["batch_id"],
            "iteration_id": report.get("iteration_id"),
            "status": evaluation["status"],
            "retrain_required": evaluation["retrain_required"],
            "blocked": evaluation["blocked"],
            "trigger_reasons": evaluation["trigger_reasons"],
            "blocked_gates": evaluation["blocked_gates"],
            "report_path": report["report_path"],
            "metadata": report["metadata"],
            "iteration": report.get("iteration"),
        }

        if evaluation["blocked"]:
            message = "演示批次已加载，门禁检查已阻断候选模型"
        elif evaluation["retrain_required"]:
            message = "演示批次已加载，监控规则触发重训信号"
        else:
            message = "演示批次已加载，未触发重训"

        return DemoReplayResponse(
            status=evaluation["status"],
            retrain_required=evaluation["retrain_required"],
            blocked=evaluation["blocked"],
            triggered=evaluation["retrain_required"],
            trigger_reasons=evaluation["trigger_reasons"],
            blocked_gates=evaluation["blocked_gates"],
            metadata=report["metadata"],
            report_path=report["report_path"],
            iteration_id=report.get("iteration_id"),
            current_status=(report.get("iteration") or {}).get("current_status"),
            timeline=(report.get("iteration") or {}).get("timeline", []),
            next_actions=(report.get("iteration") or {}).get("next_actions", []),
            iteration=report.get("iteration"),
            report=report,
            message=message,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"demo batch not found: {batch_id}")


@router.post("/upload-batch", response_model=UploadBatchResponse)
async def enhanced_upload_iteration_batch(
    file: UploadFile = File(...),
    dataset_kind: str = Form("auto"),
    recent_f1_override: Optional[float] = Form(None),
) -> UploadBatchResponse:
    """
    上传一期企业更新数据，并写入统一 IterationRecord。

    dataset_kind:
    - auto: 自动识别风险字段；
    - public_accident: 公开新增事故数据，无标签字段也允许上传，每行默认视为新增风险历史样本；
    - manual_labeled: 手动标注 CSV，必须包含明确标签字段。
    """
    filename = file.filename or "upload.csv"
    normalized_kind = (dataset_kind or "auto").strip().lower()
    if normalized_kind not in _DATASET_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"dataset_kind 仅支持 auto、public_accident、manual_labeled，当前值：{dataset_kind}",
        )

    suffix = Path(filename).suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        raise HTTPException(status_code=400, detail="Excel 上传即将支持，请先上传 CSV 文件。")
    if suffix != ".csv":
        raise HTTPException(status_code=400, detail="仅支持 CSV 文件，Excel 即将支持。")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空。")

    service = DemoReplayService()
    parsed = _read_uploaded_csv(content, dataset_kind=normalized_kind)
    rows = parsed["rows"]
    risk_sample_count = int(parsed["risk_sample_count"])
    recent_f1 = (
        round(float(recent_f1_override), 4)
        if recent_f1_override is not None
        else _recent_f1_from_rows(rows, service.f1_threshold + 0.05)
    )
    parsing_warnings = list(parsed["parsing_warnings"])
    if recent_f1_override is not None:
        parsing_warnings.append(f"已使用 recent_f1_override={recent_f1:.4f} 覆盖 CSV 内 F1 字段。")

    batch_id = f"upload_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    upload_dir = resolve_project_path(Path(get_config().paths.var_root) / "uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    upload_path = upload_dir / f"{batch_id}_{_safe_filename(filename)}"
    upload_path.write_bytes(content)

    metadata = BatchMetadata(
        batch_id=batch_id,
        sample_count=len(rows),
        risk_sample_count=risk_sample_count,
        recent_f1=recent_f1,
        description=f"Uploaded enterprise update batch: {filename}",
        scenario="UPLOAD_BATCH",
        tags=["upload", normalized_kind, "enterprise_data"],
    )
    report = service.record_uploaded_batch(
        metadata=metadata,
        upload_path=upload_path,
        records_preview=rows[:5],
    )
    evaluation = report["evaluation"]

    upload_report = {
        "original_filename": filename,
        "dataset_kind": normalized_kind,
        "detected_encoding": parsed["detected_encoding"],
        "header_row_index": parsed["header_row_index"],
        "detected_columns": parsed["detected_columns"],
        "risk_column_used": parsed["risk_column_used"],
        "risk_detection_strategy": parsed["risk_detection_strategy"],
        "sample_count": len(rows),
        "risk_sample_count": risk_sample_count,
        "recent_f1": recent_f1,
        "triggered": evaluation["retrain_required"],
        "trigger_reasons": evaluation["trigger_reasons"],
        "parsing_warnings": parsing_warnings,
        "upload_path": str(upload_path),
        "iteration_id": report["iteration_id"],
    }
    upload_report_dir = resolve_project_path("reports/uploads")
    upload_report_dir.mkdir(parents=True, exist_ok=True)
    upload_report_path = upload_report_dir / f"{batch_id}_upload_report.json"
    with upload_report_path.open("w", encoding="utf-8") as f:
        json.dump(upload_report, f, ensure_ascii=False, indent=2)

    record = service.state_store.get_record(report["iteration_id"])
    if record is None:
        raise HTTPException(status_code=500, detail="上传批次已入库，但 IterationRecord 未生成。")
    record.metadata.update(
        {
            "dataset_kind": normalized_kind,
            "original_filename": filename,
            "detected_encoding": parsed["detected_encoding"],
            "header_row_index": parsed["header_row_index"],
            "detected_columns": parsed["detected_columns"],
            "risk_column_used": parsed["risk_column_used"],
            "risk_detection_strategy": parsed["risk_detection_strategy"],
            "parsing_warnings": parsing_warnings,
            "upload_report_path": str(upload_report_path),
            "upload_report": upload_report,
        }
    )
    record = service.state_store.save_record(record)
    iteration = record.to_dict()
    report["iteration"] = iteration
    report["upload_report_path"] = str(upload_report_path)
    report["upload_report"] = upload_report
    with Path(report["report_path"]).open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    if evaluation["blocked"]:
        _iteration_state["state"] = "BLOCKED"
    elif evaluation["retrain_required"]:
        _iteration_state["state"] = "MONITORING"
    else:
        _iteration_state["state"] = "IDLE"
    _iteration_state["last_demo_replay"] = {
        "batch_id": batch_id,
        "iteration_id": report["iteration_id"],
        "status": evaluation["status"],
        "retrain_required": evaluation["retrain_required"],
        "blocked": evaluation["blocked"],
        "trigger_reasons": evaluation["trigger_reasons"],
        "blocked_gates": evaluation["blocked_gates"],
        "report_path": report["report_path"],
        "metadata": metadata.to_dict(),
        "iteration": iteration,
    }

    return UploadBatchResponse(
        status=evaluation["status"],
        batch_id=batch_id,
        original_filename=filename,
        dataset_kind=normalized_kind,
        detected_encoding=parsed["detected_encoding"],
        header_row_index=parsed["header_row_index"],
        detected_columns=parsed["detected_columns"],
        risk_column_used=parsed["risk_column_used"],
        risk_detection_strategy=parsed["risk_detection_strategy"],
        parsing_warnings=parsing_warnings,
        sample_count=len(rows),
        risk_sample_count=risk_sample_count,
        recent_f1=recent_f1,
        triggered=evaluation["retrain_required"],
        retrain_required=evaluation["retrain_required"],
        trigger_reasons=evaluation["trigger_reasons"],
        current_status=iteration["current_status"],
        report_path=report["report_path"],
        upload_report_path=str(upload_report_path),
        iteration_id=report["iteration_id"],
        timeline=iteration.get("timeline", []),
        next_actions=iteration.get("next_actions", []),
        iteration=iteration,
        upload_report=upload_report,
        message="上传批次已入库并完成触发判断。",
    )


@router.post("/upload-batch-legacy", response_model=UploadBatchResponse)
async def upload_iteration_batch(file: UploadFile = File(...)) -> UploadBatchResponse:
    """
    上传一期企业更新数据，并写入统一 IterationRecord。

    目前最小实现支持 CSV；Excel 文件会返回清晰错误，避免前端误判为空状态。
    CSV 必须包含 risk_label、label 或 risk_level 字段，可选 recent_f1/f1/f1_score。
    """
    return await enhanced_upload_iteration_batch(
        file=file,
        dataset_kind="auto",
        recent_f1_override=None,
    )

    filename = file.filename or "upload.csv"
    suffix = Path(filename).suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        raise HTTPException(status_code=400, detail="Excel 上传即将支持，请先上传 CSV 文件")
    if suffix != ".csv":
        raise HTTPException(status_code=400, detail="仅支持 CSV 文件，Excel 即将支持")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空")

    service = DemoReplayService()
    rows, risk_column = _read_uploaded_csv(content)
    risk_sample_count = sum(1 for row in rows if _risk_value(row.get(risk_column)))
    recent_f1 = _recent_f1_from_rows(rows, service.f1_threshold + 0.05)

    batch_id = f"upload_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    upload_dir = resolve_project_path(Path(get_config().paths.var_root) / "uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    upload_path = upload_dir / f"{batch_id}_{_safe_filename(filename)}"
    upload_path.write_bytes(content)

    metadata = BatchMetadata(
        batch_id=batch_id,
        sample_count=len(rows),
        risk_sample_count=risk_sample_count,
        recent_f1=recent_f1,
        description=f"Uploaded enterprise update batch: {filename}",
        scenario="UPLOAD_BATCH",
        tags=["upload", "enterprise_data"],
    )
    report = service.record_uploaded_batch(
        metadata=metadata,
        upload_path=upload_path,
        records_preview=rows[:5],
    )
    evaluation = report["evaluation"]
    iteration = report["iteration"]

    if evaluation["blocked"]:
        _iteration_state["state"] = "BLOCKED"
    elif evaluation["retrain_required"]:
        _iteration_state["state"] = "MONITORING"
    else:
        _iteration_state["state"] = "IDLE"
    _iteration_state["last_demo_replay"] = {
        "batch_id": batch_id,
        "iteration_id": report["iteration_id"],
        "status": evaluation["status"],
        "retrain_required": evaluation["retrain_required"],
        "blocked": evaluation["blocked"],
        "trigger_reasons": evaluation["trigger_reasons"],
        "blocked_gates": evaluation["blocked_gates"],
        "report_path": report["report_path"],
        "metadata": metadata.to_dict(),
        "iteration": iteration,
    }

    return UploadBatchResponse(
        status=evaluation["status"],
        batch_id=batch_id,
        sample_count=len(rows),
        risk_sample_count=risk_sample_count,
        recent_f1=recent_f1,
        triggered=evaluation["retrain_required"],
        retrain_required=evaluation["retrain_required"],
        trigger_reasons=evaluation["trigger_reasons"],
        current_status=iteration["current_status"],
        report_path=report["report_path"],
        iteration_id=report["iteration_id"],
        timeline=iteration.get("timeline", []),
        next_actions=iteration.get("next_actions", []),
        iteration=iteration,
        message="上传批次已入库并完成触发判断",
    )


@router.post("/demo/reset", response_model=DemoResetResponse)
async def reset_demo_iteration_state() -> DemoResetResponse:
    """
    重置路演状态：归档当前演示 IterationRecord 和 replay run，不删除原始 demo batch 文件。
    """
    service = DemoReplayService()
    result = service.reset_demo_state()
    _iteration_state.update(
        {
            "state": "IDLE",
            "current_model_version": None,
            "last_training_result": None,
            "approval_record_id": None,
            "last_demo_replay": None,
        }
    )
    return DemoResetResponse(**result)


@router.get("/latest", response_model=IterationRecordResponse)
async def get_latest_iteration() -> IterationRecordResponse:
    """
    查询最近一次数据入库后的统一迭代状态。
    """
    record = DemoReplayService().latest_iteration_record()
    if record is None:
        raise HTTPException(status_code=404, detail="iteration record not found")
    return IterationRecordResponse(**record)


@router.get("/batches/{batch_id}/latest-run", response_model=IterationRecordResponse)
async def get_latest_iteration_for_batch(batch_id: str) -> IterationRecordResponse:
    """
    查询某个批次最近一次加载产生的迭代状态。
    """
    record = DemoReplayService().latest_iteration_for_batch(batch_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"iteration record not found for batch: {batch_id}")
    return IterationRecordResponse(**record)


@router.get("/{iteration_id}/timeline", response_model=IterationTimelineResponse)
async def get_iteration_timeline(iteration_id: str) -> IterationTimelineResponse:
    """
    查询某次迭代的时间线。
    """
    timeline = DemoReplayService().get_iteration_timeline(iteration_id)
    if timeline is None:
        raise HTTPException(status_code=404, detail=f"iteration record not found: {iteration_id}")
    return IterationTimelineResponse(**timeline)


def _demo_step_response(result: Dict[str, Any]) -> DemoIterationStepResponse:
    _sync_iteration_state(result["iteration"])
    return DemoIterationStepResponse(**result)


@router.post("/{iteration_id}/train", response_model=DemoIterationStepResponse)
async def train_demo_candidate(iteration_id: str) -> DemoIterationStepResponse:
    try:
        return _demo_step_response(_demo_runner().train_candidate(iteration_id))
    except DemoIterationError as error:
        _handle_demo_error(error)


@router.post("/{iteration_id}/regression-test", response_model=DemoIterationStepResponse)
async def run_demo_regression_test(iteration_id: str) -> DemoIterationStepResponse:
    try:
        return _demo_step_response(_demo_runner().run_regression_test(iteration_id))
    except DemoIterationError as error:
        _handle_demo_error(error)


@router.post("/{iteration_id}/drift-analysis", response_model=DemoIterationStepResponse)
async def run_demo_drift_analysis(iteration_id: str) -> DemoIterationStepResponse:
    try:
        return _demo_step_response(_demo_runner().run_drift_analysis(iteration_id))
    except DemoIterationError as error:
        _handle_demo_error(error)


@router.post("/{iteration_id}/pr/create", response_model=DemoIterationStepResponse)
async def create_demo_pr_metadata(iteration_id: str) -> DemoIterationStepResponse:
    try:
        return _demo_step_response(_demo_runner().create_pr_metadata(iteration_id))
    except DemoIterationError as error:
        _handle_demo_error(error)


@router.post("/{iteration_id}/ci/run", response_model=DemoIterationStepResponse)
async def run_demo_ci_precheck(iteration_id: str) -> DemoIterationStepResponse:
    try:
        return _demo_step_response(_demo_runner().run_ci_precheck(iteration_id))
    except DemoIterationError as error:
        _handle_demo_error(error)


@router.post("/{iteration_id}/approve/safety", response_model=DemoIterationStepResponse)
async def approve_demo_safety(
    iteration_id: str,
    request: DemoApprovalRequest = DemoApprovalRequest(
        approver="demo_safety_reviewer",
        note="demo safety approval",
    ),
) -> DemoIterationStepResponse:
    try:
        return _demo_step_response(
            _demo_runner().approve_safety(
                iteration_id,
                approver=request.approver,
                note=request.note or "demo safety approval",
            )
        )
    except DemoIterationError as error:
        _handle_demo_error(error)


@router.post("/{iteration_id}/approve/tech", response_model=DemoIterationStepResponse)
async def approve_demo_tech(
    iteration_id: str,
    request: DemoApprovalRequest = DemoApprovalRequest(
        approver="demo_tech_reviewer",
        note="demo technical approval",
    ),
) -> DemoIterationStepResponse:
    try:
        return _demo_step_response(
            _demo_runner().approve_tech(
                iteration_id,
                approver=request.approver,
                note=request.note or "demo technical approval",
            )
        )
    except DemoIterationError as error:
        _handle_demo_error(error)


@router.post("/{iteration_id}/staging/start", response_model=DemoIterationStepResponse)
async def start_demo_staging(iteration_id: str) -> DemoIterationStepResponse:
    try:
        return _demo_step_response(_demo_runner().start_staging(iteration_id))
    except DemoIterationError as error:
        _handle_demo_error(error)


@router.post("/{iteration_id}/staging/complete-demo", response_model=DemoIterationStepResponse)
async def complete_demo_staging(iteration_id: str) -> DemoIterationStepResponse:
    try:
        return _demo_step_response(_demo_runner().complete_staging_demo(iteration_id))
    except DemoIterationError as error:
        _handle_demo_error(error)


@router.post("/{iteration_id}/canary/advance", response_model=DemoIterationStepResponse)
async def advance_demo_canary(
    iteration_id: str,
    request: DemoCanaryAdvanceRequest = DemoCanaryAdvanceRequest(),
) -> DemoIterationStepResponse:
    try:
        return _demo_step_response(
            _demo_runner().advance_canary(
                iteration_id,
                target_percentage=request.target_percentage,
                operator=request.operator,
            )
        )
    except DemoIterationError as error:
        _handle_demo_error(error)


@router.post("/{iteration_id}/demo/run-next-step", response_model=DemoIterationStepResponse)
async def run_demo_next_step(iteration_id: str) -> DemoIterationStepResponse:
    try:
        return _demo_step_response(_demo_runner().run_next_step(iteration_id))
    except DemoIterationError as error:
        _handle_demo_error(error)


@router.post("/{iteration_id}/demo/run-to-end", response_model=DemoIterationStepResponse)
async def run_demo_to_end(iteration_id: str) -> DemoIterationStepResponse:
    try:
        return _demo_step_response(_demo_runner().run_to_end(iteration_id))
    except DemoIterationError as error:
        _handle_demo_error(error)


@router.get("/{iteration_id}/audit", response_model=IterationAuditResponse)
async def get_iteration_audit(iteration_id: str) -> IterationAuditResponse:
    try:
        return IterationAuditResponse(**_demo_runner().get_audit(iteration_id))
    except DemoIterationError as error:
        _handle_demo_error(error)


@router.get("/{iteration_id}/reports", response_model=IterationReportsResponse)
async def get_iteration_reports(iteration_id: str) -> IterationReportsResponse:
    try:
        return IterationReportsResponse(**_demo_runner().get_reports(iteration_id))
    except DemoIterationError as error:
        _handle_demo_error(error)


@router.get("/{iteration_id}/reports/{report_type}", response_model=IterationReportResponse)
async def get_iteration_report(iteration_id: str, report_type: str) -> IterationReportResponse:
    try:
        return IterationReportResponse(**_demo_runner().get_report(iteration_id, report_type))
    except DemoIterationError as error:
        _handle_demo_error(error)


@router.get("/{iteration_id}/reports/{report_type}/download")
async def download_iteration_report(iteration_id: str, report_type: str) -> FileResponse:
    try:
        payload = _demo_runner().get_report(iteration_id, report_type)
        path = Path(payload["path"])
        if not path.exists():
            raise DemoIterationError(
                f"{report_type} report file is missing",
                status_code=404,
            )
        return FileResponse(
            path=path,
            media_type="application/json",
            filename=f"{iteration_id}_{payload['report_type']}.json",
        )
    except DemoIterationError as error:
        _handle_demo_error(error)


@router.post("/trigger", response_model=TriggerResponse)
async def trigger_iteration(
    request: TriggerRequest,
    _: None = Depends(require_admin_token),
) -> TriggerResponse:
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
    replay_service = DemoReplayService()
    last_demo_replay = _iteration_state.get("last_demo_replay") or replay_service.latest_run()
    latest_iteration = replay_service.latest_iteration_record()

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
        data_source=replay_service.data_source.describe(),
        last_demo_replay=last_demo_replay,
        latest_iteration=latest_iteration,
    )


@router.get("/{iteration_id}", response_model=IterationRecordResponse)
async def get_iteration_record(iteration_id: str) -> IterationRecordResponse:
    """
    查询指定迭代记录。
    """
    record = DemoReplayService().get_iteration_record(iteration_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"iteration record not found: {iteration_id}")
    return IterationRecordResponse(**record)


@router.post("/approve", response_model=ApproveResponse)
async def approve(
    request: ApproveRequest,
    _: None = Depends(require_admin_token),
) -> ApproveResponse:
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
async def canary(
    request: CanaryRequest,
    _: None = Depends(require_admin_token),
) -> CanaryResponse:
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
    _: None = Depends(require_admin_token),
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
