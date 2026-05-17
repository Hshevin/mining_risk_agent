"""
API 层统一 Schema / DTO 导出。

路由层应从此包导入请求/响应模型，避免在 router 中重复定义。
"""

from mining_risk_serve.api.schemas.audit import AuditLogEntry, AuditLogRequest
from mining_risk_serve.api.schemas.common import (
  ApiResponse,
  ErrorDetail,
  HealthPayload,
  PaginatedData,
  PaginatedResponse,
  fail,
  ok,
)
from mining_risk_serve.api.schemas.data import BatchUploadRequest, DataUploadResponse
from mining_risk_serve.api.schemas.knowledge import (
  KnowledgeAppendRequest,
  KnowledgeFileContent,
  KnowledgeMutationResponse,
  KnowledgeUpdateRequest,
)
from mining_risk_serve.api.schemas.prediction import (
  VALID_SCENARIO_IDS,
  DecisionRequest,
  DecisionResponse,
  DecisionStreamMessage,
  LLMConfigResponse,
  LLMUpdateRequest,
  PredictRequest,
  PredictResponse,
  QueryRequest,
  ScenarioSwitchResponse,
)

__all__ = [
  "ApiResponse",
  "ErrorDetail",
  "HealthPayload",
  "PaginatedData",
  "PaginatedResponse",
  "ok",
  "fail",
  "PredictRequest",
  "PredictResponse",
  "QueryRequest",
  "DecisionRequest",
  "DecisionResponse",
  "DecisionStreamMessage",
  "ScenarioSwitchResponse",
  "LLMConfigResponse",
  "LLMUpdateRequest",
  "VALID_SCENARIO_IDS",
  "KnowledgeUpdateRequest",
  "KnowledgeAppendRequest",
  "KnowledgeFileContent",
  "KnowledgeMutationResponse",
  "DataUploadResponse",
  "BatchUploadRequest",
  "AuditLogRequest",
  "AuditLogEntry",
]
