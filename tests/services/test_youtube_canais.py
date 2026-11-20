import json
import threading
import time

import pytest

from forge.infrastructure.config import Settings

CLIENTE = json.dumps({"installed": {"client_id": "id.apps.googleusercontent.com",
                                    "client_secret": "s"}})


def settings(tmp_path):
    return Settings(_env_file=None,
                    youtube_client_secrets=tmp_path / "yt" / "client_secret.json",
                    youtube_canais_dir=tmp_path / "yt" / "canais")


def token(path, access="a"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"tokens": {"access_token": access, "refresh_token": "r",
                                           "expires_at": time.time() + 3600}}), encoding="utf-8")


def canais(tmp_path, canal=None):
    from forge.services.youtube_canais import CanaisYouTube
    info = canal or {"id": "UC1", "titulo": "Canal Um", "thumbnail": "https://img/1"}
    return CanaisYouTube(settings(tmp_path), identificar=lambda credenciais: info)


def test_sem_nada_configurado(tmp_path):
    registro = canais(tmp_path)
    assert registro.cliente_configurado() is False
    assert registro.listar() == []
    assert registro.padrao() is None


def test_salvar_cliente_valido_grava_e_invalido_recusa(tmp_path):
    from forge.services.youtube import YouTubeAuthError
    registro = canais(tmp_path)
    for ruim in ("não é json", json.dumps({"web": {"client_id": "x"}}), json.dumps({"installed": {}})):
        with pytest.raises(YouTubeAuthError):
            registro.salvar_cliente(ruim)
    assert registro.cliente_configurado() is False
    registro.salvar_cliente(CLIENTE)
    assert registro.cliente_configurado() is True
    assert json.loads(settings(tmp_path).youtube_client_secrets.read_text())["installed"]["client_id"]


def test_registrar_token_move_para_o_canal_e_vira_padrao(tmp_path):
    registro = canais(tmp_path)
    temporario = tmp_path / "tmp-token.json"
    token(temporario)
    canal = registro.registrar(temporario)
    assert canal.id == "UC1" and canal.padrao is True
    assert not temporario.exists()
    assert (settings(tmp_path).youtube_canais_dir / "UC1.json").is_file()
    assert [c.titulo for c in registro.listar()] == ["Canal Um"]
    assert registro.credenciais("UC1").access_token() == "a"


def test_segundo_canal_vira_padrao_e_troca_de_padrao(tmp_path):
    canais(tmp_path).registrar(_tok(tmp_path, "t1"))
    dois = canais(tmp_path, {"id": "UC2", "titulo": "Canal Dois", "thumbnail": None})
    dois.registrar(_tok(tmp_path, "t2"))
    assert dois.padrao() == "UC2"
    dois.definir_padrao("UC1")
    assert [(c.id, c.padrao) for c in dois.listar()] == [("UC1", True), ("UC2", False)]


def test_desconectar_apaga_token_e_passa_padrao_adiante(tmp_path):
    canais(tmp_path).registrar(_tok(tmp_path, "t1"))
    dois = canais(tmp_path, {"id": "UC2", "titulo": "Canal Dois", "thumbnail": None})
    dois.registrar(_tok(tmp_path, "t2"))
    dois.desconectar("UC2")
    assert not (settings(tmp_path).youtube_canais_dir / "UC2.json").exists()
    assert dois.padrao() == "UC1"
    dois.desconectar("UC1")
    assert dois.listar() == [] and dois.padrao() is None


def test_canal_desconhecido_e_keyerror(tmp_path):
    registro = canais(tmp_path)
    for acao in (registro.definir_padrao, registro.desconectar, registro.credenciais):
        with pytest.raises(KeyError):
            acao("UC404")


@pytest.mark.parametrize("canal_id", ["../fora", "UC/1", ""])
def test_id_de_canal_estranho_nao_vira_caminho(tmp_path, canal_id):
    from forge.services.youtube import YouTubeError
    registro = canais(tmp_path, {"id": canal_id, "titulo": "x", "thumbnail": None})
    with pytest.raises(YouTubeError):
        registro.registrar(_tok(tmp_path, "t"))


def _tok(tmp_path, nome):
    caminho = tmp_path / f"{nome}.json"
    token(caminho)
    return caminho


class FakeCredenciais:
    """Login falso: entrega a URL e espera o 'callback' liberado pelo teste."""

    def __init__(self, path, liberar, falhar=None):
        self.path = path
        self.liberar = liberar
        self.falhar = falhar

    def login(self, *, timeout, open_browser, show_url=None):
        open_browser("https://accounts.google.com/o/oauth2/v2/auth?x=1")
        assert self.liberar.wait(5)
        if self.falhar:
            raise self.falhar
        token(self.path)


def test_login_pela_api_devolve_url_e_registra_o_canal(tmp_path):
    from forge.services.youtube_canais import LoginGoogle
    registro = canais(tmp_path)
    registro.salvar_cliente(CLIENTE)
    liberar = threading.Event()
    login = LoginGoogle(registro, fabrica=lambda path: FakeCredenciais(path, liberar))
    estado = login.iniciar()
    assert estado.status == "aguardando"
    assert estado.url.startswith("https://accounts.google.com/")
    assert login.iniciar().url == estado.url  # segundo clique reusa o login em curso
    liberar.set()
    login.aguardar(5)
    final = login.estado()
    assert final.status == "concluido" and final.canal_id == "UC1"
    assert [c.id for c in registro.listar()] == ["UC1"]


def test_login_recusado_fica_no_estado(tmp_path):
    from forge.services.youtube import YouTubeAuthError
    from forge.services.youtube_canais import LoginGoogle
    registro = canais(tmp_path)
    registro.salvar_cliente(CLIENTE)
    liberar = threading.Event()
    login = LoginGoogle(registro, fabrica=lambda path: FakeCredenciais(
        path, liberar, falhar=YouTubeAuthError("Login OAuth recusado")))
    login.iniciar()
    liberar.set()
    login.aguardar(5)
    assert login.estado().status == "falhou"
    assert "recusado" in login.estado().erro
    assert registro.listar() == []


def test_login_sem_cliente_e_recusado(tmp_path):
    from forge.services.youtube_canais import ClienteAusente, LoginGoogle
    with pytest.raises(ClienteAusente):
        LoginGoogle(canais(tmp_path)).iniciar()
