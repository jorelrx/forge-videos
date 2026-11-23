from __future__ import annotations

import hashlib
import wave
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

from forge.domain.operacao import Artifact, ItemStatus, RunStatus, StageName
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


def test_catalog_reuses_intact_succeeded_item_after_retry_invalidates_its_artifact(tmp_path):
    from forge.domain.execucao import WorkItemPlan
    from forge.services.catalogo import CatalogoArtefatos
    from forge.services.control_plane import ControlPlaneService

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
        repo.save_run(run.model_copy(update={"status": RunStatus.FAILED}))

    ControlPlaneService(db).request_retry_stage(
        run.id, StageName.AUDIO, idempotency_key="retry-audio-for-reuse",
    )
    with db.connection() as conn:
        current_stage = next(
            candidate for candidate in OperacaoRepository(conn).current_stages(run.id)
            if candidate.stage is StageName.AUDIO
        )
        prior = next(
            candidate for candidate in OperacaoRepository(conn).list_artifacts(run.id, current_only=False)
            if candidate.id == artifact.id
        )
    assert current_stage.attempt == 2
    assert prior.is_current is False

    catalog = CatalogoArtefatos(db, run_dir)
    outputs = catalog.reusable_outputs(
        run_id=run.id, stage=StageName.AUDIO, current_stage_run_id=current_stage.id,
        items=[WorkItemPlan(item_key="b001", input={"texto": "Texto"}, input_hash="a" * 64)],
    )

    assert len(outputs) == 1
    assert outputs[0].artifact.id == artifact.id
    assert outputs[0].artifact.is_current is False

    assert catalog.reusable_outputs(
        run_id=run.id, stage=StageName.AUDIO, current_stage_run_id=current_stage.id,
        items=[WorkItemPlan(item_key="b001", input={"texto": "Texto"}, input_hash="b" * 64)],
    ) == []

    path.write_bytes(b"corrompido")
    assert catalog.reusable_outputs(
        run_id=run.id, stage=StageName.AUDIO, current_stage_run_id=current_stage.id,
        items=[WorkItemPlan(item_key="b001", input={"texto": "Texto"}, input_hash="a" * 64)],
    ) == []


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


def test_projector_accepts_stage_artifact_with_omitted_item_key(tmp_path):
    db, run_dir, run, stage, _ = _run_with_audio_item(tmp_path)
    path = run_dir / "video" / "stage-input.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    projector = ChildEventProjector(db, run_dir, stage.id)

    projector.project("artifact.created", {
        "kind": "stage.input", "relative_path": "video/stage-input.json",
        "mime_type": "application/json", "metadata": {},
    })

    with db.connection() as conn:
        artifacts = OperacaoRepository(conn).list_artifacts(run.id)
    assert len(artifacts) == 1
    assert artifacts[0].stage_run_id == stage.id
    assert artifacts[0].work_item_id is None


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
        def synthesize(self, request, servidor, output_dir):
            return AudioOutcome.succeeded(request.item_key, _wav(output_dir / f"{request.item_key}.wav"))

    class Servidor:
        url = "falso://vulkan"
        backend = "vulkan"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

    class Broker:
        @contextmanager
        def exclusivo(self, resource):
            yield

    events = []
    result = AudioExecutor(
        settings=Settings(_env_file=None, audio_generate_dir=tmp_path / "audio-generate"),
        client=Client(), broker=Broker(), servidor_factory=lambda backend, pasta: Servidor(),
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
