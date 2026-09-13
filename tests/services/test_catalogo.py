from __future__ import annotations
from pathlib import Path

import hashlib

import pytest

from forge.domain.operacao import Artifact, ItemStatus, StageName
from forge.repositories.operacao import OperacaoRepository
from forge.services.catalogo import (
    CatalogoArtefatos,
    ChildEventProjector,
    ChildProtocolError,
    ALLOWED_MIME,
)
from forge.services.redacao import Redactor


# --- CatalogoArtefatos tests ---

def test_catalog_registers_only_file_inside_run_and_computes_sha(tmp_path, db):
    from services.conftest import prepared_run, child_projector
    _cm = db.connection()
    CatalogoArtefatos._cm_holder.append(_cm)
    conn = _cm.__enter__()
    run_dir, run, stage = prepared_run(tmp_path, db, conn=conn)
    target = run_dir / "video" / "audio" / "b001.wav"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"RIFFpayload")
    artifact = CatalogoArtefatos(db, run_dir, conn=conn).register_file(
        run=run, stage_run=stage, item=None, kind="audio.wav",
        path=target, mime_type="audio/wav", metadata={"sample_rate": 24000},
    )
    assert artifact.relative_path == "video/audio/b001.wav"
    assert artifact.sha256 == hashlib.sha256(b"RIFFpayload").hexdigest()


def test_catalog_rejects_mime_not_in_allowlist(tmp_path, db):
    from services.conftest import prepared_run
    _cm = db.connection()
    CatalogoArtefatos._cm_holder.append(_cm)
    conn = _cm.__enter__()
    run_dir, run, stage = prepared_run(tmp_path, db, conn=conn)
    target = run_dir / "video" / "evil.exe"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"evil")
    with pytest.raises(ValueError, match="MIME"):
        CatalogoArtefatos(db, run_dir, conn=conn).register_file(
            run=run, stage_run=stage, item=None,
            kind="evil.exe", path=target, mime_type="application/x-msdownload",
            metadata={},
        )


def test_catalog_rejects_path_outside_run(tmp_path, db):
    from services.conftest import prepared_run
    _cm = db.connection()
    CatalogoArtefatos._cm_holder.append(_cm)
    conn = _cm.__enter__()
    run_dir, run, stage = prepared_run(tmp_path, db, conn=conn)
    with pytest.raises(ValueError, match="outside"):
        CatalogoArtefatos(db, run_dir, conn=conn).register_file(
            run=run, stage_run=stage, item=None,
            kind="audio.wav", path=Path("/tmp/evil.wav"),
            mime_type="audio/wav", metadata={},
        )


# --- ChildEventProjector tests ---

def test_projector_rejects_unknown_item_key(tmp_path, db):
    from services.conftest import child_projector
    projector = child_projector(tmp_path, db)
    with pytest.raises(ChildProtocolError, match="unknown item_key"):
        projector.project("item.succeeded", {"item_key": "ghost", "duration_ms": 1})


def test_projector_rejects_path_escape(tmp_path, db):
    from services.conftest import child_projector
    projector = child_projector(tmp_path, db)
    with pytest.raises(ChildProtocolError, match="outside run_dir"):
        projector.project("artifact.created", {
            "item_key": None, "kind": "x", "relative_path": "../escape",
            "mime_type": "application/json", "metadata": {},
        })


def test_projector_rejects_unallowed_mime(tmp_path, db):
    from services.conftest import child_projector
    projector = child_projector(tmp_path, db)
    with pytest.raises(ValueError, match="MIME"):
        projector.project("artifact.created", {
            "item_key": None, "kind": "x", "relative_path": "video/x.evil",
            "mime_type": "application/x-msdownload", "metadata": {},
        })


def test_projector_allows_markdown_artifact_from_research(tmp_path, db):
    from services.conftest import child_projector

    projector = child_projector(tmp_path, db)

    projector.project("artifact.created", {
        "item_key": "", "kind": "research",
        "relative_path": "01-research.md",
        "mime_type": "text/markdown", "metadata": {"passage_count": 2},
    })


def test_projector_rejects_missing_item_key_on_artifact(tmp_path, db):
    from services.conftest import child_projector
    projector = child_projector(tmp_path, db)
    with pytest.raises(ChildProtocolError, match="unknown item_key"):
        projector.project("artifact.created", {
            "item_key": None, "kind": "audio.wav",
            "relative_path": "video/audio/b001.wav",
            "mime_type": "audio/wav", "metadata": {},
        })


def test_projector_allows_known_item_key_on_artifact(tmp_path, db):
    from services.conftest import child_projector, item_plan, audio_stage
    _cm = db.connection()
    ChildEventProjector._cm_holder.append(_cm)
    conn = _cm.__enter__()
    repo, run, stage = audio_stage(conn)
    repo.upsert_work_items(stage.id, [item_plan("b001", "abc")])
    projector = child_projector(tmp_path, db, conn=conn, run=run, stage=stage)
    projector.project("artifact.created", {
        "item_key": "b001", "kind": "audio.wav",
        "relative_path": "video/audio/b001.wav",
        "mime_type": "audio/wav", "metadata": {},
    })


def test_projector_creates_media_item_in_destination_stage(tmp_path, db):
    from services.conftest import prepared_run

    _cm = db.connection()
    ChildEventProjector._cm_holder.append(_cm)
    conn = _cm.__enter__()
    run_dir, run, _ = prepared_run(tmp_path, db, conn=conn)
    repo = OperacaoRepository(conn)
    media_stage = next(
        item for item in repo.current_stages(run.id) if item.stage is StageName.PLANO_MIDIA
    )
    audio_stage = next(
        item for item in repo.current_stages(run.id) if item.stage is StageName.AUDIO
    )
    projector = ChildEventProjector(db, run_dir, media_stage.id, conn=conn)
    projector.project("item.planned", {
        "item_key": "b001", "kind": "audio", "stage": "audio",
        "input": {"id": "b001", "secao": "Gancho", "texto": "fala"},
        "input_hash": "a" * 64,
    })

    created = repo.list_work_items(audio_stage.id)
    media_items = repo.list_work_items(media_stage.id)

    assert len(created) == 1
    assert created[0].item_key == "b001"
    assert created[0].status is ItemStatus.PENDING
    assert media_items == []


def test_projector_transitions_item_started_succeeded_and_failed(tmp_path, db):
    from services.conftest import prepared_run, item_plan

    _cm = db.connection()
    ChildEventProjector._cm_holder.append(_cm)
    conn = _cm.__enter__()
    run_dir, run, audio_stage = prepared_run(tmp_path, db, conn=conn)
    repo = OperacaoRepository(conn)
    repo.upsert_work_items(audio_stage.id, [
        item_plan("b001", "a" * 64), item_plan("b002", "b" * 64),
    ])
    projector = ChildEventProjector(db, run_dir, audio_stage.id, conn=conn)

    with pytest.raises(ChildProtocolError, match="invalid transition"):
        projector.project("item.succeeded", {"item_key": "b001", "duration_ms": 900})
    with pytest.raises(ChildProtocolError, match="invalid transition"):
        projector.project("item.failed", {
            "item_key": "b001", "failure_code": "item_failed",
            "failure_message": "cedo demais",
        })
    projector.project("item.started", {"item_key": "b001", "duration_ms": 0})
    running = repo.list_work_items(audio_stage.id)[0]
    projector.project("item.succeeded", {"item_key": "b001", "duration_ms": 900})
    succeeded = repo.list_work_items(audio_stage.id)[0]
    with pytest.raises(ChildProtocolError, match="invalid transition"):
        projector.project("item.failed", {
            "item_key": "b001", "failure_code": "item_failed",
            "failure_message": "tarde demais",
        })

    # A failure event is terminal and must remain representable for retry.
    projector.project("item.started", {"item_key": "b002", "duration_ms": 0})
    projector.project("item.failed", {
        "item_key": "b002", "failure_code": "item_failed",
        "failure_message": "tts morreu",
    })
    failed = repo.list_work_items(audio_stage.id)[1]

    assert running.status is ItemStatus.RUNNING
    assert running.attempts == 1
    assert succeeded.status is ItemStatus.SUCCEEDED
    assert succeeded.duration_ms == 900
    assert failed.status is ItemStatus.FAILED
    assert failed.failure_code == "item_failed"
    with pytest.raises(ChildProtocolError, match="invalid transition"):
        projector.project("item.succeeded", {"item_key": "b002", "duration_ms": 901})


# --- Redactor tests ---

def test_event_redactor_masks_exact_secret_values():
    redactor = Redactor(secrets=["sk-live-123"])
    assert redactor.clean({
        "message": "falhou com sk-live-123", "api_key": "another",
        "nested": ["safe", "token sk-live-123"],
    }) == {
        "message": "falhou com [REDACTED]", "api_key": "[REDACTED]",
        "nested": ["safe", "token [REDACTED]"],
    }


def test_event_redactor_masks_credential_keys():
    redactor = Redactor(secrets=[])
    assert redactor.clean({
        "token": "abc", "authorization": "bearer x", "password": "secret",
        "safe": "ok",
    }) == {
        "token": "[REDACTED]", "authorization": "[REDACTED]",
        "password": "[REDACTED]", "safe": "ok",
    }


def test_event_redactor_is_recursive():
    redactor = Redactor(secrets=["top-secret"])
    assert redactor.clean({
        "outer": {"inner": {"token": "top-secret", "value": "ok"}},
    }) == {
        "outer": {"inner": {"token": "[REDACTED]", "value": "ok"}},
    }


def test_event_redactor_does_not_modify_safe_values():
    redactor = Redactor(secrets=["secret"])
    data = {"message": "hello", "count": 42, "name": "world"}
    assert redactor.clean(data) == data


def test_event_redactor_masks_substring_in_message():
    redactor = Redactor(secrets=["sk-abc"])
    assert redactor.clean({
        "message": "key is sk-abc here",
    }) == {
        "message": "key is [REDACTED] here",
    }
