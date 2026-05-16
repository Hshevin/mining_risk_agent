"""
API 子模块综合测试：统一契约、依赖注册表、安全中间件、业务服务层。
"""

from __future__ import annotations

import os
from typing import List, Optional
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from api.exception_handlers import register_exception_handlers
from api.schemas.common import ApiResponse, ErrorDetail, HealthPayload, PaginatedData, fail, ok
from api.schemas.knowledge import KnowledgeAppendRequest, KnowledgeUpdateRequest
from api.schemas.prediction import (
    VALID_SCENARIO_IDS,
    DecisionRequest,
    LLMUpdateRequest,
    PredictRequest,
)
from api.security import require_admin_token
from api.services.dependencies import ResourceRegistry, mock_fallback_enabled
from api.services.knowledge_service import KnowledgeService
from api.services.prediction_service import PredictionService
from utils.exceptions import DataValidationError, KnowledgeBaseError, MiningRiskAgentException


# ---------------------------------------------------------------------------
# Schemas: common + prediction
# ---------------------------------------------------------------------------


class TestApiSchemasCommon:
    def test_ok_envelope(self):
        r = ok({"x": 1}, message="m")
        assert r.success is True
        assert r.data == {"x": 1}
        assert r.message == "m"
        assert r.error is None

    def test_fail_envelope(self):
        r = fail("E", "msg", field="f")
        assert r.success is False
        assert isinstance(r.error, ErrorDetail)
        assert r.error.code == "E"
        assert r.error.message == "msg"
        assert r.error.field == "f"

    def test_paginated_data_bounds(self):
        p = PaginatedData(total=100, items=[1, 2], offset=0, limit=10)
        assert p.total == 100
        assert len(p.items) == 2

    def test_health_payload(self):
        h = HealthPayload(status="healthy", version="1.0.0")
        assert h.status == "healthy"

    def test_predict_request_rejects_empty_enterprise_id(self):
        with pytest.raises(Exception):
            PredictRequest(enterprise_id="", data={})

    def test_valid_scenario_ids(self):
        assert VALID_SCENARIO_IDS == frozenset({"chemical", "metallurgy", "dust"})


# ---------------------------------------------------------------------------
# Security: admin token
# ---------------------------------------------------------------------------


class TestApiSecurity:
    @pytest.mark.asyncio
    async def test_require_admin_allow_unauthenticated(self, monkeypatch):
        monkeypatch.delenv("MRA_ADMIN_TOKEN", raising=False)
        monkeypatch.setenv("MRA_ALLOW_UNAUTHENTICATED_ADMIN", "true")
        await require_admin_token(None)

    @pytest.mark.asyncio
    async def test_require_admin_missing_token_returns_503(self, monkeypatch):
        monkeypatch.delenv("MRA_ADMIN_TOKEN", raising=False)
        monkeypatch.delenv("MRA_ALLOW_UNAUTHENTICATED_ADMIN", raising=False)
        with pytest.raises(HTTPException) as ei:
            await require_admin_token(None)
        assert ei.value.status_code == 503

    @pytest.mark.asyncio
    async def test_require_admin_digest_mismatch(self, monkeypatch):
        monkeypatch.setenv("MRA_ADMIN_TOKEN", "secret-token")
        monkeypatch.delenv("MRA_ALLOW_UNAUTHENTICATED_ADMIN", raising=False)
        with pytest.raises(HTTPException) as ei:
            await require_admin_token("wrong")
        assert ei.value.status_code == 401

    @pytest.mark.asyncio
    async def test_require_admin_success(self, monkeypatch):
        monkeypatch.setenv("MRA_ADMIN_TOKEN", "secret-token")
        await require_admin_token("secret-token")


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------


class TestExceptionHandlers:
    def test_mining_risk_agent_exception_maps_400(self):
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/x")
        def _route():
            raise DataValidationError("bad input")

        client = TestClient(app)
        resp = client.get("/x")
        assert resp.status_code == 400
        body = resp.json()
        assert body["success"] is False
        assert body["error"]["code"] == "DataValidationError"
        assert "bad input" in body["error"]["message"]

    def test_subclass_still_mining_exception(self):
        assert issubclass(DataValidationError, MiningRiskAgentException)


# ---------------------------------------------------------------------------
# ResourceRegistry & mock_fallback
# ---------------------------------------------------------------------------


class TestDependencies:
    def test_mock_fallback_enabled_truthy(self, monkeypatch):
        monkeypatch.setenv("MRA_ENABLE_MOCK_FALLBACK", "1")
        assert mock_fallback_enabled() is True
        monkeypatch.setenv("MRA_ENABLE_MOCK_FALLBACK", "false")
        assert mock_fallback_enabled() is False

    def test_resource_registry_default_scenario(self):
        reg = ResourceRegistry()
        assert reg.default_scenario_id == "chemical"
        reg.set_default_scenario("dust")
        assert reg.default_scenario_id == "dust"

    def test_resource_registry_workflow_cache(self):
        reg = ResourceRegistry()
        w1 = reg.get_workflow("chemical")
        w2 = reg.get_workflow("chemical")
        assert w1 is w2
        w3 = reg.get_workflow("metallurgy")
        assert w3 is not w1


# ---------------------------------------------------------------------------
# PredictionService
# ---------------------------------------------------------------------------


class _FakeModel:
    def predict(self, features):
        return {
            "predicted_level": "黄",
            "probability_distribution": {"蓝": 0.1, "黄": 0.7, "橙": 0.15, "红": 0.05},
            "shap_contributions": [{"feature": "x", "value": 1.0}],
        }

    def load(self, path: str) -> None:
        pass


class _FakePipeline:
    def transform(self, df):
        return df

    def load(self, path: str) -> None:
        pass


class _FakeValidator:
    def run(self, decision):
        return {"pass": True, "detail": "ok"}


class TestPredictionService:
    def test_resolve_scenario_from_request_field(self):
        reg = ResourceRegistry()
        reg.set_default_scenario("chemical")
        svc = PredictionService(reg)
        rid = svc.resolve_scenario_id(
            DecisionRequest(enterprise_id="E1", data={}, scenario_id="metallurgy")
        )
        assert rid == "metallurgy"

    def test_resolve_scenario_from_data_dict(self):
        reg = ResourceRegistry()
        reg.set_default_scenario("chemical")
        svc = PredictionService(reg)
        rid = svc.resolve_scenario_id(
            DecisionRequest(enterprise_id="E1", data={"scenario_id": "dust"})
        )
        assert rid == "dust"

    def test_resolve_scenario_invalid_raises_400(self):
        svc = PredictionService(ResourceRegistry())
        with pytest.raises(HTTPException) as ei:
            svc.resolve_scenario_id(
                DecisionRequest(enterprise_id="E1", data={}, scenario_id="unknown")
            )
        assert ei.value.status_code == 400

    def test_predict_with_injected_fakes(self):
        reg = ResourceRegistry()
        svc = PredictionService(reg)
        req = PredictRequest(
            enterprise_id="E-UNIT",
            data={"enterprise_name": "测试企业", "region_code": "110000"},
        )
        out = svc.predict(
            req,
            model=_FakeModel(),
            pipeline=_FakePipeline(),
            validator=_FakeValidator(),
        )
        assert out.enterprise_id == "E-UNIT"
        assert out.predicted_level == "黄"
        assert out.validation_result is not None
        assert out.suggestions is not None

    def test_query_history_placeholder(self):
        svc = PredictionService(ResourceRegistry())
        rows = svc.query_history("E99", "橙")
        assert len(rows) == 1
        assert rows[0]["enterprise_id"] == "E99"
        assert rows[0]["risk_level"] == "橙"

    def test_fallback_mock_decision_shape(self):
        d = PredictionService._fallback_mock_decision("ent-1", "chemical")
        assert d["enterprise_id"] == "ent-1"
        assert d["scenario_id"] == "chemical"
        assert "predicted_level" in d
        assert "probability_distribution" in d

    def test_get_llm_config_shape(self):
        svc = PredictionService(ResourceRegistry())
        cfg = svc.get_llm_config("ok")
        assert cfg.provider
        assert isinstance(cfg.has_api_key, bool)
        assert isinstance(cfg.available_providers, list)


class TestPredictionServiceLlmUpdate:
    """会修改进程内全局配置对象，串行测试下在末尾做并恢复。"""

    def test_update_llm_config_sets_active_provider(self):
        from utils.config import get_config

        app_cfg = get_config()
        prev_provider = app_cfg.llm.provider
        prev_keys = list(app_cfg.llm.providers.keys())
        svc = PredictionService(ResourceRegistry())
        try:
            resp = svc.update_llm_config(
                LLMUpdateRequest(provider="glm5", model="glm-5", base_url="https://example.invalid/v1/")
            )
            assert resp.provider == "glm5"
            assert app_cfg.llm.provider == "glm5"
            active = app_cfg.llm.active
            assert active.model == "glm-5"
        finally:
            app_cfg.llm.provider = prev_provider
            for k in list(app_cfg.llm.providers.keys()):
                if k not in prev_keys and k not in {"glm5", "deepseek"}:
                    del app_cfg.llm.providers[k]


# ---------------------------------------------------------------------------
# KnowledgeService + fake repository
# ---------------------------------------------------------------------------


class _FakeKnowledgeRepo:
    def __init__(self) -> None:
        self._files: dict[str, str] = {"demo.md": "# hello"}

    def list_files(self) -> List[str]:
        return sorted(self._files)

    def read(self, filename: str) -> str:
        if filename not in self._files:
            raise FileNotFoundError(filename)
        return self._files[filename]

    def write(self, filename: str, content: str, agent_id: Optional[str] = None) -> None:
        self._files[filename] = content

    def append(self, filename: str, content: str, agent_id: Optional[str] = None) -> None:
        self._files[filename] = self._files.get(filename, "") + content

    def snapshot(self, commit_message: str, agent_id: Optional[str] = None) -> str:
        return "commit-abc"

    def rollback(self, commit_id: str) -> None:
        if commit_id != "commit-abc":
            raise KnowledgeBaseError("bad commit")


class TestKnowledgeService:
    def test_list_and_read(self):
        svc = KnowledgeService(repository=_FakeKnowledgeRepo())
        assert "demo.md" in svc.list_files()
        content = svc.read_file("demo.md")
        assert content.content.startswith("# hello")

    def test_read_missing_returns_404(self):
        svc = KnowledgeService(repository=_FakeKnowledgeRepo())
        with pytest.raises(HTTPException) as ei:
            svc.read_file("nope.md")
        assert ei.value.status_code == 404

    def test_write_append_snapshot_rollback(self):
        repo = _FakeKnowledgeRepo()
        svc = KnowledgeService(repository=repo)
        svc.write_file(
            KnowledgeUpdateRequest(filename="n.md", content="A", agent_id="agent")
        )
        assert repo._files["n.md"] == "A"
        svc.append_file(KnowledgeAppendRequest(filename="n.md", content="B", agent_id="agent"))
        assert repo._files["n.md"] == "AB"
        snap = svc.snapshot("msg", agent_id="agent")
        assert snap.commit_id == "commit-abc"
        rb = svc.rollback("commit-abc")
        assert rb.status == "success"

    def test_write_knowledge_base_error_maps_400(self):
        class BadRepo(_FakeKnowledgeRepo):
            def write(self, filename: str, content: str, agent_id: Optional[str] = None) -> None:
                raise KnowledgeBaseError("sandbox")

        svc = KnowledgeService(repository=BadRepo())
        with pytest.raises(HTTPException) as ei:
            svc.write_file(KnowledgeUpdateRequest(filename="x.md", content="z"))
        assert ei.value.status_code == 400

