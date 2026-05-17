"""业务服务层导出。"""

from mining_risk_serve.api.services.dependencies import (
    ResourceRegistry,
    get_feature_pipeline,
    get_knowledge_repository,
    get_registry,
    get_risk_model,
    mock_fallback_enabled,
)
from mining_risk_serve.api.services.knowledge_service import KnowledgeService, get_knowledge_service
from mining_risk_serve.api.services.prediction_service import PredictionService, get_prediction_service

__all__ = [
    "ResourceRegistry",
    "get_registry",
    "get_risk_model",
    "get_feature_pipeline",
    "get_knowledge_repository",
    "mock_fallback_enabled",
    "PredictionService",
    "get_prediction_service",
    "KnowledgeService",
    "get_knowledge_service",
]
