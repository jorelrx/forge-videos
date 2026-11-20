from __future__ import annotations

import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from forge.api.app import create_app


def run_pronta(settings, run_id="run-1", aprovado=True):
    video = settings.studio_runs_dir / run_id / "video"
    video.mkdir(parents=True)
    (video / "final.mp4").write_bytes(b"x" * 10)
    (video / "thumbnail.jpg").write_bytes(b"\xff\xd8")
    (video / "legendas.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nOi\n", encoding="utf-8")
    (video / "validation.json").write_text(json.dumps({"approved": aprovado}), encoding="utf-8")
    (video / "embalagem.json").write_text(json.dumps({
        "titulos": [{"texto": "Título A"}], "thumbnail": {"texto": "x", "prompt": "y"},
        "descricao": "d", "tags": [],
    }), encoding="utf-8")
    return settings.studio_runs_dir / run_id


class FakeCliente:
    def iniciar_upload(self, metadados, tamanho):
        return "https://sessao"

    def enviar_arquivo(self, sessao, arquivo, *, inicio, ao_avancar=None):
        return {"id": "vid9"}

    def definir_thumbnail(self, video_id, caminho):
        pass

    def enviar_legenda(self, video_id, caminho, *, idioma, nome):
        pass


class FakeCanais:
    def __init__(self, ids=("UC1", "UC2"), padrao="UC1"):
        self.ids = list(ids)
        self._padrao = padrao if ids else None
        self.pedidos = []

    def listar(self):
        return self.ids

    def padrao(self):
        return self._padrao

    def titulo(self, canal_id):
        return {"UC1": "Canal Um", "UC2": "Canal Dois"}.get(canal_id)

    def credenciais(self, canal_id):
        if canal_id not in self.ids:
            raise KeyError(canal_id)
        self.pedidos.append(canal_id)
        return f"credenciais-{canal_id}"


def cliente_api(services, settings, *, conectado=True, cliente=None, sincrono=True, canais=None):
    from forge.services.publicacao import Publicador
    canais = canais or FakeCanais(ids=("UC1", "UC2") if conectado else ())
    publicador = Publicador(
        settings, canais=canais,
        cliente_factory=lambda credenciais: cliente or FakeCliente(),
        iniciar_thread=(lambda alvo: alvo()) if sincrono else (lambda alvo: None),
    )
    return TestClient(create_app(replace(services, publicador=publicador)))


def test_get_sem_publicacao(services, settings):
    run_pronta(settings)
    resposta = cliente_api(services, settings, conectado=False).get("/api/runs/run-1/publication")
    assert resposta.status_code == 200
    assert resposta.json() == {"estado": None, "em_andamento": False, "conectado": False}


def test_run_inexistente_ou_caminho_suspeito_e_404(services, settings):
    api = cliente_api(services, settings)
    assert api.get("/api/runs/nada/publication").status_code == 404
    assert api.get("/api/runs/..%2F..%2Fetc/publication").status_code == 404


def test_post_sem_login_google_e_409(services, settings):
    run_pronta(settings)
    resposta = cliente_api(services, settings, conectado=False).post(
        "/api/runs/run-1/publication", json={"titulo": "Título A"})
    assert resposta.status_code == 409
    assert resposta.json()["error"]["code"] == "youtube_auth_missing"
    assert "Conecte" in resposta.json()["error"]["message"]


def test_post_run_nao_aprovada_e_409(services, settings):
    run_pronta(settings, aprovado=False)
    resposta = cliente_api(services, settings).post(
        "/api/runs/run-1/publication", json={"titulo": "Título A"})
    assert resposta.status_code == 409
    assert resposta.json()["error"]["code"] == "publication_refused"


def test_post_publica_e_get_mostra_link(services, settings):
    run_pronta(settings)
    api = cliente_api(services, settings)
    resposta = api.post("/api/runs/run-1/publication",
                        json={"titulo": "Título A", "publicar_em": None})
    assert resposta.status_code == 202
    estado = api.get("/api/runs/run-1/publication").json()["estado"]
    assert estado["etapa"] == "concluida"
    assert estado["url"] == "https://studio.youtube.com/video/vid9/edit"

    de_novo = api.post("/api/runs/run-1/publication", json={"titulo": "Título A"})
    assert de_novo.status_code == 409
    assert de_novo.json()["error"]["code"] == "already_published"


def test_post_agendamento_no_passado_e_recusado(services, settings):
    run_pronta(settings)
    resposta = cliente_api(services, settings).post(
        "/api/runs/run-1/publication",
        json={"titulo": "Título A", "publicar_em": "2020-01-01T10:00:00-03:00"})
    assert resposta.status_code == 409
    assert resposta.json()["error"]["code"] == "publication_refused"


def test_segundo_post_durante_envio_e_409(services, settings):
    run_pronta(settings)
    api = cliente_api(services, settings, sincrono=False)
    assert api.post("/api/runs/run-1/publication", json={"titulo": "Título A"}).status_code == 202
    assert api.get("/api/runs/run-1/publication").json()["em_andamento"] is True
    segundo = api.post("/api/runs/run-1/publication", json={"titulo": "Título A"})
    assert segundo.status_code == 409
    assert segundo.json()["error"]["code"] == "publication_running"


def test_erro_inesperado_na_thread_fica_no_estado(services, settings):
    run_pronta(settings)

    class Quebrado(FakeCliente):
        def enviar_arquivo(self, *args, **kwargs):
            raise OSError("disco")

    api = cliente_api(services, settings, cliente=Quebrado())
    assert api.post("/api/runs/run-1/publication", json={"titulo": "Título A"}).status_code == 202
    corpo = api.get("/api/runs/run-1/publication").json()
    assert corpo["em_andamento"] is False
    assert corpo["estado"]["etapa"] == "falhou"
    assert corpo["estado"]["erro_codigo"] == "unexpected"


def test_publica_no_canal_padrao_e_grava_o_canal(services, settings):
    run_pronta(settings)
    canais = FakeCanais()
    api = cliente_api(services, settings, canais=canais)
    assert api.post("/api/runs/run-1/publication", json={"titulo": "Título A"}).status_code == 202
    estado = api.get("/api/runs/run-1/publication").json()["estado"]
    assert estado["canal_id"] == "UC1" and estado["canal_titulo"] == "Canal Um"
    assert canais.pedidos == ["UC1"]


def test_publica_no_canal_escolhido(services, settings):
    run_pronta(settings)
    canais = FakeCanais()
    api = cliente_api(services, settings, canais=canais)
    api.post("/api/runs/run-1/publication", json={"titulo": "Título A", "canal_id": "UC2"})
    assert api.get("/api/runs/run-1/publication").json()["estado"]["canal_id"] == "UC2"
    assert canais.pedidos == ["UC2"]


def test_canal_desconhecido_e_409(services, settings):
    run_pronta(settings)
    resposta = cliente_api(services, settings).post(
        "/api/runs/run-1/publication", json={"titulo": "Título A", "canal_id": "UC9"})
    assert resposta.status_code == 409
    assert resposta.json()["error"]["code"] == "youtube_channel_unknown"


def test_retomada_usa_o_canal_gravado_e_nao_o_pedido(services, settings):
    from forge.services.publicacao import EstadoPublicacao, _gravar
    run = run_pronta(settings)
    _gravar(run, EstadoPublicacao(etapa="falhou", titulo="Título A", upload_uri="https://s",
                                  total_bytes=10, canal_id="UC2", canal_titulo="Canal Dois"))
    canais = FakeCanais()
    api = cliente_api(services, settings, canais=canais)
    api.post("/api/runs/run-1/publication", json={"titulo": "Título A", "canal_id": "UC1"})
    assert canais.pedidos == ["UC2"]
    assert api.get("/api/runs/run-1/publication").json()["estado"]["canal_id"] == "UC2"
