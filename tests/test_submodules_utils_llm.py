"""
工具与 LLM 客户端子模块测试。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mining_risk_serve.llm.glm5_client import GLM5Client, OpenAICompatibleClient
from mining_risk_common.utils.config import PROJECT_ROOT, resolve_project_path
from mining_risk_common.utils.exceptions import (
    AgentFSError,
    AuditLogError,
    DataLoadingError,
    DataValidationError,
    FeatureEngineeringError,
    HighRiskBlockedError,
    KnowledgeBaseError,
    MemoryManagerError,
    MiningRiskAgentException,
    ModelInferenceError,
    ModelIterationError,
    ModelTrainingError,
    MonteCarloValidationError,
    ValidationError,
)


class TestResolveProjectPath:
    def test_absolute_passthrough(self, tmp_path):
        p = tmp_path / "abs.txt"
        p.write_text("x", encoding="utf-8")
        assert resolve_project_path(p) == p.resolve()

    def test_relative_joins_project_root(self):
        rel = resolve_project_path("config.yaml")
        assert rel.is_absolute()
        assert rel.name == "config.yaml"
        assert rel.parent == PROJECT_ROOT


class TestExceptionHierarchy:
    @pytest.mark.parametrize(
        "cls",
        [
            DataLoadingError,
            DataValidationError,
            FeatureEngineeringError,
            ModelTrainingError,
            ModelInferenceError,
            KnowledgeBaseError,
            AgentFSError,
            MemoryManagerError,
            ValidationError,
            MonteCarloValidationError,
            HighRiskBlockedError,
            ModelIterationError,
            AuditLogError,
        ],
    )
    def test_domain_exceptions_subclass_base(self, cls):
        assert issubclass(cls, MiningRiskAgentException)
        e = cls("msg")
        assert str(e) == "msg"


class TestOpenAICompatibleClient:
    def test_init_accepts_explicit_and_env_key(self, monkeypatch):
        monkeypatch.setenv("GLM5_API_KEY", "from-env")
        c = OpenAICompatibleClient(
            api_key=None,
            base_url="https://example.com/v1/",
            model="m1",
            api_key_env="GLM5_API_KEY",
        )
        assert c.model == "m1"
        assert "example.com" in c.base_url
        assert c.api_key == "from-env"

    def test_glm5_client_is_alias(self):
        assert GLM5Client is OpenAICompatibleClient
