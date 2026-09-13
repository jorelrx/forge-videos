from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from forge.domain.operacao import (
    Artifact,
    ItemStatus,
    Run,
    StageName,
    StageRun,
    WorkItem,
)
from forge.repositories.connection import Database
from forge.repositories.operacao import OperacaoRepository
from forge.repositories.schema import init_db

FIXED_NOW = datetime(2026, 9, 12, 15, 30, tzinfo=UTC)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "forge.db")
    init_db(database)
    return database


@pytest.fixture
def projectors_conn(db: Database):
    conn = db.connection().__enter__()
    yield conn
    conn.close()


def audio_stage(conn: sqlite3.Connection) -> tuple[OperacaoRepository, Run, StageRun]:
    repo = OperacaoRepository(conn)
    video, run = repo.create_video_and_run(
        tema="AudioTest",
        tese="Tese",
        priority=50,
        config_snapshot={},
        workflow_version=2,
        git_commit="abc123",
    )
    stage = next(
        s for s in repo.current_stages(run.id) if s.stage is StageName.AUDIO
    )
    return repo, run, stage


def item_plan(item_key: str, input_hash: str) -> dict:
    return {
        "item_key": item_key,
        "input": {"texto": item_key},
        "input_hash": input_hash,
    }


def retried_audio_stage(
    tmp_path: Path, db: Database
) -> tuple[Path, Run, StageRun, StageRun]:
    with db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        video, run = repo.create_video_and_run(
            tema="RetryTest",
            tese="Tese",
            priority=50,
            config_snapshot={},
            workflow_version=2,
            git_commit="abc123",
        )
        old_stage = next(
            s for s in repo.current_stages(run.id) if s.stage is StageName.AUDIO
        )
    run_dir = tmp_path / "runs" / run.id
    run_dir.mkdir(parents=True)
    new_stage = old_stage
    return run_dir, run, old_stage, new_stage


def succeeded_audio_item(
    run_dir: Path,
    run: Run,
    stage: StageRun,
    input_hash: str,
) -> tuple[WorkItem, Artifact]:
    db_path = run_dir.parent / "forge.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        repo = OperacaoRepository(conn)
        artifact_id = "artifact-audio"
        artifact = Artifact(
            id=artifact_id,
            run_id=run.id,
            stage_run_id=stage.id,
            work_item_id=None,
            kind="audio.wav",
            relative_path="video/audio/b001.wav",
            sha256=hashlib.sha256(b"RIFFpayload").hexdigest(),
            size_bytes=123,
            mime_type="audio/wav",
            metadata={"sample_rate": 24000},
            is_current=True,
            created_at=FIXED_NOW,
        )
        work_item = WorkItem(
            id="work-b001",
            stage_run_id=stage.id,
            item_key="b001",
            status=ItemStatus.SUCCEEDED,
            input={"texto": "b001"},
            input_hash=input_hash,
            attempts=1,
            duration_ms=900,
            created_at=FIXED_NOW,
        )
        repo.register_artifact(artifact)
        return work_item, artifact
    finally:
        conn.close()


def prepared_run(
    tmp_path: Path, db: Database, conn: sqlite3.Connection | None = None
) -> tuple[Path, Run, StageRun]:
    if conn is None:
        conn = db.connection().__enter__()
    repo = OperacaoRepository(conn)
    video, run = repo.create_video_and_run(
        tema="PreparedTest",
        tese="Tese",
        priority=50,
        config_snapshot={},
        workflow_version=2,
        git_commit="abc123",
    )
    stage = next(
        s for s in repo.current_stages(run.id) if s.stage is StageName.AUDIO
    )
    run_dir = tmp_path / "runs" / run.id
    run_dir.mkdir(parents=True)
    return run_dir, run, stage


def child_projector(tmp_path: Path, db: Database, conn: sqlite3.Connection | None = None, run=None, stage=None) -> ChildEventProjector:
    from forge.services.catalogo import ChildEventProjector
    from forge.repositories.operacao import OperacaoRepository

    if conn is None:
        _cm = db.connection()
        ChildEventProjector._cm_holder.append(_cm)
        conn = _cm.__enter__()
    repo = OperacaoRepository(conn)
    if run is None or stage is None:
        video, run = repo.create_video_and_run(
            tema="ProjectorTest",
            tese="Tese",
            priority=50,
            config_snapshot={},
            workflow_version=2,
            git_commit="abc123",
        )
        stage = next(
            s for s in repo.current_stages(run.id) if s.stage is StageName.AUDIO
        )
    run_dir = tmp_path / "runs" / run.id
    run_dir.mkdir(parents=True)
    return ChildEventProjector(db, run_dir, stage.id, conn=conn)


def audio_items_and_artifacts(
    tmp_path: Path, db: Database
) -> tuple[Path, Run, StageRun, WorkItem, Artifact]:
    run_dir, run, stage = prepared_run(tmp_path, db)
    conn = sqlite3.connect(run_dir.parent / "forge.db")
    conn.row_factory = sqlite3.Row
    try:
        repo = OperacaoRepository(conn)
        work_item = WorkItem(
            id="work-b001",
            stage_run_id=stage.id,
            item_key="b001",
            status=ItemStatus.PENDING,
            input={"texto": "b001"},
            input_hash="a" * 64,
            attempts=1,
            created_at=FIXED_NOW,
        )
        artifact = Artifact(
            id="artifact-audio",
            run_id=run.id,
            stage_run_id=stage.id,
            work_item_id=work_item.id,
            kind="audio.wav",
            relative_path="video/audio/b001.wav",
            sha256=hashlib.sha256(b"RIFFpayload").hexdigest(),
            size_bytes=123,
            mime_type="audio/wav",
            metadata={"sample_rate": 24000},
            is_current=True,
            created_at=FIXED_NOW,
        )
        repo.register_artifact(artifact)
    finally:
        conn.close()
    return run_dir, run, stage, work_item, artifact
