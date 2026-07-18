from pathlib import Path
from forge.config import Settings, get_settings

def test_defaults():
    s = Settings(_env_file=None)
    assert s.model == "claude-opus-4-8"
    assert s.effort == "high"
    assert s.max_review_rounds == 8
    assert s.output_dir == Path("output/roteiros")

def test_env_prefix(monkeypatch):
    monkeypatch.setenv("FORGE_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("FORGE_MAX_REVIEW_ROUNDS", "3")
    s = Settings(_env_file=None)
    assert s.model == "claude-sonnet-5"
    assert s.max_review_rounds == 3

def test_api_key_fallback(monkeypatch):
    monkeypatch.delenv("FORGE_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    s = Settings(_env_file=None)
    assert s.anthropic_api_key == "sk-test"

def test_get_settings_cached():
    assert get_settings() is get_settings()
