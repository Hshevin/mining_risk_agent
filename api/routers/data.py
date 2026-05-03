"""
数据管理路由
支持批量/单条企业数据上传
"""

import io
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from data.loader import DataLoader, DataUploadRequest
from utils.config import get_config
from utils.exceptions import DataLoadingError
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


class DataUploadResponse(BaseModel):
    success: bool
    message: str
    rows: int = 0
    columns: int = 0
    preview: Optional[List[Dict[str, Any]]] = None


class BatchUploadRequest(BaseModel):
    records: List[Dict[str, Any]]
    enterprise_id: Optional[str] = None


@router.post("/upload", response_model=DataUploadResponse)
async def upload_data(
    file: UploadFile = File(...),
    enterprise_id: Optional[str] = Form(None),
) -> DataUploadResponse:
    """上传数据文件（CSV/Excel/JSON）"""
    try:
        content = await file.read()
        fmt = file.filename.split(".")[-1].lower()
        
        request = DataUploadRequest(
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
    except Exception as e:
        logger.error(f"数据上传失败: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/upload/batch", response_model=DataUploadResponse)
async def upload_batch(request: BatchUploadRequest) -> DataUploadResponse:
    """批量上传企业数据（JSON 格式）"""
    try:
        df = pd.DataFrame(request.records)
        return DataUploadResponse(
            success=True,
            message="批量上传成功",
            rows=len(df),
            columns=len(df.columns),
            preview=df.head(5).to_dict(orient="records"),
        )
    except Exception as e:
        logger.error(f"批量上传失败: {e}")
        raise HTTPException(status_code=400, detail=str(e))
