"""
FastAPI 依赖注入与资源工厂

集中管理模型、流水线、工作流等重量级单例，避免在 router 中散落全局变量。
"""

import os
from functools import lru_cache
from typing import Dict, Optional

from agent.workflow import DecisionWorkflow
from api.interfaces import FeaturePipeline, RiskPredictor
from data.preprocessor import FeatureEngineeringPipeline
from harness.knowledge_base import KnowledgeBaseManager
from harness.memory import HybridMemoryManager
from harness.validation import ValidationPipeline
from model.stacking import StackingRiskModel
from utils.config import get_config
from utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_SCENARIO_ID = "chemical"


class ResourceRegistry:
  """应用级资源注册表（懒加载单例容器）。

  Attributes:
      model: 堆叠风险预测模型。
      pipeline: 特征工程流水线。
      memory: 混合记忆管理器。
      validator: 决策校验流水线。
      workflows: 按场景缓存的决策工作流实例。
      default_scenario_id: 默认场景 ID。
  """

  def __init__(self) -> None:
    self._model: Optional[StackingRiskModel] = None
    self._pipeline: Optional[FeatureEngineeringPipeline] = None
    self._memory: Optional[HybridMemoryManager] = None
    self._validator: Optional[ValidationPipeline] = None
    self._workflows: Dict[str, DecisionWorkflow] = {}
    self.default_scenario_id: str = DEFAULT_SCENARIO_ID

  def get_model(self) -> StackingRiskModel:
    """获取或懒加载堆叠模型。

    Returns:
        已加载或新实例化的 ``StackingRiskModel``。

    Raises:
        FileNotFoundError: 配置的模型路径不存在。
        RuntimeError: 模型文件存在但反序列化失败，单例会被重置以便下次重试。
    """
    if self._model is None:
      config = get_config()
      model_path = config.model.stacking.model_path
      candidate = StackingRiskModel()
      if not os.path.exists(model_path):
        raise FileNotFoundError(f"模型文件不存在: {model_path}，请先训练或检查 config.model.stacking.model_path")
      try:
        candidate.load(model_path)
      except Exception as exc:
        logger.error("模型加载失败 (%s): %s", model_path, exc)
        raise RuntimeError(f"模型加载失败: {exc}") from exc
      self._model = candidate
    return self._model

  def get_pipeline(self) -> FeatureEngineeringPipeline:
    """获取或懒加载特征工程流水线。

    Raises:
        FileNotFoundError: 配置的流水线路径不存在。
        RuntimeError: 文件存在但反序列化失败。
    """
    if self._pipeline is None:
      config = get_config()
      pipeline_path = config.model.stacking.pipeline_path
      candidate = FeatureEngineeringPipeline()
      if not os.path.exists(pipeline_path):
        raise FileNotFoundError(f"Pipeline 文件不存在: {pipeline_path}")
      try:
        candidate.load(pipeline_path)
      except Exception as exc:
        logger.error("Pipeline 加载失败 (%s): %s", pipeline_path, exc)
        raise RuntimeError(f"Pipeline 加载失败: {exc}") from exc
      self._pipeline = candidate
    return self._pipeline

  def get_memory(self) -> HybridMemoryManager:
    """获取混合记忆管理器单例。"""
    if self._memory is None:
      self._memory = HybridMemoryManager()
    return self._memory

  def get_validator(self) -> ValidationPipeline:
    """获取决策校验流水线单例。"""
    if self._validator is None:
      self._validator = ValidationPipeline()
    return self._validator

  def get_workflow(self, scenario_id: str = DEFAULT_SCENARIO_ID) -> DecisionWorkflow:
    """按场景获取决策工作流（缓存复用）。

    Args:
        scenario_id: 场景标识。

    Returns:
        对应场景的 ``DecisionWorkflow`` 实例。
    """
    if scenario_id not in self._workflows:
      self._workflows[scenario_id] = DecisionWorkflow(scenario_id=scenario_id)
    return self._workflows[scenario_id]

  def set_default_scenario(self, scenario_id: str) -> None:
    """更新默认场景 ID。

    Args:
        scenario_id: 新的默认场景。
    """
    self.default_scenario_id = scenario_id


@lru_cache(maxsize=1)
def get_registry() -> ResourceRegistry:
  """获取全局资源注册表单例。

  Returns:
      进程内共享的 ``ResourceRegistry``。
  """
  return ResourceRegistry()


def get_risk_model() -> RiskPredictor:
  """FastAPI 依赖：风险预测模型。"""
  return get_registry().get_model()


def get_feature_pipeline() -> FeaturePipeline:
  """FastAPI 依赖：特征工程流水线。"""
  return get_registry().get_pipeline()


def get_knowledge_repository() -> KnowledgeBaseManager:
  """FastAPI 依赖：知识库管理器（每次新建以支持热更新）。"""
  return KnowledgeBaseManager()


def mock_fallback_enabled() -> bool:
  """是否允许决策失败时降级为 Mock 数据。

  Returns:
      当环境变量 ``MRA_ENABLE_MOCK_FALLBACK`` 为 true/1/on 时返回 True。
  """
  return os.getenv("MRA_ENABLE_MOCK_FALLBACK", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
  }
