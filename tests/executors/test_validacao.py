"""Testes para executor de validação final."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.domain.execucao import GateResult, StageChildResult, ArtifactOutput
from forge.domain.operacao import StageName, Artifact
from forge.domain.operacao import WorkItem, ItemStatus
from forge.executors.validacao import ValidationExecutor
from forge.domain.execucao import RunSnapshot


class FakeArtifact:
    def __init__(self, kind, relative_path, is_current=True, metadata=None):
        self.kind = kind
        self.relative_path = relative_path
        self.is_current = is_current
        self.metadata = metadata or {}


def _artifact(kind, path, is_current=True, meta=None):
    return Artifact(
        id="a1", run_id="run-1", stage_run_id="s1", work_item_id=None,
        kind=kind, relative_path=path,
        sha256="a" * 64, size_bytes=1024, mime_type="audio/wav" if kind.startswith("audio") else "image/png",
        metadata=meta or {}, is_current=is_current,
        created_at="2026-09-13T00:00:00Z",
    )


def _work_item(key, status=ItemStatus.SUCCEEDED):
    return WorkItem(
        id=f"w-{key}", stage_run_id="s1", item_key=key,
        status=status, input={}, input_hash="a" * 64,
        attempts=1, duration_ms=100,
    )


def _snapshot(tmp_path: Path, stage=StageName.VALIDACAO, artifacts=None, work_items=(), run_dir=None) -> RunSnapshot:
    root = tmp_path / "runs"
    rd = run_dir or (root / "run-1")
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "video").mkdir(parents=True, exist_ok=True)
    real_arts = []
    for a in (artifacts or []):
        if isinstance(a, Artifact):
            real_arts.append(a)
        else:
            # Convert FakeArtifact to Artifact
            real_arts.append(_artifact(
                a.kind, a.relative_path, a.is_current, a.metadata
            ))
    real_items = []
    for w in work_items:
        if isinstance(w, WorkItem):
            real_items.append(w)
        else:
            # Assume fake item; skip if not WorkItem
            real_items.append(_work_item(str(w)))
    return RunSnapshot(
        run_id="run-1",
        video_id="v1",
        tema="Tema",
        tese="Tese",
        stage=stage,
        attempt=1,
        output_root=root,
        run_dir=rd,
        config_snapshot={},
        artifacts=real_arts,
        work_items=real_items,
    )


def test_final_gate_cross_checks_plan_items_and_artifacts(tmp_path):
    artifacts = [_artifact("audio.wav", f"video/audio/b{i:03d}.wav") for i in range(40)]
    work_items = [_work_item(f"b{i:03d}", ItemStatus.SUCCEEDED) for i in range(41)]
    snapshot = _snapshot(tmp_path, artifacts=artifacts, work_items=work_items)
    result = ValidationExecutor().run(snapshot, lambda **e: None)
    assert result.gate.code == "final_validation_failed"
    assert any(f.code == "audio_count_mismatch" for f in result.gate.findings)


def test_silence_longer_than_threshold_fails(tmp_path):
    snapshot = _snapshot(tmp_path)
    result = ValidationExecutor(max_unplanned_silence_seconds=2.0).run(snapshot, lambda **e: None)
    codes = [f.code for f in result.gate.findings]
    assert "unexpected_silence" in codes


def test_all_sample_frames_must_be_extractable(tmp_path):
    snapshot = _snapshot(tmp_path)
    (snapshot.run_dir / "video" / "final.mp4").write_bytes(b"not a video")
    result = ValidationExecutor().run(snapshot, lambda **e: None)
    assert any(f.code == "frame_sample_failed" for f in result.gate.findings)


def test_valid_report_is_registered_before_worker_can_complete(tmp_path):
    artifacts = [_artifact("audio.wav", f"video/audio/b{i:03d}.wav") for i in range(41)]
    artifacts += [_artifact("image/png", f"video/images/i{i:03d}.png") for i in range(9)]
    snapshot = _snapshot(tmp_path, artifacts=artifacts)
    (snapshot.run_dir / "video" / "final.mp4").write_bytes(b"fake")
    result = ValidationExecutor().run(snapshot, lambda **e: None)
    assert (snapshot.run_dir / "video" / "validation.json").is_file()
    kinds = [art.kind for art in result.artifacts]
    assert "validation.report" in kinds


def test_gate_approved_for_complete_run(tmp_path):
    artifacts = [_artifact("audio.wav", f"video/audio/b{i:03d}.wav") for i in range(41)]
    artifacts += [_artifact("image/png", f"video/images/i{i:03d}.png") for i in range(9)]
    snapshot = _snapshot(tmp_path, artifacts=artifacts)
    result = ValidationExecutor().run(snapshot, lambda **e: None)
    assert not any(f.code == "audio_count_mismatch" for f in result.gate.findings)
    assert not any(f.code == "image_artifact_missing" for f in result.gate.findings)
    assert (snapshot.run_dir / "video" / "validation.json").is_file()
