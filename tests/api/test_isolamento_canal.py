import pytest
from fastapi.testclient import TestClient

from forge.api.app import create_app


def test_dados_privados_exigem_sessao(services):
    api = TestClient(create_app(services))
    for url in ("/api/runs", "/api/queue", "/api/fluxos-geracao", "/api/config/effective",
                "/api/runs/desconhecida/events", "/api/artifacts/teste/content"):
        assert api.get(url).status_code == 401, url


def test_fila_total_e_eventos_limitados_ao_canal(client, services):
    outra = services.commands.enqueue_video(tema="privado", tese=None, priority=100,
        config_snapshot={}, workflow_version=1, git_commit="teste", canal_id="outro")[1]
    minha = client.post("/api/videos", json={"tema": "autorizado"}).json()["run"]["id"]
    pagina = client.get("/api/runs?limit=1").json()
    assert pagina["total"] == 1
    assert pagina["items"][0]["run"]["id"] == minha
    assert [item["run"]["id"] for item in client.get("/api/queue").json()] == [minha]
    assert [e.run_id for e in services.queries.events_after(0, canal_id="UC1")] == [minha]
    assert client.get(f"/api/runs/{outra.id}").status_code == 404
    assert client.get("/api/runs?canal_id=outro").status_code == 404


@pytest.mark.parametrize(("method", "path"), [
    ("get", "artifacts"), ("get", "publication"), ("get", "desempenho"),
    ("get", "events"), ("post", "pause"), ("post", "resume"),
    ("post", "stages/roteiro/retry"),
])
def test_recurso_de_outro_canal(client, services, method, path):
    run = services.commands.enqueue_video(tema="B", tese=None, priority=50,
        config_snapshot={}, workflow_version=1, git_commit="teste", canal_id="B")[1]
    assert client.request(method, f"/api/runs/{run.id}/{path}").status_code == 404


def test_arquivo_range_e_download_seguem_a_run(client, services, create_video, register_artifact):
    from .conftest import autenticar

    run_id = create_video()["run"]["id"]
    arquivo = register_artifact(run_id, relative_path="video/final.mp4",
                                mime_type="video/mp4", content=b"123456")
    outro = autenticar(TestClient(create_app(services)), services, conta="outra", canais=("B",))
    url = f"/api/artifacts/{arquivo.id}/content"
    assert client.get(url, headers={"Range": "bytes=0-1"}).content == b"12"
    for sufixo in ("", "?download=1"):
        assert outro.get(url+sufixo, headers={"Range": "bytes=0-1"}).status_code == 404
    assert client.get(url+"?canal_id=B").status_code == 404


def test_stream_aberto_encerra_apos_logout(client, services, create_video):
    import asyncio
    from starlette.requests import Request
    from forge.api.routes.events import _sse_body

    rid = create_video()["run"]["id"]
    cookie = next(iter(client.cookies.values()))
    request = Request({"type": "http", "app": client.app, "headers": [
        (b"cookie", f"forge_sessao={cookie}".encode())]})

    async def ler():
        stream = _sse_body(request, 0, rid, "UC1")
        assert b"run.queued" in await anext(stream)
        assert client.post("/api/sessao/sair").status_code == 204
        with pytest.raises(StopAsyncIteration):
            await anext(stream)

    asyncio.run(ler())
