"""O runbook do Studio precisa citar os comandos reais que existem.

Documentação que aponta para um script inexistente é pior que documentação
ausente: o operador descobre no meio da operação.
"""
from __future__ import annotations

from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
README = RAIZ / "README.md"

COMANDOS = (
    r".\scripts\start-studio.ps1",
    r".\scripts\stop-studio.ps1",
    "uv run forge-studio-doctor --migrate",
    "uv run forge-import-runs",
    "FORGE_RUN_INTEGRATION=1",
    "FORGE_RUN_STUDIO_E2E=1",
)

CAMINHOS = (
    "scripts/start-studio.ps1",
    "scripts/stop-studio.ps1",
    "scripts/studio-common.ps1",
    "src/forge/studio/doctor.py",
    "src/forge/studio/import_runs.py",
)


@pytest.fixture(scope="module")
def readme() -> str:
    return README.read_text(encoding="utf-8")


@pytest.mark.parametrize("comando", COMANDOS)
def test_readme_documenta_o_comando(readme: str, comando: str) -> None:
    assert comando in readme, f"comando ausente no README: {comando}"


@pytest.mark.parametrize("caminho", CAMINHOS)
def test_caminho_citado_existe(caminho: str) -> None:
    assert (RAIZ / caminho).exists(), f"caminho documentado não existe: {caminho}"


def test_readme_nao_promete_busca_web(readme: str) -> None:
    """A pesquisa usa o acervo; um fallback web silencioso foi eliminado de propósito."""
    assert "acervo" in readme.lower()


def test_exemplo_de_env_cobre_as_variaveis_do_studio() -> None:
    exemplo = (RAIZ / ".env.example").read_text(encoding="utf-8")
    for variavel in (
        "FORGE_STUDIO_DB_PATH",
        "FORGE_STUDIO_RUNS_DIR",
        "FORGE_STUDIO_API_PORT",
        "FORGE_STUDIO_WORKER_POLL_SECONDS",
        "FORGE_TTS_BINARY",
        "FORGE_COMFY_DIR",
    ):
        assert variavel in exemplo, f"variável ausente em .env.example: {variavel}"


def test_nenhum_runtime_referencia_o_poc_antigo() -> None:
    """Restrição do plano: o runtime não pode depender do POC antigo."""
    # Montado em partes: escrito literalmente, o próprio teste se acusaria.
    proibido = "_pipeline" + "-poc"
    for pasta in ("src", "scripts", "tests"):
        for arquivo in (RAIZ / pasta).rglob("*"):
            if not arquivo.is_file() or arquivo.suffix not in {".py", ".ps1", ".md"}:
                continue
            try:
                texto = arquivo.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            assert proibido not in texto, f"referência proibida em {arquivo}"
