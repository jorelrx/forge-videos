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
def test_probe_padrao_do_claude_nao_chama_o_modelo(monkeypatch):
    """O painel consulta a saúde em laço: uma chamada de modelo por consulta
    gastaria a cota da assinatura à toa. Só `auth status`."""
    from forge.infrastructure.config import Settings
    from forge.services import saude

    chamadas = []
    monkeypatch.setattr('forge.services.claude_cli.ClaudeCLI.check_auth', lambda self: chamadas.append('status'))
    monkeypatch.setattr('forge.services.claude_cli.ClaudeCLI.sondar',
                        lambda self: (_ for _ in ()).throw(AssertionError('modelo chamado')))
    probes = saude._default_probes(Settings(_env_file=None, provider='claude'))
    assert probes.claude() is True
    assert probes.usos['claude'] == ('roteiro', 'revisão')
    assert chamadas == ['status']


def _probes_todos(**extra):
    base = dict(
        research=lambda: True, lm_studio=lambda: True, comfyui=lambda: True,
        tts=lambda: True, ffmpeg=lambda: True, gpu=lambda: None,
        codex=lambda: True, claude=lambda: True, anthropic=lambda: True,
        openai=lambda: True, youtube=lambda: True,
    )
    base.update(extra)
    return HealthProbes(**base)


def test_check_all_lista_todos_os_servicos_mesmo_os_nao_habilitados():
    from forge.infrastructure.config import Settings
    from forge.services.saude import usos_dos_servicos

    usos = usos_dos_servicos(Settings(_env_file=None, provider="claude", image_provider="comfyui"))
    health = StudioHealthService(_probes_todos(usos=usos)).check_all()

    assert set(health) == {
        "research", "lm_studio", "comfyui", "tts", "ffmpeg", "gpu",
        "codex", "claude", "anthropic", "openai", "youtube",
    }
    assert health["claude"].enabled and health["claude"].usos == ["roteiro", "revisão"]
    assert health["comfyui"].enabled and health["comfyui"].usos == ["imagens"]
    assert not health["lm_studio"].enabled and health["lm_studio"].usos == []
    assert not health["anthropic"].enabled
    # Habilitado e disponível são eixos distintos: o não habilitado também é sondado.
    assert health["lm_studio"].state == ServiceState.AVAILABLE


def test_usos_separam_escritor_revisor_e_imagens():
    from forge.infrastructure.config import Settings
    from forge.services.saude import usos_dos_servicos

    usos = usos_dos_servicos(Settings(
        _env_file=None, provider="lm-studio", review_provider="claude", image_provider="codex",
    ))
    assert usos["lm_studio"] == ("roteiro",)
    assert usos["claude"] == ("revisão",)
    assert usos["codex"] == ("imagens",)
    assert usos["research"] == ("pesquisa",)
    assert usos["tts"] == ("narração",)
    assert usos["ffmpeg"] == ("montagem",)
    assert usos["youtube"] == ("publicação",)
    assert "gpu" in usos
    assert "comfyui" not in usos and "anthropic" not in usos and "openai" not in usos


def test_sondas_rodam_em_paralelo():
    """Com todo serviço sondado, timeouts de 2 s em série somariam ~10 s."""
    import time

    def lenta() -> bool:
        time.sleep(0.2)
        return True

    probes = _probes_todos(research=lenta, lm_studio=lenta, comfyui=lenta, codex=lenta, claude=lenta)
    inicio = time.perf_counter()
    StudioHealthService(probes).check_all()
    assert time.perf_counter() - inicio < 0.6


def test_leitura_carrega_estado_e_mensagem_propria():
    from forge.services.saude import Leitura

    probes = _probes_todos(
        anthropic=lambda: Leitura(ServiceState.UNAVAILABLE, "Sem FORGE_ANTHROPIC_API_KEY"),
        youtube=lambda: Leitura(ServiceState.DEGRADED, "Nenhum canal vinculado"),
    )
    health = StudioHealthService(probes).check_all()
    assert health["anthropic"].state == ServiceState.UNAVAILABLE
    assert health["anthropic"].message == "Sem FORGE_ANTHROPIC_API_KEY"
    assert health["youtube"].state == ServiceState.DEGRADED


def test_sem_usos_injetados_tudo_conta_como_habilitado():
    health = StudioHealthService(HealthProbes(
        research=lambda: True, lm_studio=lambda: True, comfyui=lambda: True,
        tts=lambda: True, ffmpeg=lambda: True, gpu=lambda: None,
    )).check_all()
    assert set(health) == {"research", "lm_studio", "comfyui", "tts", "ffmpeg", "gpu"}
    assert all(item.enabled for item in health.values())


def test_chaves_de_api_nao_vazam_e_seguem_o_provider(monkeypatch):
    from forge.infrastructure.config import Settings
    from forge.services import saude

    probes = saude._default_probes(Settings(
        _env_file=None, provider="openai", api_key="sk-generica", anthropic_api_key=None, openai_api_key=None,
    ))
    anthropic, openai = probes.anthropic(), probes.openai()
    # A chave genérica é do provider principal; não serve à Anthropic.
    assert anthropic.state == ServiceState.UNAVAILABLE
    assert openai.state == ServiceState.AVAILABLE
    assert "sk-" not in anthropic.message + openai.message


def test_youtube_le_cliente_e_canais_vinculados(tmp_path):
    from forge.infrastructure.config import Settings
    from forge.services import saude

    settings = Settings(
        _env_file=None,
        youtube_client_secrets=tmp_path / "client.json",
        youtube_canais_dir=tmp_path / "canais",
    )
    leitura = saude._default_probes(settings).youtube()
    assert leitura.state == ServiceState.UNAVAILABLE
    assert "cliente" in leitura.message.lower()



def test_fora_de_uso_reusa_leitura_por_um_minuto():
    """Serviço fora de uso não paga timeout nem CLI a cada consulta do painel."""
    agora = [0.0]
    chamadas = {"lm_studio": 0, "research": 0}

    def contar(nome):
        def probe() -> bool:
            chamadas[nome] += 1
            return True
        return probe

    service = StudioHealthService(
        _probes_todos(
            lm_studio=contar("lm_studio"), research=contar("research"),
            usos={"research": ("pesquisa",)},
        ),
        relogio=lambda: agora[0],
    )
    service.check_all()
    agora[0] = 30.0
    service.check_all()
    assert chamadas == {"lm_studio": 1, "research": 2}
    agora[0] = 61.0
    service.check_all()
    assert chamadas == {"lm_studio": 2, "research": 3}


def test_worker_e_habilitado_sempre():
    from forge.infrastructure.config import Settings
    from forge.services.saude import usos_dos_servicos

    assert usos_dos_servicos(Settings(_env_file=None))["worker"] == ("execução da fila",)


def test_default_probes_le_batimento_do_worker(tmp_path):
    from forge.infrastructure.config import Settings
    from forge.services import saude

    settings = Settings(_env_file=None, output_dir=tmp_path / "roteiros")
    leitura = saude._default_probes(settings).worker()
    assert leitura.state == ServiceState.UNAVAILABLE
