from pathlib import Path

import pytest

from forge.infrastructure.config import Settings, get_settings

def test_defaults():
    s = Settings(_env_file=None)
    assert s.resolved_model == "claude-opus-4-8"
    assert s.effort == "high"
    assert s.max_review_rounds == 8
    assert s.output_dir == Path("output/roteiros")

def test_env_prefix(monkeypatch):
    monkeypatch.setenv("FORGE_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("FORGE_MAX_REVIEW_ROUNDS", "3")
    s = Settings(_env_file=None)
    assert s.resolved_model == "claude-sonnet-5"
    assert s.max_review_rounds == 3

def test_api_key_fallback(monkeypatch):
    monkeypatch.delenv("FORGE_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    s = Settings(_env_file=None)
    assert s.anthropic_api_key == "sk-test"

def test_get_settings_cached():
    assert get_settings() is get_settings()


def test_resolved_model_por_provider():
    """Sem override, cada provider usa o próprio default."""
    assert Settings(_env_file=None, provider="openai").resolved_model == "gpt-5-nano"
    assert Settings(_env_file=None, provider="lm-studio").resolved_model == "qwen/qwen3.5-9b"


def test_model_override_vence_em_qualquer_provider(monkeypatch):
    monkeypatch.setenv("FORGE_MODEL", "gpt-5")
    assert Settings(_env_file=None, provider="openai").resolved_model == "gpt-5"


def test_resolved_api_key_nao_cruza_provider(monkeypatch):
    """Chave Anthropic nunca pode ser enviada à OpenAI."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("FORGE_OPENAI_API_KEY", raising=False)
    s = Settings(_env_file=None, provider="openai", anthropic_api_key="sk-ant")
    assert s.resolved_api_key is None


def test_resolved_api_key_por_provider():
    s = Settings(_env_file=None, anthropic_api_key="sk-ant", openai_api_key="sk-oai")
    assert s.resolved_api_key == "sk-ant"
    assert s.model_copy(update={"provider": "openai"}).resolved_api_key == "sk-oai"


def test_api_key_generica_vence(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    s = Settings(_env_file=None, api_key="sk-generica", anthropic_api_key="sk-ant")
    assert s.resolved_api_key == "sk-generica"


def test_lm_studio_dispensa_chave():
    assert Settings(_env_file=None, provider="lm-studio").resolved_api_key == "lm-studio"


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_chave_faltando_falha_claro(monkeypatch, provider):
    for var in ("ANTHROPIC_API_KEY", "FORGE_ANTHROPIC_API_KEY",
                "OPENAI_API_KEY", "FORGE_OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    s = Settings(_env_file=None, provider=provider)
    with pytest.raises(ValueError, match="API key ausente"):
        s.exigir_api_key()
