"""Gate comum dos testes de integração real.

Nada aqui roda por acidente. `uv run pytest` mantém `-m not integration` no
`pyproject.toml`, e além disso todo teste exige `FORGE_RUN_INTEGRATION=1`. Um
serviço indisponível vira SKIP com endpoint/path exato — nunca PASS fictício,
nunca corpo de teste com `pytest.skip` incondicional.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import httpx
import pytest

from forge.infrastructure.config import get_settings

OPT_IN_ENV = "FORGE_RUN_INTEGRATION"


def require_integration_opt_in() -> None:
    if os.getenv(OPT_IN_ENV) != "1":
        pytest.skip(
            f"defina {OPT_IN_ENV}=1 para habilitar integração real"
        )


@pytest.fixture(autouse=True)
def integration_opt_in() -> None:
    require_integration_opt_in()


@pytest.fixture
def real_settings(tmp_path: Path):
    """Config real da máquina, com artefatos isolados em tmp_path.

    Parte de `get_settings()` de propósito: `Settings(_env_file=None)` perderia
    o provider/URLs configurados no `.env` e os testes passariam a medir o
    default do código, não a máquina. Aqui só os caminhos de escrita mudam.
    """
    base = get_settings()
    audio = tmp_path / "audio"
    audio.mkdir()
    return base.model_copy(
        update={
            "studio_db_path": tmp_path / "forge.db",
            "studio_runs_dir": tmp_path / "runs",
            "output_dir": tmp_path / "roteiros",
            "gaps_file": tmp_path / "gaps.txt",
            "respostas_ruins_file": tmp_path / "bad.jsonl",
            "audio_generate_dir": base.audio_generate_dir,
        }
    )


def _http_ok(url: str, *, timeout: float = 2.0) -> tuple[bool, str]:
    try:
        resp = httpx.get(url, timeout=timeout)
    except Exception as error:  # noqa: BLE001 - o motivo vira diagnóstico de skip
        return False, str(error)
    if resp.status_code >= 400:
        return False, f"HTTP {resp.status_code}"
    return True, ""


def require_http(url: str, *, action: str) -> str:
    """Skip com endpoint e ação concreta quando o serviço não responde."""
    ok, motivo = _http_ok(url)
    if not ok:
        pytest.skip(f"{url} indisponível ({motivo}). Ação: {action}")
    return url


def require_binary(name: str, *, action: str) -> str:
    path = shutil.which(name)
    if path is None:
        pytest.skip(f"{name} não está no PATH. Ação: {action}")
    return path


def require_file(path: Path, *, env_var: str) -> Path:
    if not Path(path).is_file():
        pytest.skip(f"{path} não existe. Ação: aponte {env_var} para o arquivo")
    return Path(path)
