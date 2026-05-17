"""
审计日志 API 契约模型
"""

from typing import Optional

from pydantic import BaseModel, Field


class AuditLogRequest(BaseModel):
  """审计日志写入请求。"""

  event_type: str = Field(..., min_length=1, description="事件类型")
  agent_id: Optional[str] = None
  enterprise_id: Optional[str] = None
  details: Optional[str] = None
  risk_level: Optional[str] = None
  validation_status: Optional[str] = None


class AuditLogEntry(BaseModel):
  """审计日志查询条目。"""

  id: int
  timestamp: float
  event_type: str
  agent_id: Optional[str] = None
  enterprise_id: Optional[str] = None
  details: Optional[str] = None
  risk_level: Optional[str] = None
  validation_status: Optional[str] = None
