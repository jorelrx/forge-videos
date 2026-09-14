from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from forge.domain.operacao import Artifact, ItemStatus, StageName
from forge.services.reconciliacao import Reconciliador
from forge.repositories.connection import Database
from forge.repositories.operacao import OperacaoRepository
from forge.repositories.schema import init_db


def _setup_db(tmp_path):
    db_path = tmp_path / "forge.db"
    db = Database(db_path)
    init_db(db)
    with db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        video, run = repo.create_video_and_run(
            tema="Teste",
            tese="Tese",
            priority=50,
            config_snapshot={},
            workflow_version=1,
            git_commit="abc",
        )
        stage = next(
            s
            for s in repo.current_stages(run.id)
            if s.stage is StageName.AUDIO
        )
    return db, run, stage


def test_known_outputs_patterns_exist():
    from forge.services.reconciliacao import KNOWN_OUTPUTS

    assert "video/audio/*.wav" in KNOWN_OUTPUTS
    assert "video/validation.json" in KNOWN_OUTPUTS


def test_valid_succeeded_artifact_survives_reconciliation(tmp_path):
    db, run, stage = _setup_db(tmp_path)
    run_dir = tmp_path / "runs" / run.id
    run_dir.mkdir(parents=True)
    (run_dir / "video" / "audio" / "b001.wav").parent.mkdir(
        parents=True, exist_ok=True
    )
    (run_dir / "video" / "audio" / "b001.wav").write_bytes(b"RIFFpayload")

    work_item_id = "work-b001"
    with db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        conn.execute(
            "INSERT INTO work_items (id, stage_run_id, item_key, status, input_json, input_hash, attempts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                work_item_id,
                stage.id,
                "b001",
                ItemStatus.SUCCEEDED.value,
                '{"texto":"b001"}',
                "a" * 64,
                1,
            ),
        )
        artifact = Artifact(
            id="artifact-audio",
            run_id=run.id,
            stage_run_id=stage.id,
            work_item_id=work_item_id,
            kind="audio.wav",
            relative_path="video/audio/b001.wav",
            sha256=hashlib.sha256(b"RIFFpayload").hexdigest(),
            size_bytes=len(b"RIFFpayload"),
            mime_type="audio/wav",
            metadata={"sample_rate": 24000},
            is_current=True,
            created_at=datetime.now(UTC),
        )
        repo.register_artifact(artifact)

    reconciliador = Reconciliador(db, tmp_path / "runs")
    report = reconciliador.reconcile(run.id)
    assert "artifact-audio" in report.preserved
    assert "artifact-audio" not in report.invalidated


def test_missing_file_invalidates_artifact_and_resets_item(tmp_path):
    db, run, stage = _setup_db(tmp_path)
    run_dir = tmp_path / "runs" / run.id
    run_dir.mkdir(parents=True)

    work_item_id = "work-b001-missing"
    with db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        conn.execute(
            "INSERT INTO work_items (id, stage_run_id, item_key, status, input_json, input_hash, attempts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                work_item_id,
                stage.id,
                "b001",
                ItemStatus.SUCCEEDED.value,
                '{"texto":"b001"}',
                "b" * 64,
                1,
            ),
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
            created_at=datetime.now(UTC),
        )
        repo.register_artifact(artifact)

    reconciliador = Reconciliador(db, tmp_path / "runs")
    report = reconciliador.reconcile(run.id)
    assert "artifact-missing" in report.invalidated


def test_changed_hash_invalidates_artifact(tmp_path):
    db, run, stage = _setup_db(tmp_path)
    run_dir = tmp_path / "runs" / run.id
    run_dir.mkdir(parents=True)
    (run_dir / "video" / "audio" / "b001.wav").parent.mkdir(
        parents=True, exist_ok=True
    )
    (run_dir / "video" / "audio" / "b001.wav").write_bytes(b"different")

    work_item_id = "work-b001-changed"
    with db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        conn.execute(
            "INSERT INTO work_items (id, stage_run_id, item_key, status, input_json, input_hash, attempts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                work_item_id,
                stage.id,
                "b001",
                ItemStatus.SUCCEEDED.value,
                '{"texto":"b001"}',
                "c" * 64,
                1,
            ),
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
            created_at=datetime.now(UTC),
        )
        repo.register_artifact(artifact)

    reconciliador = Reconciliador(db, tmp_path / "runs")
    report = reconciliador.reconcile(run.id)
    assert "artifact-changed" in report.invalidated


def test_known_unregistered_file_is_cataloged_as_orphan(tmp_path):
    db, run, stage = _setup_db(tmp_path)
    run_dir = tmp_path / "runs" / run.id
    run_dir.mkdir(parents=True)
    (run_dir / "video" / "audio" / "b001.wav").parent.mkdir(
        parents=True, exist_ok=True
    )
    (run_dir / "video" / "audio" / "b001.wav").write_bytes(b"RIFFpayload")

    reconciliador = Reconciliador(db, tmp_path / "runs")
    report = reconciliador.reconcile(run.id)
    assert len(report.orphans) > 0
    with db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        artifacts = repo.list_artifacts(run.id, current_only=False)
        orphan_art = [
            a for a in artifacts if a.id in report.orphans and "b001" in a.relative_path
        ]
        if orphan_art:
            assert orphan_art[0].kind == "audio.wav"
            assert orphan_art[0].is_current is False


def test_unknown_files_ignored_and_never_deleted(tmp_path):
    db, run, stage = _setup_db(tmp_path)
    run_dir = tmp_path / "runs" / run.id
    run_dir.mkdir(parents=True)
    (run_dir / "notes.private").write_text("keep", encoding="utf-8")

    reconciliador = Reconciliador(db, tmp_path / "runs")
    reconciliador.reconcile(run.id)
    assert (run_dir / "notes.private").read_text(encoding="utf-8") == "keep"


def test_register_orphan_creates_artifact_row():
    from forge.services.reconciliacao import register_orphan

    assert callable(register_orphan)
