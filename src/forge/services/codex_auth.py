"""Credenciais OAuth do Forge; nenhum import ou processo Hermes/Codex.

Protocolo adaptado das rotas Codex do Hermes Agent (MIT); veja
THIRD_PARTY_NOTICES.md. Endpoints de credenciais são fixos, nunca configuráveis.
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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from filelock import FileLock

from forge.services.codex import CodexError

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
TOKEN_URL = "https://auth.openai.com/oauth/token"
_LOGIN = "Sessão ChatGPT ausente ou inválida; execute forge auth codex login"


class CodexAuthError(CodexError):
    """Autenticação ausente, inválida ou que precisa de novo login."""


def token_claims(token: str) -> dict:
    try:
        payload = token.split(".")[1]
        claims = json.loads(
            base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        )
        return claims if isinstance(claims, dict) else {}
    except (ValueError, IndexError, UnicodeError):
        return {}


def request_headers(token: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "ForgeVideos/0.1.0",
        "originator": "forge-videos",
    }
    auth = token_claims(token).get("https://api.openai.com/auth", {})
    if isinstance(auth, dict):
        account = auth.get("chatgpt_account_id")
        residency = auth.get("chatgpt_data_residency") or auth.get(
            "chatgpt_compute_residency"
        )
        if isinstance(account, str) and account:
            headers["ChatGPT-Account-ID"] = account
        if isinstance(residency, str) and residency.strip():
            headers["x-openai-internal-codex-residency"] = residency.strip()
    return headers


def validate_callback(path: str, state: str) -> str:
    query = parse_qs(urlsplit(path).query)
    if (
        urlsplit(path).path != "/auth/callback"
        or query.get("error")
        or len(query.get("state", [])) != 1
        or not hmac.compare_digest(query["state"][0].encode(), state.encode())
        or len(query.get("code", [])) != 1
    ):
        raise CodexAuthError("Retorno OAuth inválido ou login recusado; repita o login")
    return query["code"][0]


class OAuthCredentials:
    def __init__(self, path: Path, *, client: httpx.Client | None = None):
        self.path = Path(path)
        self.client = client

    def _read(self) -> dict:
        try:
            store = json.loads(self.path.read_text(encoding="utf-8"))
            token = store["tokens"]["access_token"]
            if (
                store.get("auth_mode") not in (None, "chatgpt")
                or not isinstance(token, str)
                or not token.strip()
            ):
                raise ValueError("missing OAuth token")
            return store
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise CodexAuthError(_LOGIN) from error

    def _save(self, store: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".oauth-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(store, output, ensure_ascii=False)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(name, 0o600)
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)

    def login(
        self, *, timeout: float = 180, open_browser=webbrowser.open, show_url=None
    ) -> None:
        if timeout <= 0:
            raise CodexAuthError("Prazo de login deve ser positivo")
        verifier = secrets.token_urlsafe(64)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        state = secrets.token_urlsafe(32)
        result: dict = {}
        done = threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # URLs de retorno contêm códigos: nunca registrar.

            def do_GET(self):
                if urlsplit(self.path).path != "/auth/callback":
                    self.send_error(404)
                    return
                try:
                    result["code"] = validate_callback(self.path, state)
                    status, body = 200, b"Login recebido. Pode fechar esta janela."
                except CodexAuthError:
                    result["error"] = True
                    status, body = 400, b"Retorno OAuth invalido."
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                done.set()

        try:
            server = ThreadingHTTPServer(("127.0.0.1", 1455), Handler)
        except OSError:
            raise CodexAuthError(
                "Porta 1455 ocupada; encerre outro login e repita forge auth codex login"
            ) from None
        redirect = "http://localhost:1455/auth/callback"
        url = "https://auth.openai.com/oauth/authorize?" + urlencode(
            {
                "response_type": "code",
                "client_id": CLIENT_ID,
                "redirect_uri": redirect,
                "scope": "openid profile email offline_access",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "id_token_add_organizations": "true",
                "state": state,
            }
        )
        try:
            server.timeout = 0.2
            if show_url:
                show_url(url)
            if not open_browser(url) and show_url is None:
                raise CodexAuthError("Navegador indisponível para login OAuth")
            deadline = time.monotonic() + timeout
            while not done.is_set() and time.monotonic() < deadline:
                server.handle_request()
            if not done.is_set() or result.get("error"):
                raise CodexAuthError(
                    "Login OAuth recusado ou prazo esgotado; repita o login"
                )
        finally:
            server.server_close()
        context = (
            nullcontext(self.client)
            if self.client is not None
            else httpx.Client(timeout=20)
        )
        try:
            with context as client:
                response = client.post(
                    TOKEN_URL,
                    data={
                        "grant_type": "authorization_code",
                        "code": result["code"],
                        "redirect_uri": redirect,
                        "client_id": CLIENT_ID,
                        "code_verifier": verifier,
                    },
                )
            response.raise_for_status()
            tokens = response.json()
            if not all(
                isinstance(tokens.get(k), str) and tokens[k].strip()
                for k in ("access_token", "refresh_token")
            ):
                raise ValueError("OAuth tokens missing")
            if isinstance(tokens.get("expires_in"), (int, float)):
                tokens["expires_at"] = time.time() + tokens["expires_in"]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with FileLock(str(self.path) + ".lock", timeout=30):
                self._save(
                    {
                        "auth_mode": "chatgpt",
                        "tokens": tokens,
                        "last_refresh": time.strftime(
                            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                        ),
                    }
                )
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise CodexAuthError(
                "Falha ao trocar autorização OAuth; repita forge auth codex login"
            ) from None

    def access_token(self) -> str:
        self._read()  # Falta de login não cria arquivos ou pastas.
        with FileLock(str(self.path) + ".lock", timeout=30):
            store = self._read()
            tokens = store["tokens"]
            token = tokens["access_token"].strip()
            expiry = token_claims(token).get("exp", tokens.get("expires_at", 0))
            if not isinstance(expiry, (int, float)) or expiry <= time.time() + 120:
                refresh = tokens.get("refresh_token")
                if not isinstance(refresh, str) or not refresh.strip():
                    raise CodexAuthError(_LOGIN)
                context = (
                    nullcontext(self.client)
                    if self.client is not None
                    else httpx.Client(timeout=20)
                )
                try:
                    with context as client:
                        response = client.post(
                            TOKEN_URL,
                            json={
                                "grant_type": "refresh_token",
                                "refresh_token": refresh,
                                "client_id": CLIENT_ID,
                            },
                        )
                    response.raise_for_status()
                    updated = response.json()
                    token = updated["access_token"]
                    if not isinstance(token, str) or not token.strip():
                        raise ValueError("missing refreshed access token")
                    tokens["access_token"] = token.strip()
                    for key in ("refresh_token", "id_token"):
                        if isinstance(updated.get(key), str) and updated[key].strip():
                            tokens[key] = updated[key].strip()
                    if isinstance(updated.get("expires_in"), (int, float)):
                        tokens["expires_at"] = time.time() + updated["expires_in"]
                    store["last_refresh"] = time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                    )
                    self._save(store)
                except (httpx.HTTPError, ValueError, KeyError, TypeError):
                    raise CodexAuthError(
                        "Falha ao renovar sessão ChatGPT; execute forge auth codex login"
                    ) from None
            return token.strip()
