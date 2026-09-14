from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from forge.api.contracts import CreateVideoRequest
from forge.domain.operacao import RunStatus
from forge.repositories.operacao import OperacaoRepository


def _create_imported_run(services, *, tema: str = "legado") -> str:
    """Cria uma run importada (somente-leitura) no banco do serviço."""
    with services.commands.db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        _, run = repo.create_imported_video_and_run(
            tema=tema,
            tese=None,
            config_snapshot={"legacy_import": True},
            git_commit="legacy-import",
            run_id=str(uuid.uuid4()),
        )
    return run.id


def test_imported_run_is_exposed_as_read_only_in_detail(client: TestClient, services) -> None:
    run_id = _create_imported_run(services)

    resp = client.get(f"/api/runs/{run_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["run"]["is_read_only"] is True
    assert data["run"]["status"] == RunStatus.COMPLETED.value


def test_imported_run_is_exposed_as_read_only_in_listing(client: TestClient, services) -> None:
    run_id = _create_imported_run(services, tema="legado-list")

    resp = client.get("/api/runs?limit=10")

    assert resp.status_code == 200
    item = next(
        entry for entry in resp.json()["items"] if entry["run"]["id"] == run_id
    )
    assert item["run"]["is_read_only"] is True


def test_normal_run_is_not_read_only(client: TestClient) -> None:
    resp = client.post(
        "/api/videos",
        json=CreateVideoRequest(tema="novo", priority=50).model_dump(),
    )
    assert resp.status_code == 201

    run_id = resp.json()["run"]["id"]
    detail = client.get(f"/api/runs/{run_id}").json()
    assert detail["run"]["is_read_only"] is False


@pytest.mark.parametrize(
    ("method", "suffix"),
    [
        ("pause", "pause"),
        ("resume", "resume"),
    ],
)
def test_commands_on_imported_run_return_409(
    client: TestClient, services, method: str, suffix: str
) -> None:
    run_id = _create_imported_run(services)

    resp = client.post(
        f"/api/runs/{run_id}/{suffix}",
        headers={"Idempotency-Key": f"{method}-legado"},
    )

    assert resp.status_code == 409
    assert resp.json()["detail"]["error"]["code"] == "read_only"


def test_retry_on_imported_run_returns_409(client: TestClient, services) -> None:
    run_id = _create_imported_run(services)

    resp = client.post(
        f"/api/runs/{run_id}/stages/roteiro/retry",
        headers={"Idempotency-Key": "retry-legado"},
    )

    assert resp.status_code == 409
    assert resp.json()["detail"]["error"]["code"] == "read_only"
