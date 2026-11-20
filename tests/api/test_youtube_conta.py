from __future__ import annotations

import json
import threading
import time
from dataclasses import replace

from fastapi.testclient import TestClient

from forge.api.app import create_app

CLIENTE = json.dumps({"installed": {"client_id": "id.apps.googleusercontent.com",
                                    "client_secret": "segredo-xyz"}})


class FakeCredenciais:
    def __init__(self, path, liberar):
        self.path, self.liberar = path, liberar

    def login(self, *, timeout, open_browser, show_url=None):
        open_browser("https://accounts.google.com/o/oauth2/v2/auth?x=1")
        assert self.liberar.wait(5)
        self.path.write_text(json.dumps({"tokens": {
            "access_token": "a", "refresh_token": "r", "expires_at": time.time() + 3600}}),
            encoding="utf-8")


def montar(services, settings, tmp_path, canal=None):
    from forge.services.youtube_canais import CanaisYouTube, ContaYouTube, LoginGoogle
    settings = settings.model_copy(update={
        "youtube_client_secrets": tmp_path / "yt" / "client_secret.json",
        "youtube_canais_dir": tmp_path / "yt" / "canais",
    })
    info = canal or {"id": "UC1", "titulo": "Canal Um", "thumbnail": "https://img/1"}
    canais = CanaisYouTube(settings, identificar=lambda credenciais: info)
    liberar = threading.Event()
    login = LoginGoogle(canais, fabrica=lambda path: FakeCredenciais(path, liberar))
    api = TestClient(create_app(replace(services, settings=settings,
                                        youtube=ContaYouTube(canais=canais, login=login))))
    return api, liberar, login


def test_estado_inicial_sem_cliente(services, settings, tmp_path):
    api, _, _ = montar(services, settings, tmp_path)
    assert api.get("/api/youtube").json() == {
        "cliente_configurado": False, "canais": [],
        "login": {"status": "inativo", "url": None, "erro": None, "canal_id": None},
    }


def test_login_sem_cliente_e_409(services, settings, tmp_path):
    api, _, _ = montar(services, settings, tmp_path)
    resposta = api.post("/api/youtube/login")
    assert resposta.status_code == 409
    assert resposta.json()["error"]["code"] == "youtube_client_missing"


def test_cliente_invalido_e_422_e_valido_configura(services, settings, tmp_path):
    api, _, _ = montar(services, settings, tmp_path)
    ruim = api.post("/api/youtube/client", json={"conteudo": json.dumps({"web": {}})})
    assert ruim.status_code == 422
    assert ruim.json()["error"]["code"] == "youtube_client_invalid"
    bom = api.post("/api/youtube/client", json={"conteudo": CLIENTE})
    assert bom.status_code == 200
    assert bom.json()["cliente_configurado"] is True
    assert "segredo-xyz" not in bom.text  # o segredo nunca volta


def test_login_completo_lista_o_canal_como_padrao(services, settings, tmp_path):
    api, liberar, login = montar(services, settings, tmp_path)
    api.post("/api/youtube/client", json={"conteudo": CLIENTE})
    inicio = api.post("/api/youtube/login")
    assert inicio.status_code == 202
    assert inicio.json()["login"]["status"] == "aguardando"
    assert inicio.json()["login"]["url"].startswith("https://accounts.google.com/")
    liberar.set()
    login.aguardar(5)
    visao = api.get("/api/youtube").json()
    assert visao["login"]["status"] == "concluido"
    assert visao["canais"] == [{"id": "UC1", "titulo": "Canal Um",
                                "thumbnail": "https://img/1", "padrao": True}]


def test_padrao_e_desconectar(services, settings, tmp_path):
    api, liberar, login = montar(services, settings, tmp_path)
    api.post("/api/youtube/client", json={"conteudo": CLIENTE})
    api.post("/api/youtube/login")
    liberar.set()
    login.aguardar(5)
    assert api.post("/api/youtube/channels/UC1/default").json()["canais"][0]["padrao"] is True
    assert api.post("/api/youtube/channels/UC9/default").status_code == 404
    assert api.post("/api/youtube/channels/UC9/disconnect").status_code == 404
    assert api.post("/api/youtube/channels/UC1/disconnect").json()["canais"] == []
