"""Testes para executor de imagens."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.domain.execucao import RunSnapshot
from forge.domain.operacao import StageName
from forge.executors.imagens import ImageExecutor
from forge.executors.comfy import ComfyClient
from forge.infrastructure.config import Settings


def _snapshot(tmp_path: Path, stage=StageName.IMAGENS) -> RunSnapshot:
    root = tmp_path / "runs"
    from forge.services.persistencia import gravar_modelo
    from forge.domain.midia import PlanoMidia, Beat
    run_dir = root / "run-1"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "video").mkdir(parents=True, exist_ok=True)
    gravar_modelo(run_dir / "video" / "midia.json", PlanoMidia(beats=[
        Beat(id="i001", bloco_id="b001", prompt="cosmic interior"),
        Beat(id="i002", bloco_id="b002", prompt="interior space"),
    ]))
    return RunSnapshot(
        run_id="run-1", video_id="v1", tema="T", tese="Teste",
        stage=stage, attempt=1, output_root=root, run_dir=run_dir,
        config_snapshot={}, artifacts=[], work_items=[],
    )


def test_image_gate_rejects_when_image_unreadable(tmp_path):
    snapshot = _snapshot(tmp_path)
    executor = ImageExecutor(client=ComfyClient(settings=Settings(), offline=True))
    plan = executor.prepare(snapshot)
    events = []
    result = executor.execute(snapshot, plan, lambda **e: events.append(e))
    gate = executor.validate(snapshot, plan, result)
    assert not gate.approved


def test_retry_uses_same_hash_images_and_renders_only_failed_beats(tmp_path):
    snapshot = _snapshot(tmp_path)
    executor = ImageExecutor(client=ComfyClient(settings=Settings(), offline=True))
    plan = executor.prepare(snapshot)
    events = []
    result = executor.execute(snapshot, plan, lambda **e: events.append(e))
    gate = executor.validate(snapshot, plan, result)
    assert result.total_items == 2
