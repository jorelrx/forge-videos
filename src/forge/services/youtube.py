"""Cliente mínimo da YouTube Data API v3: upload retomável, thumbnail e legenda.

Quatro chamadas REST não justificam o `google-api-python-client`: httpx basta
e mantém o controle do upload retomável, que é o que importa aqui — um vídeo
de 400 MB não pode recomeçar do zero porque a rede piscou.
"""

from __future__ import annotations

import json
import secrets
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Callable

import httpx

UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
THUMBNAIL_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
LEGENDA_URL = "https://www.googleapis.com/upload/youtube/v3/captions"
CANAIS_URL = "https://www.googleapis.com/youtube/v3/channels"
# Múltiplo de 256 KiB, exigência do upload retomável.
TRECHO = 8 * 1024 * 1024
TENTATIVAS = 5
_MOTIVOS_COTA = {"quotaExceeded", "uploadLimitExceeded", "dailyLimitExceeded", "rateLimitExceeded"}


class YouTubeError(RuntimeError):
    """Falha explícita da publicação; a mensagem diz o que fazer."""

    codigo = "youtube_error"

    def __init__(self, mensagem: str, *, status: int | None = None):
        super().__init__(mensagem)
        self.status = status


class YouTubeAuthError(YouTubeError):
    """Sessão Google ausente, revogada ou cliente OAuth inválido."""

    codigo = "youtube_auth"


class YouTubeQuotaError(YouTubeError):
    """Cota diária da API esgotada; renova à meia-noite do Pacífico."""

    codigo = "youtube_quota"


class YouTubeSessaoExpirada(YouTubeError):
    """A sessão de upload retomável não existe mais; o envio recomeça do zero."""

    codigo = "youtube_upload_session_expired"


class _Transitorio(Exception):
    """Rede ou 5xx: vale consultar a sessão e tentar de novo."""


def _motivo(resposta: httpx.Response) -> tuple[str, str]:
    try:
        erro = resposta.json().get("error", {})
        motivos = [e.get("reason", "") for e in erro.get("errors", []) if isinstance(e, dict)]
        return (motivos[0] if motivos else ""), str(erro.get("message") or "")
    except (ValueError, AttributeError):
        return "", ""


def _verificar(resposta: httpx.Response) -> httpx.Response:
    if resposta.status_code < 400 or resposta.status_code == 308:
        return resposta
    if resposta.status_code >= 500:
        raise _Transitorio(f"HTTP {resposta.status_code}")
    motivo, mensagem = _motivo(resposta)
    if motivo in _MOTIVOS_COTA:
        raise YouTubeQuotaError(
            "Cota da YouTube Data API esgotada (renova à meia-noite do horário do "
            f"Pacífico); tente de novo depois. Detalhe: {motivo}"
        )
    if resposta.status_code == 401:
        raise YouTubeAuthError(
            "Sessão Google recusada pela API; execute forge auth youtube login"
        )
    raise YouTubeError(f"YouTube recusou ({resposta.status_code} {motivo}): {mensagem}".strip(),
                       status=resposta.status_code)


class YouTubeClient:
    def __init__(self, token: Callable[[], str], *, client: httpx.Client | None = None,
                 trecho: int = TRECHO, espera: Callable[[float], None] = time.sleep):
        self._token = token
        self._client = client
        self._trecho = trecho
        self._espera = espera

    def _http(self):
        return nullcontext(self._client) if self._client is not None else httpx.Client(timeout=120)

    def _cabecalhos(self, **extra) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token()}", **extra}

    def _pedir(self, metodo: str, url: str, **kwargs) -> httpx.Response:
        try:
            with self._http() as http:
                return _verificar(http.request(metodo, url, **kwargs))
        except httpx.TransportError as erro:
            raise _Transitorio(type(erro).__name__) from erro

    def _com_tentativas(self, acao):
        for tentativa in range(TENTATIVAS):
            try:
                return acao()
            except _Transitorio as erro:
                ultimo = erro
                self._espera(min(2 ** tentativa, 30))
        raise YouTubeError(
            f"Falha de rede ou do servidor do YouTube após {TENTATIVAS} tentativas "
            f"({ultimo}); tente publicar de novo, o envio continua de onde parou"
        )

    def iniciar_upload(self, metadados: dict, tamanho: int) -> str:
        def acao():
            resposta = self._pedir(
                "POST", UPLOAD_URL,
                params={"uploadType": "resumable", "part": "snippet,status"},
                headers=self._cabecalhos(**{
                    "Content-Type": "application/json; charset=UTF-8",
                    "X-Upload-Content-Length": str(tamanho),
                    "X-Upload-Content-Type": "video/mp4",
                }),
                content=json.dumps(metadados, ensure_ascii=False).encode("utf-8"),
            )
            sessao = resposta.headers.get("Location")
            if not sessao:
                raise YouTubeError("YouTube não devolveu a sessão de upload")
            return sessao
        return self._com_tentativas(acao)

    @staticmethod
    def _resultado(resposta: httpx.Response) -> int | dict:
        """308: bytes já recebidos. 200/201: o recurso do vídeo."""
        if resposta.status_code == 308:
            intervalo = resposta.headers.get("Range")
            return int(intervalo.rsplit("-", 1)[1]) + 1 if intervalo else 0
        return resposta.json()

    def _consultar(self, sessao: str, tamanho: int) -> int | dict:
        try:
            resposta = self._pedir("PUT", sessao, headers=self._cabecalhos(**{
                "Content-Range": f"bytes */{tamanho}", "Content-Length": "0"}))
        except YouTubeError as erro:
            if erro.status in (404, 410):
                raise YouTubeSessaoExpirada(
                    "Sessão de upload expirou no YouTube; o envio recomeça do zero"
                ) from erro
            raise
        return self._resultado(resposta)

    def enviar_arquivo(self, sessao: str, arquivo: Path, *, inicio: int,
                       ao_avancar: Callable[[int], None] | None = None) -> dict:
        tamanho = Path(arquivo).stat().st_size
        estado: dict = {"offset": inicio, "consultar": inicio > 0}

        def passo():
            if estado["consultar"]:
                resultado = self._consultar(sessao, tamanho)
                estado["consultar"] = False
                if isinstance(resultado, dict):
                    return resultado
                estado["offset"] = resultado
            offset = estado["offset"]
            fim = min(offset + self._trecho, tamanho) - 1
            with open(arquivo, "rb") as origem:
                origem.seek(offset)
                dados = origem.read(fim - offset + 1)
            try:
                resposta = self._pedir("PUT", sessao, headers=self._cabecalhos(**{
                    "Content-Range": f"bytes {offset}-{fim}/{tamanho}",
                    "Content-Type": "video/mp4"}), content=dados)
            except _Transitorio:
                estado["consultar"] = True
                raise
            return self._resultado(resposta)

        while True:
            resultado = self._com_tentativas(passo)
            if isinstance(resultado, dict):
                return resultado
            estado["offset"] = resultado
            if ao_avancar:
                ao_avancar(resultado)

    def meu_canal(self) -> dict:
        """O canal a que o token pertence: o Google o fixa na tela de login."""
        resposta = self._com_tentativas(lambda: self._pedir(
            "GET", CANAIS_URL, params={"part": "snippet", "mine": "true"},
            headers=self._cabecalhos()))
        itens = resposta.json().get("items") or []
        if not itens:
            raise YouTubeError(
                "A conta Google não tem canal do YouTube; crie o canal em youtube.com e conecte de novo")
        snippet = itens[0].get("snippet") or {}
        fotos = snippet.get("thumbnails") or {}
        foto = next((fotos[k]["url"] for k in ("medium", "default", "high")
                     if isinstance(fotos.get(k), dict) and fotos[k].get("url")), None)
        return {"id": str(itens[0].get("id") or ""), "titulo": str(snippet.get("title") or ""),
                "thumbnail": foto}

    def definir_thumbnail(self, video_id: str, caminho: Path) -> None:
        dados = Path(caminho).read_bytes()
        self._com_tentativas(lambda: self._pedir(
            "POST", THUMBNAIL_URL, params={"videoId": video_id, "uploadType": "media"},
            headers=self._cabecalhos(**{"Content-Type": "image/jpeg"}), content=dados))

    def enviar_legenda(self, video_id: str, caminho: Path, *, idioma: str, nome: str) -> None:
        fronteira = "forge" + secrets.token_hex(12)
        snippet = json.dumps({"snippet": {
            "videoId": video_id, "language": idioma, "name": nome, "isDraft": False,
        }}, ensure_ascii=False)
        corpo = (
            f"--{fronteira}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{snippet}\r\n--{fronteira}\r\nContent-Type: application/octet-stream\r\n\r\n"
        ).encode("utf-8") + Path(caminho).read_bytes() + f"\r\n--{fronteira}--\r\n".encode()
        self._com_tentativas(lambda: self._pedir(
            "POST", LEGENDA_URL, params={"part": "snippet", "uploadType": "multipart"},
            headers=self._cabecalhos(**{
                "Content-Type": f"multipart/related; boundary={fronteira}"}),
            content=corpo))


__all__ = [
    "YouTubeAuthError", "YouTubeClient", "YouTubeError", "YouTubeQuotaError",
    "YouTubeSessaoExpirada",
]
