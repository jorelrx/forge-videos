"""Apoio do teste ponta a ponta: opt-in duplo, isolamento e sondas de produto."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from forge.domain.operacao import StageStatus
from forge.infrastructure.config import Settings
from forge.services.preflight import check_preflight

STUDIO_E2E_ENV = "FORGE_RUN_STUDIO_E2E"
KEEP_OUTPUT_ENV = "FORGE_KEEP_INTEGRATION_OUTPUT"


def require_studio_e2e_opt_in(settings: Settings) -> None:
    """Exige as duas flags e a máquina pronta; senão SKIP com a lista do que falta.

    Um requisito ausente não pode virar run parcial: o teste começa inteiro ou
    não começa.
    """
    if os.getenv("FORGE_RUN_INTEGRATION") != "1":
        pytest.skip("defina FORGE_RUN_INTEGRATION=1 para habilitar integração real")
    if os.getenv(STUDIO_E2E_ENV) != "1":
        pytest.skip(
            f"defina {STUDIO_E2E_ENV}=1 para habilitar a run completa de vídeo"
        )

    report = check_preflight(settings)
    falhas = [check for check in report.checks if check.state == "failed"]
    if falhas:
        detalhes = "; ".join(
            f"{check.name}: {check.action or check.message}" for check in falhas
        )
        pytest.skip(f"pré-requisitos ausentes -> {detalhes}")


def isolated_settings(real_settings: Settings, tmp_path: Path) -> Settings:
    """Nenhum caminho de produção é reusado: banco, runs, gaps e lock são locais."""
    raiz = tmp_path / "isolado"
    raiz.mkdir(parents=True, exist_ok=True)
    return real_settings.model_copy(
        update={
            "studio_db_path": raiz / "forge.db",
            "studio_runs_dir": raiz / "runs",
            "output_dir": raiz / "roteiros",
            "gaps_file": raiz / "gaps.txt",
            "respostas_ruins_file": raiz / "bad.jsonl",
            "comfy_output_dir": raiz / "comfy-out",
            "image_library_dir": raiz / "library",
            "lora_dir": raiz / "loras",
        }
    )


def diagnostics(detail) -> str:
    """Lista stage/status/failure_code para quando o laço se esgota."""
    linhas = [
        f"{stage.stage.value}={stage.status.value}"
        + (f"({stage.failure_code})" if stage.failure_code else "")
        for stage in detail.stages
    ]
    run = detail.run
    return (
        f"run={run.id} status={run.status.value} "
        f"failure={run.failure_code}:{run.failure_message} | " + " ".join(linhas)
    )


def assert_all_stages_succeeded(detail) -> None:
    reprovadas = [
        stage for stage in detail.stages if stage.status is not StageStatus.SUCCEEDED
    ]
    assert not reprovadas, diagnostics(detail)
    sem_gate = [stage.stage.value for stage in detail.stages if not stage.gate_status]
    assert not sem_gate, f"etapas sem gate_status: {sem_gate}"


def read_validation(run_dir: Path) -> dict:
    caminho = run_dir / "video" / "validation.json"
    assert caminho.is_file(), f"validation.json ausente: {caminho}"
    return json.loads(caminho.read_text(encoding="utf-8"))
