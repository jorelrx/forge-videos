import json
import threading
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest


def cliente(path, tipo="installed"):
    path.write_text(json.dumps({tipo: {
        "client_id": "id.apps.googleusercontent.com",
        "client_secret": "segredo-cliente",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }}), encoding="utf-8")
    return path


def salvar_token(path, access="acesso", refresh="refresh-secreto", expira=None):
    path.write_text(json.dumps({"tokens": {
        "access_token": access, "refresh_token": refresh,
        "expires_at": time.time() + 3600 if expira is None else expira,
    }}), encoding="utf-8")


def sem_rede(request):
    raise AssertionError("não devia chamar a rede")


def credenciais(tmp_path, handler=sem_rede):
    from forge.services.youtube_auth import GoogleCredentials
    return GoogleCredentials(
        tmp_path / "token.json", cliente(tmp_path / "client_secret.json"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_token_valido_nao_usa_rede(tmp_path):
    auth = credenciais(tmp_path)
    salvar_token(tmp_path / "token.json")
    assert auth.access_token() == "acesso"
    assert auth.disponivel() is True


def test_sem_login_falha_com_acao_e_nao_cria_arquivo(tmp_path):
    from forge.services.youtube import YouTubeAuthError
    auth = credenciais(tmp_path)
    assert auth.disponivel() is False
    with pytest.raises(YouTubeAuthError, match="forge auth youtube login"):
        auth.access_token()
    assert not (tmp_path / "token.json").exists()


def test_cliente_oauth_web_e_recusado(tmp_path):
    from forge.services.youtube import YouTubeAuthError
    from forge.services.youtube_auth import ler_cliente
    with pytest.raises(YouTubeAuthError, match="desktop"):
        ler_cliente(cliente(tmp_path / "c.json", tipo="web"))


def test_cliente_ausente_explica_onde_colocar(tmp_path):
    from forge.services.youtube import YouTubeAuthError
    from forge.services.youtube_auth import ler_cliente
    with pytest.raises(YouTubeAuthError, match="FORGE_YOUTUBE_CLIENT_SECRETS"):
        ler_cliente(tmp_path / "nada.json")


def test_token_vencido_renova_e_mantem_refresh(tmp_path):
    def renovar(request):
        form = parse_qs(request.content.decode())
        assert form["grant_type"] == ["refresh_token"]
        assert form["refresh_token"] == ["refresh-secreto"]
        assert form["client_secret"] == ["segredo-cliente"]
        # O Google não devolve refresh token novo na renovação.
        return httpx.Response(200, json={"access_token": "novo", "expires_in": 3599})

    auth = credenciais(tmp_path, renovar)
    salvar_token(tmp_path / "token.json", expira=time.time() - 10)
    assert auth.access_token() == "novo"
    gravado = json.loads((tmp_path / "token.json").read_text())["tokens"]
    assert gravado["refresh_token"] == "refresh-secreto"
    assert gravado["expires_at"] > time.time() + 3000


def test_refresh_revogado_pede_novo_login_sem_vazar_segredo(tmp_path):
    from forge.services.youtube import YouTubeAuthError

    def revogado(request):
        return httpx.Response(400, json={"error": "invalid_grant"})

    auth = credenciais(tmp_path, revogado)
    salvar_token(tmp_path / "token.json", expira=0)
    with pytest.raises(YouTubeAuthError, match="forge auth youtube login") as erro:
        auth.access_token()
    assert "refresh-secreto" not in str(erro.value)


def test_login_pkce_offline_em_loopback(tmp_path):
    abertos, threads = [], []

    def navegador(url):
        params = parse_qs(urlsplit(url).query)
        abertos.append(params)
        redirect = params["redirect_uri"][0]
        assert redirect.startswith("http://127.0.0.1:")
        assert params["code_challenge_method"] == ["S256"]
        assert params["access_type"] == ["offline"]
        assert params["prompt"] == ["consent"]
        assert set(params["scope"][0].split()) == {
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.force-ssl",
        }

        def volta():
            resposta = httpx.get(redirect + "?code=codigo&state=" + params["state"][0], timeout=5)
            assert resposta.status_code == 200

        thread = threading.Thread(target=volta)
        threads.append(thread)
        thread.start()
        return True

    def troca(request):
        form = parse_qs(request.content.decode())
        assert form["grant_type"] == ["authorization_code"]
        assert form["code"] == ["codigo"]
        assert form["redirect_uri"] == abertos[0]["redirect_uri"]
        assert len(form["code_verifier"][0]) >= 43
        return httpx.Response(200, json={
            "access_token": "acesso", "refresh_token": "refresh", "expires_in": 3599,
        })

    auth = credenciais(tmp_path, troca)
    auth.login(timeout=5, open_browser=navegador)
    for thread in threads:
        thread.join(timeout=5)
    assert auth.access_token() == "acesso"
    assert json.loads((tmp_path / "token.json").read_text())["tokens"]["refresh_token"] == "refresh"


def test_login_sem_refresh_token_e_recusado(tmp_path):
    from forge.services.youtube import YouTubeAuthError

    def navegador(url):
        params = parse_qs(urlsplit(url).query)
        threading.Thread(target=lambda: httpx.get(
            params["redirect_uri"][0] + "?code=c&state=" + params["state"][0], timeout=5,
        )).start()
        return True

    auth = credenciais(tmp_path, lambda r: httpx.Response(200, json={"access_token": "a"}))
    with pytest.raises(YouTubeAuthError):
        auth.login(timeout=5, open_browser=navegador)
    assert not (tmp_path / "token.json").exists()


def test_callback_exige_state():
    from forge.services.youtube import YouTubeAuthError
    from forge.services.youtube_auth import validar_callback
    assert validar_callback("/?code=bom&state=certo", "certo") == "bom"
    for caminho in ("/?code=x&state=errado", "/?code=x", "/?state=certo&error=access_denied"):
        with pytest.raises(YouTubeAuthError):
            validar_callback(caminho, "certo")
