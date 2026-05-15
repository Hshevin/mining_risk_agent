"""
风险预测与决策智能体 API 契约模型
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PredictRequest(BaseModel):
  """传统风险预测请求。

  Attributes:
      enterprise_id: 企业唯一标识，不可为空。
      data: 企业特征字段键值对。
  """

  enterprise_id: str = Field(..., min_length=1, description="企业 ID")
  data: Dict[str, Any] = Field(default_factory=dict, description="企业特征数据")


class PredictResponse(BaseModel):
  """传统风险预测响应。"""

  enterprise_id: str
  predicted_level: str
  probability_distribution: Dict[str, float]
  shap_contributions: List[Dict[str, Any]]
  validation_result: Optional[Dict[str, Any]] = None
  suggestions: Optional[Dict[str, Any]] = None


class QueryRequest(BaseModel):
  """预警历史查询条件。"""

  enterprise_id: Optional[str] = None
  start_time: Optional[str] = None
  end_time: Optional[str] = None
  risk_level: Optional[str] = None


class DecisionRequest(BaseModel):
  """决策智能体工作流请求。

  Attributes:
      enterprise_id: 企业唯一标识。
      data: 原始企业数据。
      scenario_id: 场景 ID，可选；缺省时从 ``data.scenario_id`` 或默认场景推断。
  """

  enterprise_id: str = Field(..., min_length=1, description="企业 ID")
  data: Dict[str, Any] = Field(default_factory=dict, description="企业原始数据")
  scenario_id: Optional[str] = Field(default=None, description="场景: chemical/metallurgy/dust")


class DecisionResponse(BaseModel):
  """决策智能体完整响应。"""

  enterprise_id: str
  scenario_id: str
  final_status: str
  predicted_level: str
  probability_distribution: Dict[str, float]
  shap_contributions: List[Dict[str, Any]]
  risk_level_and_attribution: Dict[str, Any] = Field(default_factory=dict)
  government_intervention: Dict[str, Any] = Field(default_factory=dict)
  enterprise_control: Dict[str, Any] = Field(default_factory=dict)
  march_result: Optional[Dict[str, Any]] = None
  monte_carlo_result: Optional[Dict[str, Any]] = None
  three_d_risk: Optional[Dict[str, Any]] = None
  node_status: List[Dict[str, Any]] = Field(default_factory=list)
  mock: bool = Field(default=False, description="是否为演示降级数据")


class DecisionStreamMessage(BaseModel):
  """SSE 流式决策节点状态消息。"""

  node: str
  status: str
  timestamp: Optional[float] = None
  detail: Optional[str] = None
  final_status: Optional[str] = None
  predicted_level: Optional[str] = None
  error: Optional[str] = None
  mock: bool = False
  decision_response: Optional[DecisionResponse] = None


class ScenarioSwitchResponse(BaseModel):
  """场景切换响应。"""

  scenario_id: str
  scenario_name: str
  message: str
  confidence_threshold: float
  risk_threshold: float
  checker_strictness: str
  memory_top_k: int


class LLMConfigResponse(BaseModel):
  """LLM 运行时配置响应。"""

  provider: str
  model: str
  base_url: str
  default_temperature: float
  default_max_tokens: int
  max_retries: int
  has_api_key: bool
  available_providers: List[str] = Field(default_factory=list)
  message: str = ""


class LLMUpdateRequest(BaseModel):
  """LLM 配置更新请求。"""

  provider: str = Field(..., min_length=1, description="提供方标识")
  model: Optional[str] = None
  base_url: Optional[str] = None
  api_key: Optional[str] = None
  api_key_env: Optional[str] = None
  default_temperature: Optional[float] = None
  default_max_tokens: Optional[int] = None
  max_retries: Optional[int] = None


VALID_SCENARIO_IDS = frozenset({"chemical", "metallurgy", "dust"})
