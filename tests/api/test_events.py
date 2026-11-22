from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from forge.api.contracts import CreateVideoRequest
from forge.infrastructure.config import Settings
from forge.repositories.connection import Database
from forge.repositories.schema import init_db
from forge.repositories.operacao import OperacaoRepository
from datetime import UTC, datetime
import uuid


def test_event_history_not_found(client: TestClient) -> None:
    resp = client.get("/api/runs/fake/events")
    assert resp.status_code == 404


def test_event_history_empty(client: TestClient, settings: Settings) -> None:
    # Cria um run diretamente no mesmo banco do fixture (para garantir lista vazia)
    db = Database(str(settings.studio_db_path))
    init_db(db)

    with db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        video_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        conn.execute(
            "INSERT INTO videos (id, tema, tese, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (video_id, "teste", None, now.isoformat(), now.isoformat()),
        )
        conn.execute(
            """INSERT INTO runs (id, video_id, status, priority, queue_position, config_snapshot_json,
                workflow_version, git_commit, created_at, canal_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'UC1')""",
            (run_id, video_id, "queued", 50, 1, "{}", 1, "test", now.isoformat()),
        )

    resp = client.get(f"/api/runs/{run_id}/events")
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["next_before_id"] is None


def test_event_history_has_run_queued_event(client: TestClient) -> None:
    rid = _create_video(client, "com-evento")
    resp = client.get(f"/api/runs/{rid}/events?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    kinds = {item["kind"] for item in data["items"]}
    assert "run.queued" in kinds


def test_event_history_pagination(client: TestClient) -> None:
    rid = _create_video(client, "pagination")
    resp = client.get(f"/api/runs/{rid}/events?limit=1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    if data["next_before_id"] is not None:
        assert isinstance(data["next_before_id"], int)


def _create_video(client: TestClient, tema: str = "eventos"):
    resp = client.post(
        "/api/videos",
        json=CreateVideoRequest(tema=tema).model_dump(),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["run"]["id"]
