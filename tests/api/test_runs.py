from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from forge.api.contracts import CreateVideoRequest
from forge.domain.operacao import RunStatus


def test_create_video_returns_video_and_run(client: TestClient) -> None:
    resp = client.post(
        "/api/videos",
        json={"tema": "meu tema", "priority": 50, "preset": "local-recomendado-v1"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "video" in data
    assert "run" in data
    assert data["video"]["tema"] == "meu tema"
    assert data["run"]["status"] == RunStatus.QUEUED.value
    assert "fluxo_geracao" not in data["run"]["config_snapshot"]


def test_custom_flow_is_listed_and_frozen_in_the_run(client: TestClient) -> None:
    path = "/api/fluxos-geracao"
    catalog = client.get(path).json()
    assert [flow["id"] for flow in catalog] == ["padrao", "comentarios", "gancho-inicial"]
    created = client.post(path, json={
        "nome": "  Dilema moral  ",
        "descricao": "Uma decisão difícil.",
        "instrucoes": "Abra com uma decisão que tem duas respostas plausíveis.",
    })
    assert created.status_code == 201, created.text
    flow = created.json()
    assert flow["nome"] == "Dilema moral"
    assert flow in client.get(path).json()

    queued = client.post("/api/videos", json={"tema": "Coragem", "fluxo_geracao": flow["id"]})
    assert queued.status_code == 201, queued.text
    run = queued.json()["run"]
    detail = client.get(f"/api/runs/{run['id']}").json()
    assert detail["run"]["config_snapshot"]["fluxo_geracao"] == flow


def test_unknown_flow_cannot_enqueue_a_video(client: TestClient) -> None:
    response = client.post("/api/videos", json={"tema": "Coragem", "fluxo_geracao": "outro"})
    assert response.status_code == 422
    assert client.get("/api/queue").json() == []


def test_get_run_not_found(client: TestClient) -> None:
    resp = client.get("/api/runs/nao-existe")
    assert resp.status_code == 404


def test_get_run_ok(client: TestClient) -> None:
    _, rid = _create_video(client, "acesso")
    resp = client.get(f"/api/runs/{rid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["run"]["id"] == rid
    assert data["run"]["status"] == RunStatus.QUEUED.value
    assert data["video"]["tema"] == "acesso"
    assert data["progress"] == 0
    assert data["current_stage"] == "preparacao"
    assert set(data["stages"]) == {
        "preparacao",
        "pesquisa",
        "roteiro",
        "plano_midia",
        "audio",
        "imagens",
        "montagem",
        "validacao",
    }


def test_list_runs_empty(client: TestClient) -> None:
    resp = client.get("/api/runs")
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0


def test_list_runs_after_create(client: TestClient) -> None:
    _create_video(client, "r1")
    _create_video(client, "r2")
    resp = client.get("/api/runs?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 2


def test_pause_requires_idempotency_key(client: TestClient) -> None:
    _, rid = _create_video(client, "pause-test")
    resp = client.post(f"/api/runs/{rid}/pause")
    assert resp.status_code == 422


def test_pause_unknown_run(client: TestClient) -> None:
    # O fixture client já está configurado com o app correto
    # O teste apenas verifica se a rota retorna 404 para run desconhecido
    resp = client.post(
        "/api/runs/unknown/pause",
        headers={"Idempotency-Key": "key-1"},
    )
    assert resp.status_code == 404


def test_retry_stage_invalid_name(client: TestClient) -> None:
    _, rid = _create_video(client)
    resp = client.post(
        f"/api/runs/{rid}/stages/estagio-invalido/retry",
        headers={"Idempotency-Key": "key-retry"},
    )
    assert resp.status_code == 422


def test_retry_stage_unknown_run(client: TestClient, settings) -> None:
    # Precisa criar um run real primeiro para o FK constraint não falhar
    # mas o teste deve ser sobre run desconhecido
    # Usar um UUID que não existe no banco
    fake_rid = "00000000-0000-0000-0000-000000000000"
    resp = client.post(
        f"/api/runs/{fake_rid}/stages/preparacao/retry",
        headers={"Idempotency-Key": "key-rr"},
    )
    assert resp.status_code == 404


def test_retry_stage_requires_idempotency_key(client: TestClient) -> None:
    _, rid = _create_video(client)
    resp = client.post(f"/api/runs/{rid}/stages/preparacao/retry")
    assert resp.status_code == 422


def _create_video(client: TestClient, tema: str = "teste", priority: int = 50):
    resp = client.post(
        "/api/videos",
        json=CreateVideoRequest(tema=tema, priority=priority).model_dump(),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["video"]["id"], body["run"]["id"]
