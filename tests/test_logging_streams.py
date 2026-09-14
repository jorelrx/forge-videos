"""O stdout do processo filho é o canal do protocolo JSONL.

Qualquer linha não-JSON ali é lida pelo pai como evento inválido e derruba a
etapa inteira — foi assim que a run ponta a ponta morreu na pesquisa, com
`2026-09-14 07:44:54 [info] Research completed passagens=5` no lugar de um
evento. O log estruturado do filho precisa ir para stderr.

Fora do filho o log continua no stdout: o CLI imprime o caminho do roteiro lá.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from forge.infrastructure import logging as forge_logging


@pytest.fixture(autouse=True)
def reset_child_logging(monkeypatch):
    """`setup_child_logging` é idempotente por módulo e a config é global."""
    import structlog

    anterior = structlog.get_config()
    monkeypatch.setattr(forge_logging, "_CHILD_CONFIGURED", False)
    yield
    monkeypatch.setattr(forge_logging, "_CHILD_CONFIGURED", False)
    structlog.configure(**anterior)


def test_child_logging_sends_structured_logs_to_stderr(monkeypatch):
    capturado_out = io.StringIO()
    capturado_err = io.StringIO()
    monkeypatch.setattr(sys, "stdout", capturado_out)
    monkeypatch.setattr(sys, "stderr", capturado_err)

    forge_logging.setup_child_logging("INFO")
    forge_logging.get_logger("teste").info("Research completed", passagens=5)

    assert "Research completed" in capturado_err.getvalue()
    assert capturado_out.getvalue() == "", (
        "stdout do filho carrega JSONL: log ali vira evento inválido"
    )


def test_child_logger_factory_resolves_stderr_dynamically(monkeypatch):
    """Capturar o stream em `configure` quebra sob o capture do pytest."""
    forge_logging.setup_child_logging("INFO")

    novo = io.StringIO()
    monkeypatch.setattr(sys, "stderr", novo)
    forge_logging.get_logger("teste").info("depois da troca")

    assert "depois da troca" in novo.getvalue()


def test_entrypoint_configures_child_logging_in_the_module_guard():
    """O entrypoint possui o canal, mas a configuração não pode viver em
    `main()`: os testes a chamam no processo do pytest e a reconfiguração
    global vazaria para o resto da sessão."""
    origem = (
        Path(__file__).resolve().parents[1]
        / "src" / "forge" / "executors" / "entrypoint.py"
    ).read_text(encoding="utf-8")

    guarda = origem.split('if __name__ == "__main__":', 1)[1]
    assert "setup_child_logging()" in guarda
    corpo_de_main = origem.split("def main(")[1].split('if __name__ == "__main__":')[0]
    assert "setup_child_logging" not in corpo_de_main


def test_child_executors_do_not_print_to_stdout():
    """Um `print` dentro de um executor corrompe o protocolo do subprocesso."""
    raiz = Path(__file__).resolve().parents[1] / "src" / "forge" / "executors"
    infratores = []
    for arquivo in raiz.rglob("*.py"):
        if arquivo.name == "entrypoint.py":
            # O entrypoint é quem EMITE o JSONL no stdout.
            continue
        for numero, linha in enumerate(
            arquivo.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if "print(" in linha and "file=sys.stderr" not in linha:
                infratores.append(f"{arquivo.name}:{numero}")
    assert not infratores, f"print em stdout dentro de executor: {infratores}"
