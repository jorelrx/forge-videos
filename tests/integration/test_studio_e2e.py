"""Run completa do Studio: só conclui com um vídeo real e validado.

Sem mock algum: LLM, research, TTS, ComfyUI, FFmpeg e broker são os de
produção. Exige `FORGE_RUN_INTEGRATION=1` e `FORGE_RUN_STUDIO_E2E=1`.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from forge.api.app import build_api_services, create_app
from forge.domain.execucao import StudioPreset
from forge.domain.operacao import ETAPAS, RunStatus, StageStatus
from forge.executors.ffmpeg import probe_media
from forge.services.studio import build_control_plane, build_worker

from .support import (
    KEEP_OUTPUT_ENV,
    assert_all_stages_succeeded,
    diagnostics,
    isolated_settings,
    read_validation,
    require_studio_e2e_opt_in,
)

pytestmark = pytest.mark.integration

# Oito etapas mais a folga de retry implícito. Ao esgotar, o teste falha com o
# diagnóstico de cada etapa — nunca gira para sempre.
MAX_PASSOS = 32


def test_studio_completes_real_video(real_settings, tmp_path: Path) -> None:
    settings = isolated_settings(real_settings, tmp_path)
    require_studio_e2e_opt_in(settings)

    control = build_control_plane(settings)
    _, run = control.enqueue_video(
        tema="Por que a liberdade exige limites?",
        tese="",
        priority=50,
        config_snapshot=StudioPreset().model_dump(mode="json"),
        workflow_version=1,
        git_commit="integration", canal_id="integracao",
    )
    worker = build_worker(settings, worker_id="integration-worker")

    detail = control.get_run(run.id)
    for _ in range(MAX_PASSOS):
        worker.run_once()
        detail = control.get_run(run.id)
        if detail.run.status in {RunStatus.COMPLETED, RunStatus.FAILED}:
            break

    run_dir = settings.studio_runs_dir / run.id
    if os.getenv(KEEP_OUTPUT_ENV) == "1":
        print(f"[e2e] saída preservada em {run_dir}")

    assert detail.run.status is RunStatus.COMPLETED, diagnostics(detail)
    assert [stage.stage for stage in detail.stages] == list(ETAPAS)
    assert_all_stages_succeeded(detail)

    artifacts = {artifact.relative_path: artifact for artifact in detail.artifacts}
    for esperado in ("video/midia.json", "video/final.mp4", "video/validation.json"):
        assert esperado in artifacts, f"artefato ausente: {esperado}"
    assert all(artifact.is_current for artifact in artifacts.values())

    relatorio = read_validation(run_dir)
    assert relatorio["approved"] is True, relatorio["findings"]
    assert not relatorio["findings"], relatorio["findings"]
    assert all(check["approved"] for check in relatorio["checks"])

    final = run_dir / "video" / "final.mp4"
    probe = probe_media(final)
    assert (probe.codec, probe.audio_codec) == ("h264", "aac")
    assert (probe.width, probe.height) == (1920, 1080)
    assert probe.duration and probe.duration > 0

    # O dashboard precisa enxergar a MESMA run pelo control plane, sem inferir
    # estado do disco.
    from forge.services.sessao_studio import SessaoStudio
    token = SessaoStudio(control.db).criar("teste", "Teste")
    with control.db.transaction() as conn:
        conn.execute("INSERT INTO acesso_canais(conta_id,canal_id,titulo) VALUES ('teste','integracao','Teste')")
    with TestClient(create_app(build_api_services(settings)), cookies={"forge_sessao": token}) as client:
        resposta = client.get(f"/api/runs/{run.id}")
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["run"]["status"] == RunStatus.COMPLETED.value
        assert set(corpo["stages"]) == {stage.value for stage in ETAPAS}

        lista = client.get(f"/api/runs/{run.id}/artifacts")
        assert lista.status_code == 200
        itens = lista.json()
        itens = itens["items"] if isinstance(itens, dict) else itens
        video = next(
            item for item in itens if item["relative_path"] == "video/final.mp4"
        )

        faixa = client.get(
            f"/api/artifacts/{video['id']}/content",
            headers={"Range": "bytes=0-1023"},
        )
        assert faixa.status_code in (200, 206)
        assert len(faixa.content) > 0
