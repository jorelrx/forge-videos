from __future__ import annotations

import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from forge.api.app import create_app, ApiServices
from forge.api.contracts import CreateVideoRequest
from forge.domain.operacao import RunStatus, StageName, StageRun, StageStatus
from forge.infrastructure.config import Settings
from forge.repositories.connection import Database
from forge.repositories.operacao import OperacaoRepository
from forge.services.control_plane import ControlPlaneService
from forge.services.studio_query import StudioQueryService
from forge.services.saude import StudioHealthService
from forge.services.saude import _default_probes as _health_probes
from forge.repositories.schema import init_db
import uuid
from datetime import datetime, timezone


def _make_services(settings: Settings) -> ApiServices:
    db = Database(str(settings.studio_db_path))
    init_db(db)
    return ApiServices(
        settings=settings,
        commands=ControlPlaneService(db),
        queries=StudioQueryService(db),
        health=StudioHealthService(probes=_health_probes()),
        git_commit="test-sha",
        workflow_version=1,
    )


def _create_video(client: TestClient, tema: str = "teste", priority: int = 50):
    resp = client.post(
        "/api/videos",
        json=CreateVideoRequest(tema=tema, priority=priority).model_dump(),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["video"]["id"], body["run"]["id"]


def test_continuity_after_api_restart(
    client: TestClient, settings: Settings
) -> None:
    _, rid = _create_video(client, "persistente")

    db = Database(str(settings.studio_db_path))
    queries = StudioQueryService(db)
    commands = ControlPlaneService(db)
    services2 = ApiServices(
        settings=settings,
        commands=commands,
        queries=queries,
        health=StudioHealthService(probes=_health_probes()),
        git_commit="test-sha",
        workflow_version=1,
    )
    app2 = create_app(services2)
    client2 = TestClient(app2, cookies=client.cookies)

    resp = client2.get(f"/api/runs/{rid}")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["run"]["id"] == rid
    assert data["run"]["status"] == RunStatus.QUEUED.value


def test_sse_replay_after_reconnect(
    client: TestClient, settings: Settings
) -> None:
    from forge.api.sse import iter_sse_events, ServerSentEvent

    _, rid = _create_video(client, "sse-test")

    db = Database(str(settings.studio_db_path))
    queries = StudioQueryService(db)
    events = queries.events_after(cursor=0, run_id=rid, limit=10)
    assert len(events) > 0
    first_id = events[0].id

    stream = iter_sse_events(
        queries,
        cursor=first_id - 1,
        run_id=rid,
        poll_seconds=0.01,
        keepalive_seconds=0.02,
        sleep=lambda _: None,
    )
    # Pular keep-alives até chegar no evento real
    event = next(stream)
    while event.comment is not None:
        event = next(stream)
    assert event.id == str(first_id)
    assert event.data["kind"] == "run.queued"


def test_command_idempotency(
    client: TestClient, settings: Settings
) -> None:
    _, rid = _create_video(client, "idempotency")

    db = Database(str(settings.studio_db_path))
    with db.connection() as conn:
        repo = OperacaoRepository(conn)
        with db.transaction(immediate=True):
            pass
        run = repo.get_run(rid)
        if run is not None and run.status == RunStatus.QUEUED:
            repo.save_run(
                run.model_copy(
                    update={"status": RunStatus.PREPARING}
                )
            )

    key = "test-idempotency-key"
    r1 = client.post(
        f"/api/runs/{rid}/pause",
        headers={"Idempotency-Key": key},
    )
    r2 = client.post(
        f"/api/runs/{rid}/pause",
        headers={"Idempotency-Key": key},
    )

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]


def test_secure_preview(
    client: TestClient, settings: Settings
) -> None:
    _, rid = _create_video(client, "preview")

    run_root = Path(settings.studio_runs_dir) / rid
    run_root.mkdir(parents=True, exist_ok=True)
    file_path = run_root / "informe.md"
    file_path.write_bytes(b"# Interno\ndados sensiveis\n")

    db = Database(str(settings.studio_db_path))
    artifact_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    with db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        # Use existing stage_run from the run (created by create_video_and_run)
        existing_stages = repo.current_stages(rid)
        assert existing_stages, "run should have stages"
        stage_run_id = existing_stages[0].id
        conn.execute(
            """INSERT INTO artifacts (
                id, run_id, stage_run_id, work_item_id, kind, relative_path, sha256,
                size_bytes, mime_type, metadata_json, is_current, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                artifact_id,
                rid,
                stage_run_id,
                None,
                "document",
                "informe.md",
                "sha256hash",
                len(b"# Interno\ndados sensiveis\n"),
                "text/markdown",
                "{}",
                1,
                now,
            ),
        )

    resp = client.get(f"/api/artifacts/{artifact_id}/content")
    assert resp.status_code == 200
    assert resp.content == b"# Interno\ndados sensiveis\n"


def test_ordered_queue(client: TestClient) -> None:
    _, id1 = _create_video(client, "baixa", priority=10)
    _, id2 = _create_video(client, "alta", priority=90)
    _, id3 = _create_video(client, "media", priority=50)

    resp = client.get("/api/queue")
    assert resp.status_code == 200
    queue = resp.json()

    assert len(queue) == 3
    priorities = [item["run"]["priority"] for item in queue]
    assert priorities == sorted(priorities, reverse=True)
