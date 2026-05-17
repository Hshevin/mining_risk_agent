"""LLM provider 配置测试。"""

from mining_risk_common.utils.config import LLMConfig, LLMProviderConfig


def test_llm_config_defaults_to_glm5():
    cfg = LLMConfig(
        providers={
            "glm5": LLMProviderConfig(model="glm-5", base_url="https://example.com/v1")
        }
    )

    assert cfg.provider == "glm5"
    assert cfg.active.model == "glm-5"


def test_llm_config_selects_custom_provider_from_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "custom-openai")
    monkeypatch.setenv("LLM_CUSTOM_OPENAI_API_KEY", "test-custom-key")
    monkeypatch.setenv("LLM_CUSTOM_OPENAI_MODEL", "custom-model")

    cfg = LLMConfig(
        providers={
            "custom-openai": LLMProviderConfig(
                model="default-model",
                base_url="https://example.com/v1",
            )
        }
    )

    assert cfg.provider == "custom-openai"
    assert cfg.active.api_key == "test-custom-key"
    assert cfg.active.model == "custom-model"


def test_llm_config_creates_unknown_provider_from_generic_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "unknown")
    monkeypatch.setenv("LLM_MODEL", "runtime-model")
    monkeypatch.setenv("LLM_BASE_URL", "https://runtime.example/v1")

    cfg = LLMConfig()

    assert cfg.provider == "unknown"
    assert cfg.active.model == "runtime-model"
    assert cfg.active.base_url == "https://runtime.example/v1"
