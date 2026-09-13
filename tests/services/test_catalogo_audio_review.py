from __future__ import annotations

import hashlib
import wave
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

from forge.domain.operacao import Artifact, ItemStatus, StageName
from forge.repositories.connection import Database
from forge.repositories.eventos import EventosRepository
from forge.repositories.operacao import OperacaoRepository
from forge.repositories.schema import init_db
from forge.services.catalogo import ChildEventProjector, ChildProtocolError
from forge.services.worker import StageContext, StudioWorker


def _wav(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24000)
        output.writeframes(b"\0\0" * 2400)
    return path


def _run_with_audio_item(tmp_path: Path):
    db = Database(tmp_path / "forge.db")
    init_db(db)
    with db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        _, run = repo.create_video_and_run(
            tema="Tema", tese="Tese", priority=50, config_snapshot={},
            workflow_version=2, git_commit="abc123",
        )
        stage = next(item for item in repo.current_stages(run.id) if item.stage is StageName.AUDIO)
        repo.upsert_work_items(stage.id, [{
            "item_key": "b001", "input": {"texto": "Texto"}, "input_hash": "a" * 64,
        }])
        item = repo.list_work_items(stage.id)[0]
    run_dir = tmp_path / "runs" / run.id
    run_dir.mkdir(parents=True)
    return db, run_dir, run, stage, item


def test_worker_projects_audio_artifact_to_current_catalog_before_audit_event(tmp_path):
    db, run_dir, run, stage, item = _run_with_audio_item(tmp_path)
    path = _wav(run_dir / "video" / "audio" / "b001.wav")
    worker = StudioWorker(db, worker_id="worker-a", lease_seconds=60, executors={})

    worker._event_sink(StageContext(run=run, stage_run=stage, run_dir=run_dir, work_items=[item]))(
        kind="artifact.created", level="info", message="Áudio criado", payload={
            "item_key": "b001", "kind": "audio.wav", "relative_path": "video/audio/b001.wav",
            "mime_type": "audio/wav", "metadata": {"seed": 42},
        }
    )

    with db.connection() as conn:
        artifacts = OperacaoRepository(conn).list_artifacts(run.id)
        events = EventosRepository(conn).after(0, run_id=run.id)
    assert len(artifacts) == 1
    assert artifacts[0].work_item_id == item.id
    assert artifacts[0].sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert artifacts[0].size_bytes == path.stat().st_size
    assert [event.kind for event in events] == ["artifact.created"]


def test_catalog_find_reusable_output_requires_intact_prior_current_item(tmp_path):
    from forge.services.catalogo import CatalogoArtefatos

    db, run_dir, run, stage, item = _run_with_audio_item(tmp_path)
    path = _wav(run_dir / "video" / "audio" / "b001.wav")
    with db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        conn.execute("UPDATE work_items SET status = ? WHERE id = ?", ("succeeded", item.id))
        artifact = repo.register_artifact(Artifact(
            id="prior-audio", run_id=run.id, stage_run_id=stage.id, work_item_id=item.id,
            kind="audio.wav", relative_path="video/audio/b001.wav",
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(), size_bytes=path.stat().st_size,
            mime_type="audio/wav", metadata={}, is_current=True,
            created_at=datetime.now(UTC),
        ))
        conn.execute(
            "INSERT INTO stage_runs (id, run_id, stage, attempt, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("audio-attempt-2", run.id, "audio", 2, "pending", datetime.now(UTC).isoformat()),
        )

    found = CatalogoArtefatos(db, run_dir).find_reusable_output(
        run_id=run.id, stage=StageName.AUDIO, item_key="b001", input_hash="a" * 64,
        current_stage_run_id="audio-attempt-2",
    )

    assert found is not None
    assert found.id == artifact.id


def test_projector_rejects_path_escape_without_creating_artifact(tmp_path):
    db, run_dir, run, stage, item = _run_with_audio_item(tmp_path)
    outside = _wav(tmp_path / "outside.wav")
    projector = ChildEventProjector(db, run_dir, stage.id)

    with pytest.raises(ChildProtocolError, match="outside"):
        projector.project("artifact.created", {
            "item_key": item.item_key, "kind": "audio.wav", "relative_path": "../outside.wav",
            "mime_type": "audio/wav", "metadata": {},
        })

    with db.connection() as conn:
        assert OperacaoRepository(conn).list_artifacts(run.id) == []
    assert outside.is_file()


def test_audio_child_events_project_without_invalid_transitions_or_duplicate_terminals(tmp_path):
    from forge.domain.execucao import RunSnapshot
    from forge.domain.midia import BlocoNarracao, PlanoMidia
    from forge.executors.audio import AudioExecutor
    from forge.executors.audio_generate import AudioOutcome
    from forge.infrastructure.config import Settings
    from forge.services.persistencia import gravar_modelo

    db, run_dir, run, stage, _ = _run_with_audio_item(tmp_path)
    with db.transaction(immediate=True) as conn:
        conn.execute("DELETE FROM work_items WHERE stage_run_id = ?", (stage.id,))
    snapshot = RunSnapshot(
        run_id=run.id, video_id=run.video_id, tema="Tema", tese="Tese", stage=StageName.AUDIO,
        attempt=stage.attempt, output_root=run_dir.parent, run_dir=run_dir, config_snapshot={},
        artifacts=[], work_items=[], reusable_outputs=[],
    )
    gravar_modelo(run_dir / "video" / "midia.json", PlanoMidia(blocos=[
        BlocoNarracao(id="b001", secao="A", texto="Texto"),
    ]))

    class Client:
        def synthesize_batch(self, items, output_dir):
            return [AudioOutcome.succeeded(item.item_key, _wav(output_dir / f"{item.item_key}.wav")) for item in items]

    class Broker:
        @contextmanager
        def exclusivo(self, resource):
            yield

    events = []
    result = AudioExecutor(
        settings=Settings(_env_file=None, audio_generate_dir=tmp_path / "audio-generate"),
        client=Client(), broker=Broker(),
    ).run(snapshot, lambda **event: events.append(event))
    projector = ChildEventProjector(db, run_dir, stage.id)
    for event in events:
        projector.project(event["kind"], event["payload"])

    terminals = [event for event in events if event["kind"] in {"item.succeeded", "item.failed"}]
    with db.connection() as conn:
        persisted = OperacaoRepository(conn).list_work_items(stage.id)
    assert result.gate.approved
    assert [event["kind"] for event in events if event["kind"].startswith("item.")] == [
        "item.planned", "item.started", "item.succeeded"
    ]
    assert len(terminals) == 1
    assert persisted[0].status is ItemStatus.SUCCEEDED
