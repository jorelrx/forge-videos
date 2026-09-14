"""Launcher do ComfyUI: sobe só quando está fora do ar, e registra o PID.

O broker encerra o ComfyUI antes do TTS (o processo segura o heap Vulkan) e o
áudio roda antes das imagens — sem este launcher, a etapa de imagem encontraria
o servidor morto em todo run.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from forge.gpu import liberadores
from forge.gpu.liberadores import garantir_comfy
from forge.infrastructure.config import Settings


class FakeProcess:
    pid = 4242


def _settings(tmp_path: Path) -> Settings:
    comfy = tmp_path / "comfy"
    (comfy / "venv" / "Scripts").mkdir(parents=True)
    (comfy / "venv" / "Scripts" / "python.exe").write_bytes(b"MZ")
    (comfy / "main.py").write_text("print('comfy')", encoding="utf-8")
    return Settings(
        _env_file=None,
        comfy_dir=comfy,
        comfy_output_dir=tmp_path / "comfy-out",
        comfy_url="http://127.0.0.1:8188",
        comfy_boot_timeout=2.0,
    )


def test_does_not_launch_when_the_server_is_already_up(tmp_path):
    lancamentos: list = []

    resultado = garantir_comfy(
        _settings(tmp_path),
        probe=lambda: True,
        launcher=lambda *args, **kwargs: lancamentos.append(args),
    )

    assert resultado is True
    assert lancamentos == []


def test_launches_with_the_configured_boot_arguments(tmp_path):
    settings = _settings(tmp_path)
    capturado: dict = {}
    registrados: list[int] = []
    estados = iter([False, False, True])

    def launcher(argv, **kwargs):
        capturado["argv"] = argv
        capturado.update(kwargs)
        return FakeProcess()

    resultado = garantir_comfy(
        settings,
        probe=lambda: next(estados, True),
        launcher=launcher,
        registrar=registrados.append,
    )

    assert resultado is True
    assert registrados == [4242]

    argv = capturado["argv"]
    assert argv[0] == str(settings.resolved_comfy_python)
    assert argv[1] == str(settings.comfy_dir / "main.py")
    assert "--directml" in argv and "--lowvram" in argv
    assert argv[argv.index("--port") + 1] == "8188"
    assert "--disable-auto-launch" in argv
    assert argv[argv.index("--output-directory") + 1] == str(settings.comfy_output_dir)
    assert capturado["cwd"] == str(settings.comfy_dir)


def test_returns_false_when_the_server_never_comes_up(tmp_path):
    registrados: list[int] = []

    resultado = garantir_comfy(
        _settings(tmp_path),
        probe=lambda: False,
        launcher=lambda *args, **kwargs: FakeProcess(),
        registrar=registrados.append,
    )

    assert resultado is False
    # O PID é registrado mesmo assim: é árvore que o forge abriu e pode encerrar.
    assert registrados == [4242]


def test_does_not_launch_when_the_comfy_install_is_missing(tmp_path):
    vazio = tmp_path / "vazio"
    vazio.mkdir()
    lancamentos: list = []

    resultado = garantir_comfy(
        Settings(_env_file=None, comfy_dir=vazio, comfy_boot_timeout=0.2),
        probe=lambda: False,
        launcher=lambda *args, **kwargs: lancamentos.append(args),
    )

    assert resultado is False
    assert lancamentos == []


def test_auto_start_is_wired_as_the_image_slot_preparer(tmp_path, monkeypatch):
    """Reclamar o slot de imagem é o ponto certo para subir o ComfyUI."""
    settings = _settings(tmp_path)
    chamadas: list[Settings] = []
    monkeypatch.setattr(
        liberadores, "garantir_comfy", lambda s, **kw: chamadas.append(s) or True
    )

    broker = liberadores.montar_broker(settings, base=tmp_path)
    broker.preparadores["imagem"]()

    assert chamadas == [settings]


def test_auto_start_can_be_disabled(tmp_path, monkeypatch):
    settings = _settings(tmp_path).model_copy(update={"comfy_auto_start": False})
    chamadas: list = []
    monkeypatch.setattr(
        liberadores, "garantir_comfy", lambda s, **kw: chamadas.append(s) or True
    )

    broker = liberadores.montar_broker(settings, base=tmp_path)
    broker.preparadores["imagem"]()

    assert chamadas == []
