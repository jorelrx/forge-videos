from __future__ import annotations

import pytest

from forge.services.saude import ServiceState, StudioHealthService, HealthProbes, ServiceHealth


def test_service_state_enum_values():
    assert ServiceState.AVAILABLE.value == "available"
    assert ServiceState.UNAVAILABLE.value == "unavailable"
    assert ServiceState.DEGRADED.value == "degraded"


def test_service_health_model_default():
    sh = ServiceHealth(name="test", state=ServiceState.AVAILABLE, message="OK")
    assert sh.latency_ms is None
    assert sh.details == {}


def test_health_probes_dataclass():
    def dummy() -> bool:
        return True
    probes = HealthProbes(
        research=dummy,
        lm_studio=dummy,
        comfyui=dummy,
        tts=dummy,
        ffmpeg=dummy,
        gpu=lambda: None,
    )
    assert probes.research() is True


def test_studio_health_service_check_all_with_mock_probes():
    def always_true() -> bool:
        return True
    def always_false() -> bool:
        return False
    def gpu_none() -> None:
        return None

    service = StudioHealthService(
        probes=HealthProbes(
            research=always_true,
            lm_studio=always_true,
            comfyui=always_true,
            tts=always_true,
            ffmpeg=always_true,
            gpu=gpu_none,
        )
    )
    result = service.check_all()
    assert "research" in result
    assert result["research"].state == ServiceState.AVAILABLE


def test_studio_health_service_degraded_for_unavailable_probe():
    def fail_probe() -> bool:
        raise RuntimeError("simulado")

    service = StudioHealthService(
        probes=HealthProbes(
            research=fail_probe,
            lm_studio=lambda: True,
            comfyui=lambda: True,
            tts=lambda: True,
            ffmpeg=lambda: True,
            gpu=lambda: None,
        )
    )
    result = service.check_all()
    assert result["research"].state == ServiceState.UNAVAILABLE
    assert "simulado" in result["research"].message


def test_check_all_returns_six_services():
    def true_probe() -> bool:
        return True
    service = StudioHealthService(
        probes=HealthProbes(
            research=true_probe,
            lm_studio=true_probe,
            comfyui=true_probe,
            tts=true_probe,
            ffmpeg=true_probe,
            gpu=lambda: None,
        )
    )
    result = service.check_all()
    assert len(result) == 6
    assert set(result.keys()) == {"research", "lm_studio", "comfyui", "tts", "ffmpeg", "gpu"}


def test_default_probes_gpu_le_o_estado_real_do_broker(tmp_path, monkeypatch):
    """O probe de GPU precisa ler o MESMO arquivo que o broker grava.

    Com um caminho temporário próprio ele nunca enxerga o residente: o painel
    anunciava "Sem residente" com o LLM carregado na placa.
    """
    import json
    import os

    from forge.infrastructure.config import Settings
    from forge.services import saude

    settings = Settings(_env_file=None, output_dir=tmp_path / "roteiros")
    (tmp_path / ".gpu-residente.json").write_text(
        json.dumps({
            "recurso": "llm",
            "pid": os.getpid(),
            "claimed_at": "2026-09-14T13:55:30+00:00",
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(saude, "get_settings", lambda: settings)

    assert saude._default_probes().gpu() == "llm"


def test_default_probes_gpu_ignora_dono_morto(tmp_path, monkeypatch):
    """Estado gravado por um filho que já saiu não é residente."""
    import json

    from forge.infrastructure.config import Settings
    from forge.services import saude

    settings = Settings(_env_file=None, output_dir=tmp_path / "roteiros")
    (tmp_path / ".gpu-residente.json").write_text(
        json.dumps({
            "recurso": "imagem",
            "pid": 999999,
            "claimed_at": "2026-09-14T13:55:30+00:00",
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(saude, "get_settings", lambda: settings)

    assert saude._default_probes().gpu() is None


def test_default_probes_report_structured_health_when_services_are_offline():
    service = StudioHealthService()
    # Não falha imediatamente porque _default_probes captura exceções,
    # mas os probes retornam False (indisponível) na maioria dos casos.
    result = service.check_all()
    # Esperado parcial: alguns disponíveis, a maioria UNAVAILABLE sem endpoints ativos.
    for name in result:
        assert isinstance(result[name], ServiceHealth)
