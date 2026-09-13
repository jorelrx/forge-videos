from pathlib import Path

import pytest

from forge.infrastructure.config import Settings, get_settings


def test_defaults():
    s = Settings(_env_file=None)
    assert s.resolved_model == "claude-opus-4-8"
    assert s.effort == "high"
    assert s.max_review_rounds == 8
    assert s.output_dir == Path("output/roteiros")


def test_studio_executor_defaults_are_canonical():
    s = Settings(_env_file=None)

    assert s.studio_runs_dir == Path("output/runs")
    assert s.research_min_sources == 3


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


def test_secret_values_exposes_configured_provider_keys_for_redaction():
    s = Settings(
        _env_file=None,
        api_key="sk-generic",
        anthropic_api_key="sk-anthropic",
        openai_api_key="sk-openai",
    )

    assert s.secret_values() == ["sk-generic", "sk-anthropic", "sk-openai"]


def test_get_settings_cached():
    assert get_settings() is get_settings()


def test_resolved_model_por_provider():
    """Sem override, cada provider usa o próprio default."""
    assert Settings(_env_file=None, provider="openai").resolved_model == "gpt-5-nano"
    assert Settings(_env_file=None, provider="lm-studio").resolved_model == "google/gemma-4-e4b"


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


def test_acervo_tem_defaults_locais():
    from forge.infrastructure.config import Settings

    s = Settings(_env_file=None)
    assert s.acervo_url == "http://127.0.0.1:8000"
    assert s.acervo_top == 8
    assert s.acervo_timeout == 30.0


def test_broker_tem_defaults():
    from forge.infrastructure.config import Settings

    s = Settings(_env_file=None)
    assert s.gpu_lock_timeout == 900.0
    assert s.tts_backend == "vulkan"


def test_audio_generation_defaults_and_resolved_paths_stay_under_tool_dir():
    s = Settings(_env_file=None)

    assert s.audio_generate_dir == Path(r"C:\\dev\\audio-generate")
    assert s.tts_seed == 42
    assert s.tts_batch_size == 3
    assert s.tts_item_timeout == 900
    assert s.tts_batch_timeout == 3600
    assert s.tts_sample_rate == 24000
    for path in (s.resolved_tts_binary, s.resolved_tts_model, s.resolved_tts_voice_reference):
        assert path.is_relative_to(s.audio_generate_dir)


def test_audio_generation_resolved_paths_preserve_explicit_overrides(tmp_path):
    binary, model, voice = tmp_path / "bin.exe", tmp_path / "model.gguf", tmp_path / "voice.wav"
    s = Settings(_env_file=None, tts_binary=binary, tts_model=model, tts_voice_reference=voice)

    assert (s.resolved_tts_binary, s.resolved_tts_model, s.resolved_tts_voice_reference) == (
        binary, model, voice,
    )


@pytest.mark.parametrize("field, value", [("tts_batch_size", 0), ("tts_batch_size", 9), ("tts_item_timeout", 0), ("tts_batch_timeout", 0), ("tts_sample_rate", 0)])
def test_audio_generation_limits_are_validated(field, value):
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        Settings(_env_file=None, **{field: value})


def test_liberadores_tem_defaults():
    from forge.infrastructure.config import Settings

    s = Settings(_env_file=None)
    assert s.comfy_url == "http://127.0.0.1:8188"
    assert s.comfy_vram_livre_min == 6_000_000_000
    assert s.gpu_liberacao_timeout == 60.0
    assert s.comfy_process_timeout == 60.0
    assert s.gpu_orphan_diagnostic_threshold_mb == 600
    assert s.lms_bin.endswith("lms.exe")


@pytest.mark.parametrize(
    "campo, valor",
    [("comfy_process_timeout", 0), ("gpu_orphan_diagnostic_threshold_mb", 0)],
)
def test_limites_de_processos_gpu_devem_ser_positivos(campo, valor):
    """Aceitar zero desliga silenciosamente timeout/diagnóstico de órfãos."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        Settings(_env_file=None, **{campo: valor})


def test_llm_tem_prazo():
    from forge.infrastructure.config import Settings

    s = Settings(_env_file=None)
    assert s.llm_timeout == 600.0
    assert s.llm_max_retries == 1


def test_midia_alvo_segundos_deve_ser_positivo():
    """propor_beats divide por esse valor para estimar quantas imagens uma
    seção comporta; um 0 configurado seria ZeroDivisionError lá dentro. A
    validação recusa o valor aqui, na borda, em vez de um guard na função.
    """
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        Settings(_env_file=None, midia_alvo_segundos=0)


def test_juiz_de_relevancia_vem_ligado():
    from forge.infrastructure.config import Settings

    assert Settings(_env_file=None).juiz_relevancia is True


def test_arquivos_de_lacuna_apontam_para_o_acervo():
    from forge.infrastructure.config import Settings

    s = Settings(_env_file=None)
    assert s.gaps_file is not None and s.gaps_file.name == "unanswered_questions.txt"
    assert s.respostas_ruins_file is not None
    assert s.respostas_ruins_file.suffix == ".jsonl"


def test_nenhum_settings_da_suite_aponta_para_os_dados_do_usuario(tmp_path):
    r"""Rede de segurança da suíte inteira (fixture autouse em conftest).

    `Settings` sem `gaps_file` explícito herdava o caminho real,
    `C:\dev\research\dados\unanswered_questions.txt` — 16 linhas curadas à
    mão pelo usuário. Um único teste que esquecesse de passar `tmp_path` as
    poluiria.
    """
    from forge.infrastructure.config import Settings

    s = Settings(_env_file=None)

    assert s.gaps_file is not None and s.respostas_ruins_file is not None
    assert s.gaps_file.parent == tmp_path
    assert s.respostas_ruins_file.parent == tmp_path


def test_studio_db_path_tem_default_local(monkeypatch):
    monkeypatch.delenv("FORGE_STUDIO_DB_PATH", raising=False)

    assert Settings(_env_file=None).studio_db_path == Path("data/forge.db")


def test_studio_db_path_aceita_override_por_ambiente(monkeypatch, tmp_path):
    studio_db_path = tmp_path / "studio" / "forge.db"
    monkeypatch.setenv("FORGE_STUDIO_DB_PATH", str(studio_db_path))

    assert Settings(_env_file=None).studio_db_path == studio_db_path


def test_studio_db_path_aceita_construtor_direto(tmp_path):
    studio_db_path = tmp_path / "forge.db"

    assert Settings(_env_file=None, studio_db_path=studio_db_path).studio_db_path == studio_db_path


def test_worker_lease_e_heartbeat_tem_defaults_coerentes():
    settings = Settings(_env_file=None)

    assert settings.worker_lease_seconds == 15
    assert settings.worker_heartbeat_seconds == 5
    assert settings.worker_heartbeat_seconds < settings.worker_lease_seconds


def test_worker_lease_e_heartbeat_aceitam_override_por_ambiente(monkeypatch):
    monkeypatch.setenv("FORGE_WORKER_LEASE_SECONDS", "30")
    monkeypatch.setenv("FORGE_WORKER_HEARTBEAT_SECONDS", "7")

    settings = Settings(_env_file=None)

    assert settings.worker_lease_seconds == 30
    assert settings.worker_heartbeat_seconds == 7


def test_worker_rejeita_heartbeat_maior_ou_igual_ao_lease():
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        Settings(
            _env_file=None,
            worker_lease_seconds=15,
            worker_heartbeat_seconds=15,
        )
