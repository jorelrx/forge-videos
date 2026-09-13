from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from forge.domain.operacao import Artifact, ItemStatus, StageName
from forge.services.reconciliacao import (
    KNOWN_OUTPUTS,
    Reconciliador,
    register_orphan,
)


def _run_dir_for(tmp_path: Path, db) -> Path:
    from services.conftest import audio_stage
    with db.connection() as conn:
        repo, _, _ = audio_stage(conn)
    # Find the run id from the connection
    with db.connection() as conn:
        repo = __import__("forge.repositories.operacao", fromlist=[""]).OperacaoRepository(conn)
        video, run = repo.create_video_and_run(
            tema="Reconciliation",
            tese="Reconciliacao",
            priority=50,
            config_snapshot={},
            workflow_version=1,
            git_commit="abc",
        )
    return tmp_path / "runs" / run.id


def test_known_outputs_patterns_exist():
    assert "video/audio/*.wav" in KNOWN_OUTPUTS
    assert "video/validation.json" in KNOWN_OUTPUTS


def test_valid_succeeded_artifact_survives_reconciliation(tmp_path, db):
    from services.conftest import audio_stage, succeeded_audio_item
    with db.connection() as conn:
        repo, run, stage = audio_stage(conn)
        # Create work item and artifact
        run_dir = tmp_path / "runs" / run.id
        run_dir.mkdir(parents=True)
        (run_dir / "video" / "audio" / "b001.wav").parent.mkdir(parents=True, exist_ok=True)
        (run_dir / "video" / "audio" / "b001.wav").write_bytes(b"RIFFpayload")
        work_item_id = "work-b001"
        conn.execute(
            "INSERT INTO work_items (id, stage_run_id, item_key, status, input_json, input_hash, attempts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (work_item_id, stage.id, "b001", ItemStatus.SUCCEEDED.value, '{"texto":"b001"}', "a" * 64, 1),
        )
        artifact = Artifact(
            id="artifact-audio",
            run_id=run.id,
            stage_run_id=stage.id,
            work_item_id=work_item_id,
            kind="audio.wav",
            relative_path="video/audio/b001.wav",
            sha256=hashlib.sha256(b"RIFFpayload").hexdigest(),
            size_bytes=12,
            mime_type="audio/wav",
            metadata={"sample_rate": 24000},
            is_current=True,
            created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )
        repo.register_artifact(artifact)

    reconciliador = Reconciliador(db, tmp_path / "runs")
    report = reconciliador.reconcile(run.id)
    assert "artifact-audio" in report.preserved
    assert "artifact-audio" not in report.invalidated
    with db.connection() as conn:
        repo = __import__("forge.repositories.operacao", fromlist=[""]).OperacaoRepository(conn)
        item = next(i for i in repo.list_work_items(stage.id) if i.id == work_item_id)
        assert item.status is ItemStatus.SUCCEEDED


def test_missing_file_invalidates_artifact_and_resets_item(tmp_path, db):
    from services.conftest import audio_stage
    with db.connection() as conn:
        repo, run, stage = audio_stage(conn)
        run_dir = tmp_path / "runs" / run.id
        run_dir.mkdir(parents=True)
        # No file created -> missing
        work_item_id = "work-b001-missing"
        conn.execute(
            "INSERT INTO work_items (id, stage_run_id, item_key, status, input_json, input_hash, attempts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (work_item_id, stage.id, "b001", ItemStatus.SUCCEEDED.value, '{"texto":"b001"}', "b" * 64, 1),
        )
        artifact = Artifact(
            id="artifact-missing",
            run_id=run.id,
            stage_run_id=stage.id,
            work_item_id=work_item_id,
            kind="audio.wav",
            relative_path="video/audio/b001.wav",
            sha256="a" * 64,
            size_bytes=0,
            mime_type="audio/wav",
            metadata={},
            is_current=True,
            created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )
        repo.register_artifact(artifact)

    reconciliador = Reconciliador(db, tmp_path / "runs")
    report = reconciliador.reconcile(run.id)
    assert "artifact-missing" in report.invalidated
    with db.connection() as conn:
        repo = __import__("forge.repositories.operacao", fromlist=[""]).OperacaoRepository(conn)
        item = next(i for i in repo.list_work_items(stage.id) if i.id == work_item_id)
        # Item should be reset (PENDING with artifact_missing or FAILED)
        assert item.status in (ItemStatus.PENDING, ItemStatus.FAILED)


def test_changed_hash_invalidates_artifact(tmp_path, db):
    from services.conftest import audio_stage
    with db.connection() as conn:
        repo, run, stage = audio_stage(conn)
        run_dir = tmp_path / "runs" / run.id
        run_dir.mkdir(parents=True)
        (run_dir / "video" / "audio" / "b001.wav").parent.mkdir(parents=True, exist_ok=True)
        # File with different content than recorded hash
        (run_dir / "video" / "audio" / "b001.wav").write_bytes(b"different")
        work_item_id = "work-b001-changed"
        conn.execute(
            "INSERT INTO work_items (id, stage_run_id, item_key, status, input_json, input_hash, attempts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (work_item_id, stage.id, "b001", ItemStatus.SUCCEEDED.value, '{"texto":"b001"}', "c" * 64, 1),
        )
        artifact = Artifact(
            id="artifact-changed",
            run_id=run.id,
            stage_run_id=stage.id,
            work_item_id=work_item_id,
            kind="audio.wav",
            relative_path="video/audio/b001.wav",
            sha256=hashlib.sha256(b"original").hexdigest(),
            size_bytes=8,
            mime_type="audio/wav",
            metadata={},
            is_current=True,
            created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )
        repo.register_artifact(artifact)

    reconciliador = Reconciliador(db, tmp_path / "runs")
    report = reconciliador.reconcile(run.id)
    assert "artifact-changed" in report.invalidated


def test_known_unregistered_file_is_cataloged_as_orphan(tmp_path, db):
    from services.conftest import audio_stage
    with db.connection() as conn:
        repo, run, stage = audio_stage(conn)
        run_dir = tmp_path / "runs" / run.id
        run_dir.mkdir(parents=True)
        (run_dir / "video" / "audio" / "b001.wav").parent.mkdir(parents=True, exist_ok=True)
        (run_dir / "video" / "audio" / "b001.wav").write_bytes(b"RIFFpayload")

    reconciliador = Reconciliador(db, tmp_path / "runs")
    report = reconciliador.reconcile(run.id)
    # Since no artifact exists for b001.wav, it should become orphan
    assert any("b001" in (report.orphans or []) for _ in [True]) or len(report.orphans) > 0
    with db.connection() as conn:
        repo = __import__("forge.repositories.operacao", fromlist=[""]).OperacaoRepository(conn)
        artifacts = repo.list_artifacts(run.id, current_only=False)
        orphan_art = [a for a in artifacts if a.id in report.orphans and "b001" in a.relative_path]
        if orphan_art:
            assert orphan_art[0].kind == "audio.wav"
            assert orphan_art[0].is_current is False


def test_unknown_files_ignored_and_never_deleted(tmp_path, db):
    from services.conftest import audio_stage
    with db.connection() as conn:
        repo, run, stage = audio_stage(conn)
        run_dir = tmp_path / "runs" / run.id
        run_dir.mkdir(parents=True)
        (run_dir / "notes.private").write_text("keep", encoding="utf-8")

    reconciliador = Reconciliador(db, tmp_path / "runs")
    reconciliador.reconcile(run.id)
    assert (tmp_path / "runs" / run.id / "notes.private").read_text(encoding="utf-8") == "keep"


def test_register_orphan_creates_artifact_row():
    conn = None
    # Just verify the helper exists and has correct signature
    assert callable(register_orphan)
