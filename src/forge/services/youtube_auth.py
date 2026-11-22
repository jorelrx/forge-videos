"""Login OAuth da conta Google para publicar no YouTube.

Fluxo de aplicativo instalado: PKCE com callback em loopback (porta livre
escolhida pelo sistema, como o Google pede para clientes desktop). O cliente
OAuth é do usuário — o JSON que ele baixa do Google Cloud —, nunca embutido
aqui. Mesmo molde de `codex_auth.py`: gravação atômica sob `FileLock`, e
nenhum token ou código em log.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import threading
import time
import webbrowser
from contextlib import nullcontext
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from filelock import FileLock

from forge.services.youtube import YouTubeAuthError, YouTubeError

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ESCOPOS = (
    "https://www.googleapis.com/auth/youtube.upload",
    # Legenda (captions.insert) não aceita só o escopo de upload.
    "https://www.googleapis.com/auth/youtube.force-ssl",
)
_LOGIN = "Sessão Google ausente ou expirada; execute forge auth youtube login"


@dataclass(frozen=True)
class ClienteOAuth:
    client_id: str
    client_secret: str = ""

    def __repr__(self) -> str:  # o segredo não vai para log nem traceback
        return f"ClienteOAuth(client_id={self.client_id!r})"


def ler_cliente(path: Path) -> ClienteOAuth:
    """Lê o JSON de cliente OAuth baixado do Google Cloud (tipo desktop)."""
    try:
        dados = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as erro:
        raise YouTubeAuthError(
            f"Cliente OAuth do Google não encontrado em {path}; baixe o JSON do "
            "cliente desktop no Google Cloud e aponte FORGE_YOUTUBE_CLIENT_SECRETS para ele"
        ) from erro
    instalado = dados.get("installed") if isinstance(dados, dict) else None
    if not isinstance(instalado, dict):
        raise YouTubeAuthError(
            "Cliente OAuth precisa ser do tipo desktop (chave 'installed'); "
            "crie um cliente 'App para computador' no Google Cloud"
        )
    client_id = instalado.get("client_id")
    if not isinstance(client_id, str) or not client_id.strip():
        raise YouTubeAuthError("Cliente OAuth sem client_id; baixe o JSON de novo")
    segredo = instalado.get("client_secret")
    return ClienteOAuth(client_id.strip(), segredo.strip() if isinstance(segredo, str) else "")


def validar_callback(caminho: str, state: str) -> str:
    query = parse_qs(urlsplit(caminho).query)
    if (
        query.get("error")
        or len(query.get("state", [])) != 1
        or not hmac.compare_digest(query["state"][0].encode(), state.encode())
        or len(query.get("code", [])) != 1
    ):
        raise YouTubeAuthError("Retorno OAuth inválido ou login recusado; repita o login")
    return query["code"][0]


class GoogleCredentials:
    def __init__(self, token_path: Path, client_secrets_path: Path, *,
                 client: httpx.Client | None = None):
        self.path = Path(token_path)
        self.client_secrets_path = Path(client_secrets_path)
        self.client = client

    def _http(self):
        return nullcontext(self.client) if self.client is not None else httpx.Client(timeout=20)

    def _ler(self) -> dict:
        try:
            store = json.loads(self.path.read_text(encoding="utf-8"))
            tokens = store["tokens"]
            if store.get("revogado"):
                raise ValueError("credencial revogada")
            if not all(isinstance(tokens.get(k), str) and tokens[k].strip()
                       for k in ("access_token", "refresh_token")):
                raise ValueError("tokens ausentes")
            return store
        except (OSError, ValueError, KeyError, TypeError) as erro:
            raise YouTubeAuthError(_LOGIN) from erro

    def _gravar(self, store: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, nome = tempfile.mkstemp(prefix=".oauth-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as saida:
                json.dump(store, saida, ensure_ascii=False)
                saida.flush()
                os.fsync(saida.fileno())
            os.chmod(nome, 0o600)
            os.replace(nome, self.path)
        finally:
            Path(nome).unlink(missing_ok=True)

    def escopos(self) -> set[str]:
        return set(self._ler()["tokens"].get("scope", "").split())

    def disponivel(self) -> bool:
        """Há login gravado. Sem rede: não prova que o refresh ainda vale."""
        try:
            self._ler()
            return True
        except YouTubeAuthError:
            return False

    def login(self, *, timeout: float = 180, open_browser=webbrowser.open, show_url=None,
              escopos=ESCOPOS, retorno_studio=None) -> None:
        cliente = ler_cliente(self.client_secrets_path)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        state = secrets.token_urlsafe(32)
        resultado: dict = {}
        pronto = threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # a URL de retorno traz o código: nunca registrar

            def do_GET(self):
                if "favicon" in self.path:
                    self.send_error(404)
                    return
                try:
                    resultado["code"] = validar_callback(self.path, state)
                    status, corpo = 200, "Login recebido. Pode fechar esta janela.".encode()
                    if retorno_studio:
                        status, corpo = 303, b""
                except YouTubeAuthError:
                    resultado["erro"] = True
                    status, corpo = 400, b"Retorno OAuth invalido."
                self.send_response(status)
                if status == 303:
                    self.send_header("Location", retorno_studio)
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                self.wfile.write(corpo)
                pronto.set()

        servidor = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        redirect = f"http://127.0.0.1:{servidor.server_address[1]}/"
        url = AUTH_URL + "?" + urlencode({
            "response_type": "code",
            "client_id": cliente.client_id,
            "redirect_uri": redirect,
            "scope": " ".join(escopos),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            # Sem os dois, o Google não devolve refresh token e o login dura 1 h.
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        })
        try:
            servidor.timeout = 0.2
            if show_url:
                show_url(url)
            if not open_browser(url) and show_url is None:
                raise YouTubeAuthError("Navegador indisponível para o login OAuth")
            prazo = time.monotonic() + timeout
            while not pronto.is_set() and time.monotonic() < prazo:
                servidor.handle_request()
            if not pronto.is_set() or resultado.get("erro"):
                raise YouTubeAuthError("Login OAuth recusado ou prazo esgotado; repita o login")
        finally:
            servidor.server_close()
        try:
            with self._http() as http:
                resposta = http.post(TOKEN_URL, data={
                    "grant_type": "authorization_code",
                    "code": resultado["code"],
                    "redirect_uri": redirect,
                    "client_id": cliente.client_id,
                    "client_secret": cliente.client_secret,
                    "code_verifier": verifier,
                })
            resposta.raise_for_status()
            tokens = resposta.json()
            if not all(isinstance(tokens.get(k), str) and tokens[k].strip()
                       for k in ("access_token", "refresh_token")):
                raise ValueError("tokens ausentes")
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise YouTubeAuthError(
                "Falha ao trocar a autorização do Google; repita forge auth youtube login"
            ) from None
        tokens = {k: tokens[k] for k in ("access_token", "refresh_token", "scope", "expires_in")
                  if k in tokens}
        # RFC 6749: scope omitido na resposta significa os mesmos escopos pedidos.
        tokens.setdefault("scope", " ".join(escopos))
        if isinstance(tokens.get("expires_in"), (int, float)):
            tokens["expires_at"] = time.time() + tokens.pop("expires_in")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.path) + ".lock", timeout=30):
            self._gravar({"tokens": tokens, "ultimo_login": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime())})

    def access_token(self) -> str:
        self._ler()  # sem login, não cria pasta nem lock
        with FileLock(str(self.path) + ".lock", timeout=30):
            store = self._ler()
            tokens = store["tokens"]
            expira = tokens.get("expires_at", 0)
            if isinstance(expira, (int, float)) and expira > time.time() + 120:
                return tokens["access_token"].strip()
            cliente = ler_cliente(self.client_secrets_path)
            try:
                with self._http() as http:
                    resposta = http.post(TOKEN_URL, data={
                        "grant_type": "refresh_token",
                        "refresh_token": tokens["refresh_token"],
                        "client_id": cliente.client_id,
                        "client_secret": cliente.client_secret,
                    })
                resposta.raise_for_status()
                novo = resposta.json()
                token = novo["access_token"]
                if not isinstance(token, str) or not token.strip():
                    raise ValueError("access token ausente")
            except httpx.HTTPStatusError as erro:
                try:
                    motivo = erro.response.json().get("error")
                except (ValueError, AttributeError):
                    motivo = None
                if motivo == "invalid_grant":
                    store["revogado"] = True
                    self._gravar(store)
                    raise YouTubeAuthError(_LOGIN) from None
                raise YouTubeError("Renovação indisponível no Google", status=erro.response.status_code) from None
            except (httpx.RequestError, ValueError, KeyError, TypeError):
                raise YouTubeError("Falha temporária na renovação do Google") from None
            tokens["access_token"] = token.strip()
            if isinstance(novo.get("scope"), str):
                tokens["scope"] = novo["scope"]
            if isinstance(novo.get("refresh_token"), str) and novo["refresh_token"].strip():
                tokens["refresh_token"] = novo["refresh_token"].strip()
            if isinstance(novo.get("expires_in"), (int, float)):
                tokens["expires_at"] = time.time() + novo["expires_in"]
            self._gravar(store)
            return tokens["access_token"]


__all__ = ["ESCOPOS", "ClienteOAuth", "GoogleCredentials", "ler_cliente", "validar_callback"]
