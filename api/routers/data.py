"""
数据管理路由
支持批量/单条企业数据上传
"""

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from data.loader import DataLoader, DataUploadRequest
from utils.config import resolve_project_path
from utils.exceptions import DataLoadingError
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()
UPLOAD_DIR = resolve_project_path("data/uploads")


class DataUploadResponse(BaseModel):
    success: bool
    message: str
    rows: int = 0
    columns: int = 0
    preview: Optional[List[Dict[str, Any]]] = None
    saved_path: Optional[str] = None
    record_path: Optional[str] = None
    checksum: Optional[str] = None
    bytes: int = 0
    persisted: bool = False
    record_count: int = 0


class BatchUploadRequest(BaseModel):
    records: List[Dict[str, Any]]
    enterprise_id: Optional[str] = None


def _safe_filename(filename: str) -> str:
    stem = Path(filename or "upload").stem
    suffix = Path(filename or "").suffix.lower()
    safe_stem = re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff]+", "_", stem).strip("._")
    return f"{safe_stem or 'upload'}{suffix if suffix else '.csv'}"


def _data_format_from_filename(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return "excel"
    if suffix == ".json":
        return "json"
    return "csv"


def _persist_upload_bytes(content: bytes, filename: str, enterprise_id: str) -> Dict[str, Any]:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    checksum = hashlib.sha256(content).hexdigest()
    safe_name = _safe_filename(filename)
    safe_enterprise = re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff]+", "_", enterprise_id).strip("._") or "unknown"
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    upload_path = UPLOAD_DIR / f"upload_{timestamp}_{checksum[:10]}_{safe_enterprise}_{safe_name}"
    upload_path.write_bytes(content)
    stored = upload_path.read_bytes()
    stored_checksum = hashlib.sha256(stored).hexdigest()
    if stored_checksum != checksum or len(stored) != len(content):
        raise DataLoadingError("上传文件持久化校验失败：checksum 或 size 不一致")
    return {"path": upload_path, "checksum": checksum, "bytes": len(stored)}


def _persist_records(df: pd.DataFrame, upload_path: Path) -> Path:
    record_path = upload_path.with_suffix(upload_path.suffix + ".records.jsonl")
    df.to_json(record_path, orient="records", lines=True, force_ascii=False)
    if not record_path.exists() or (record_path.stat().st_size == 0 and len(df) > 0):
        raise DataLoadingError("规范化记录持久化校验失败")
    return record_path


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(resolve_project_path(".")))
    except ValueError:
        return str(path)


@router.post("/upload", response_model=DataUploadResponse)
async def upload_data(
    file: UploadFile = File(...),
    enterprise_id: Optional[str] = Form(None),
) -> DataUploadResponse:
    """上传数据文件（CSV/Excel/JSON）"""
    try:
        content = await file.read()
        enterprise = enterprise_id or "unknown"
        persisted = _persist_upload_bytes(content, file.filename or "upload.csv", enterprise)
        fmt = _data_format_from_filename(file.filename or "")
        
        request = DataUploadRequest(
            enterprise_id=enterprise,
            data_format=fmt,
            content=content,
        )
        
        loader = DataLoader()
        df = loader.load_from_api(request)
        record_path = _persist_records(df, persisted["path"])
        
        preview = df.head(5).to_dict(orient="records") if len(df) > 0 else None
        
        return DataUploadResponse(
            success=True,
            message="上传成功，文件已持久化",
            rows=len(df),
            columns=len(df.columns),
            preview=preview,
            saved_path=_display_path(persisted["path"]),
            record_path=_display_path(record_path),
            checksum=persisted["checksum"],
            bytes=persisted["bytes"],
            persisted=True,
            record_count=len(df),
        )
    except Exception as e:
        logger.error(f"数据上传失败: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/upload/batch", response_model=DataUploadResponse)
async def upload_batch(request: BatchUploadRequest) -> DataUploadResponse:
    """批量上传企业数据（JSON 格式）"""
    try:
        df = pd.DataFrame(request.records)
        enterprise = request.enterprise_id or "unknown"
        raw = json.dumps(request.records, ensure_ascii=False).encode("utf-8")
        persisted = _persist_upload_bytes(raw, "batch.json", enterprise)
        record_path = _persist_records(df, persisted["path"])
        return DataUploadResponse(
            success=True,
            message="批量上传成功，记录已持久化",
            rows=len(df),
            columns=len(df.columns),
            preview=df.head(5).to_dict(orient="records"),
            saved_path=_display_path(persisted["path"]),
            record_path=_display_path(record_path),
            checksum=persisted["checksum"],
            bytes=persisted["bytes"],
            persisted=True,
            record_count=len(df),
        )
    except Exception as e:
        logger.error(f"批量上传失败: {e}")
        raise HTTPException(status_code=400, detail=str(e))
