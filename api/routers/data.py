"""
数据管理路由
支持批量/单条企业数据上传
"""

import io
from typing import Optional

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from api.schemas.data import BatchUploadRequest, DataUploadResponse
from data.loader import DataLoader, DataUploadRequest as LoaderUploadRequest
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.post("/upload", response_model=DataUploadResponse)
async def upload_data(
    file: UploadFile = File(...),
    enterprise_id: Optional[str] = Form(None),
) -> DataUploadResponse:
    """上传数据文件（CSV/Excel/JSON）。"""
    try:
        content = await file.read()
        fmt = file.filename.split(".")[-1].lower()

        request = LoaderUploadRequest(
            enterprise_id=enterprise_id or "unknown",
            data_format=fmt if fmt in ("csv", "excel", "json") else "csv",
            content=content,
        )

        loader = DataLoader()
        df = loader.load_from_api(request)

        preview = df.head(5).to_dict(orient="records") if len(df) > 0 else None

        return DataUploadResponse(
            success=True,
            message="上传成功",
            rows=len(df),
            columns=len(df.columns),
            preview=preview,
        )
    except Exception as exc:
        logger.error("数据上传失败: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/upload/batch", response_model=DataUploadResponse)
async def upload_batch(request: BatchUploadRequest) -> DataUploadResponse:
    """批量上传企业数据（JSON 格式）。"""
    try:
        df = pd.DataFrame(request.records)
        return DataUploadResponse(
            success=True,
            message="批量上传成功",
            rows=len(df),
            columns=len(df.columns),
            preview=df.head(5).to_dict(orient="records"),
        )
    except Exception as exc:
        logger.error("批量上传失败: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
