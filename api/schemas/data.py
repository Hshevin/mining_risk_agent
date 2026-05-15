"""
数据管理 API 契约模型
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DataUploadResponse(BaseModel):
  """数据上传响应。

  Attributes:
      success: 是否上传成功。
      message: 人类可读说明。
      rows: 解析得到的行数。
      columns: 列数。
      preview: 可选，前几行预览。
  """

  success: bool
  message: str
  rows: int = Field(default=0, ge=0)
  columns: int = Field(default=0, ge=0)
  preview: Optional[List[Dict[str, Any]]] = None


class BatchUploadRequest(BaseModel):
  """批量 JSON 上传请求。"""

  records: List[Dict[str, Any]] = Field(..., min_length=1, description="记录列表")
  enterprise_id: Optional[str] = Field(default=None, description="默认企业 ID")
