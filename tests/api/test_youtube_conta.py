from __future__ import annotations

import json
import threading
import time
from dataclasses import replace

from fastapi.testclient import TestClient

from forge.api.app import create_app
from .conftest import autenticar

CLIENTE = json.dumps({"installed": {"client_id": "id.apps.googleusercontent.com",
                                    "client_secret": "segredo-xyz"}})


class FakeCredenciais:
    def __init__(self, path, liberar):
        self.path, self.liberar = path, liberar

    def login(self, *, timeout, open_browser, escopos, retorno_studio, show_url=None):
        self.liberar.retornos[retorno_studio.split("/")[-2]] = retorno_studio
        open_browser("https://accounts.google.com/o/oauth2/v2/auth?x=1")
        assert self.liberar.wait(5)
        self.path.write_text(json.dumps({"tokens": {
            "scope": " ".join(escopos), "access_token": "a", "refresh_token": "r", "expires_at": time.time() + 3600}}),
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
    liberar.retornos = {}
    login = LoginGoogle(canais, fabrica=lambda path: FakeCredenciais(path, liberar))
    api = TestClient(create_app(replace(services, settings=settings,
                                        youtube=ContaYouTube(canais=canais, login=login))))
    autenticar(api, services, canais=())
    return api, liberar, canais


def concluir(api, tentativa, liberar):
    assert api.get(liberar.retornos[tentativa]).status_code == 200
    liberar.set()
    for _ in range(150):
        resultado = api.get("/api/youtube/login/" + tentativa).json()["login"]
        if resultado["status"] != "aguardando":
            return resultado
        time.sleep(.02)
    raise AssertionError("Login não terminou")


def test_conta_nova_e_configuracao_local(services, settings, tmp_path):
    api, _, canais = montar(services, settings, tmp_path)
    assert api.get("/api/canais").json() == {"canais": [], "ultimo_canal_id": None}
    resposta = api.post("/api/youtube/login")
    assert resposta.status_code == 409
    assert resposta.json()["error"]["code"] == "youtube_client_missing"
    assert api.post("/api/youtube/client", json={"conteudo": CLIENTE}).status_code == 404
    assert not canais.cliente_configurado()


def test_login_completo_e_desconexao(services, settings, tmp_path):
    api, liberar, canais = montar(services, settings, tmp_path)
    canais.salvar_cliente(CLIENTE)
    inicio = api.post("/api/youtube/login")
    assert inicio.status_code == 202
    dados = inicio.json()
    assert dados["login"]["status"] == "aguardando"
    assert dados["login"]["url"].startswith("https://accounts.google.com/")
    assert concluir(api, dados["tentativa_id"], liberar)["status"] == "concluido"
    assert api.get("/api/canais").json() == {"ultimo_canal_id": "UC1", "canais": [
        {"id": "UC1", "titulo": "Canal Um", "thumbnail": "https://img/1", "conectado": True, "padrao": True}]}
    assert api.post("/api/youtube/channels/UC1/default").json()["ultimo_canal_id"] == "UC1"
    assert api.post("/api/youtube/channels/UC9/default").status_code == 404
    assert api.post("/api/youtube/channels/UC9/disconnect").status_code == 404
    assert api.post("/api/youtube/channels/UC1/disconnect").json()["canais"] == []
