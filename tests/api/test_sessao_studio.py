from urllib.parse import urlencode, urlsplit, parse_qs
from dataclasses import replace

from fastapi.testclient import TestClient

from forge.api.app import create_app


class OIDC:
    async def iniciar(self, callback, state, nonce):
        self.nonce = nonce
        return "https://accounts.example/authorize?" + urlencode({"state": state})

    async def identificar(self, callback, code, nonce):
        assert nonce == self.nonce and code == "ok"
        return {"sub": "pessoa", "name": "Pessoa", "picture": "https://img.example/foto"}


def test_login_em_localhost_redireciona_para_origem_do_callback(services):
    app = create_app(replace(services, oidc=OIDC()))
    client = TestClient(app, follow_redirects=False)
    resposta = client.get("/api/sessao/google", params={"retorno": "/canais/A"},
                           headers={"X-Forwarded-Host": "localhost:3100"})
    assert resposta.status_code == 307
    assert resposta.headers["location"] == (
        "http://127.0.0.1:3100/api/sessao/google?retorno=%2Fcanais%2FA"
    )
    assert "set-cookie" not in resposta.headers


def test_recusa_do_google_tem_mensagem_propria(services):
    app = create_app(replace(services, oidc=OIDC()))
    client = TestClient(app, base_url=services.settings.studio_public_origin,
                        follow_redirects=False)
    login = client.get("/api/sessao/google")
    state = parse_qs(urlsplit(login.headers["location"]).query)["state"][0]
    resposta = client.get("/api/sessao/google/callback",
                           params={"state": state, "error": "access_denied"})
    assert resposta.status_code == 400
    assert resposta.json()["detail"] == "O Google recusou ou cancelou a autorização."


def test_oidc_vincula_navegador_consumo_unico_e_logout(services):
    app = create_app(replace(services, oidc=OIDC()))
    origem = services.settings.studio_public_origin
    client = TestClient(app, base_url=origem, follow_redirects=False)
    outro = TestClient(app, base_url=origem)
    assert client.get("/api/sessao").status_code == 401
    login = client.get("/api/sessao/google", params={"retorno": "/canais/A"})
    state = parse_qs(urlsplit(login.headers["location"]).query)["state"][0]
    callback = "/api/sessao/google/callback?" + urlencode({"state": state, "code": "ok"})
    assert outro.get(callback).status_code == 400
    retorno = client.get(callback)
    assert retorno.headers["location"].endswith("/canais/A")
    assert "HttpOnly" in retorno.headers["set-cookie"]
    assert client.get("/api/sessao").json()["nome"] == "Pessoa"
    cookie = client.cookies.get("forge_sessao")
    assert client.get(callback).status_code == 400
    assert client.post("/api/sessao/sair").status_code == 403
    assert client.post("/api/sessao/sair", headers={"Origin": services.settings.studio_public_origin}).status_code == 204
    outro.cookies.set("forge_sessao", cookie)
    assert outro.get("/api/sessao").status_code == 401

def test_expiracao_e_retorno_externo(services):
    from forge.services.sessao_studio import SessaoStudio
    from forge.api.routes.sessao import _retorno_interno

    for caminho in ("https://exemplo.org", "//exemplo.org", "/%5Cexemplo.org", "/%0A/exemplo.org"):
        assert _retorno_interno(caminho) == "/"
    sessoes = SessaoStudio(services.commands.db)
    state, navegador, _ = sessoes.tentar("/")
    token = sessoes.criar("p", "Pessoa")
    with services.commands.db.transaction() as conn:
        row = conn.execute("SELECT digest FROM sessoes").fetchone()
        assert row[0] != token
        conn.execute("UPDATE sessoes SET expira=0")
        conn.execute("UPDATE tentativas_oidc SET expira=0")
    assert sessoes.pessoa(token) is None
    assert sessoes.consumir(state, navegador) is None


def test_oidc_valida_token_assinado_sem_rede(settings):
    import asyncio
    import time
    from unittest.mock import AsyncMock
    import pytest
    from joserfc import jwt
    from joserfc.jwk import RSAKey
    from pydantic import SecretStr
    from forge.services.sessao_studio import GoogleOIDC

    oidc = GoogleOIDC(settings.model_copy(update={
        "studio_google_client_id": "cliente-teste",
        "studio_google_client_secret": SecretStr("segredo-teste"),
    }))
    chave = RSAKey.generate_key(2048, parameters={"kid": "teste"})
    metadata = {"issuer": "https://accounts.google.com", "id_token_signing_alg_values_supported": ["RS256"]}
    oidc.cliente.load_server_metadata = AsyncMock(return_value=metadata)
    oidc.cliente.fetch_jwk_set = AsyncMock(return_value={"keys": [chave.as_dict(private=False)]})
    agora = int(time.time())
    claims = {"iss": "https://accounts.google.com", "aud": "cliente-teste", "sub": "p",
              "nonce": "n", "exp": agora + 600, "iat": agora}
    def verificar(alteracoes, assinatura=chave):
        id_token = jwt.encode({"alg": "RS256", "kid": "teste"}, claims | alteracoes, assinatura)
        oidc.cliente.fetch_access_token = AsyncMock(return_value={"access_token":"teste", "id_token":id_token})
        return asyncio.run(oidc.identificar("https://studio.example/callback", "ok", "n"))

    assert verificar({})["sub"] == "p"
    for alteracao in ({"nonce":"outro"}, {"iss":"https://outro"}, {"aud":"outro"}, {"exp":agora-600}):
        with pytest.raises(Exception):
            verificar(alteracao)
    with pytest.raises(Exception):
        verificar({}, RSAKey.generate_key(2048, parameters={"kid":"teste"}))
