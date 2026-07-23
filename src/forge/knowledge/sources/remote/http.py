"""Cliente HTTP compartilhado das fontes remotas + cache raw em disco.

A rede fica confinada aqui; os parsers de cada fonte são puros. O cache grava o
corpo baixado em disco para reingest offline e para poupar os servidores das
fontes. `cliente` é injetável para os testes rodarem com httpx.MockTransport,
sem rede.
"""
import re
import time
from pathlib import Path

import httpx

from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)

_UA = "forge-videos/knowledge (+https://github.com)"
_RETRIABLE = {429, 500, 502, 503, 504}


def _sanitizar(nome: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", nome)[:180]


def _decodificar(resp: httpx.Response) -> str:
    """Decodifica o corpo dos bytes crus, sem adivinhação lossy.

    `resp.text` do httpx chuta o charset quando o header não declara e injeta
    U+FFFD irreversível ao errar — o que envenena a base com mojibake gravado.
    Aqui: respeita o charset declarado no header; senão tenta utf-8 e cai para
    cp1252/latin-1. latin-1 nunca levanta, então sempre há um resultado.
    """
    declarado = resp.charset_encoding  # None quando o header não declara charset
    dados = resp.content
    if declarado:
        try:
            return dados.decode(declarado)
        except (LookupError, UnicodeDecodeError):
            pass
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return dados.decode(enc)
        except UnicodeDecodeError:
            continue
    return dados.decode("latin-1", errors="replace")


class Http:
    def __init__(
        self,
        *,
        cache_dir,
        rate_delay: float = 1.0,
        timeout: float = 30.0,
        tentativas: int = 3,
        cliente: httpx.Client | None = None,
    ):
        self._cache_dir = Path(cache_dir)
        self._rate_delay = rate_delay
        self._tentativas = tentativas
        self._cliente = cliente or httpx.Client(
            headers={"User-Agent": _UA}, timeout=timeout, follow_redirects=True
        )

    def get_json(self, url: str, *, params: dict | None = None) -> dict:
        return self._request(url, params=params).json()

    def get_text(self, url: str, *, params: dict | None = None) -> str:
        return _decodificar(self._request(url, params=params))

    def get_text_cacheado(self, url: str, *, fonte: str, id_externo: str, ext: str = "txt") -> str:
        caminho = self._cache_dir / fonte / f"{_sanitizar(id_externo)}.{ext}"
        if caminho.exists():
            logger.debug("Cache hit", fonte=fonte, id=id_externo)
            return caminho.read_text(encoding="utf-8")
        texto = self.get_text(url)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(texto, encoding="utf-8")
        logger.debug("Cache gravado", fonte=fonte, id=id_externo, chars=len(texto))
        return texto

    def _request(self, url: str, *, params: dict | None = None) -> httpx.Response:
        ultimo: Exception | None = None
        for tentativa in range(self._tentativas):
            try:
                resp = self._cliente.get(url, params=params)

                # Retriable statuses: raise to trigger retry logic
                if resp.status_code in _RETRIABLE:
                    raise httpx.HTTPStatusError(
                        "status retriável", request=resp.request, response=resp
                    )

                # Check for HTTP errors and raise if any
                resp.raise_for_status()

                # Success: apply rate limiting and return
                if self._rate_delay:
                    time.sleep(self._rate_delay)
                return resp
            except httpx.HTTPStatusError as e:
                # Non-retriable status: re-raise immediately without retry
                if e.response.status_code >= 400 and e.response.status_code not in _RETRIABLE:
                    raise

                # Retriable status: proceed with retry logic
                ultimo = e
                logger.debug("Request falhou, retry", url=url, tentativa=tentativa)

                # Backoff sleep: only if not the last attempt
                if tentativa < self._tentativas - 1 and self._rate_delay:
                    time.sleep(self._rate_delay * (tentativa + 1))
            except httpx.HTTPError as e:
                # Other HTTP errors (network errors, etc.)
                ultimo = e
                logger.debug("Request falhou, retry", url=url, tentativa=tentativa)

                # Backoff sleep: only if not the last attempt
                if tentativa < self._tentativas - 1 and self._rate_delay:
                    time.sleep(self._rate_delay * (tentativa + 1))
        assert ultimo is not None
        raise ultimo
