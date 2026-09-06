"""Cliente da API `acervo` — a única fonte de material de pesquisa do forge.

O acervo indexa livros de domínio público e devolve passagens com caminho
canônico estável. É esse caminho (`Passagem.path`) que o roteiro cita: ele
sobrevive à re-fragmentação de outros livros, ao contrário de um número de
página ou de um offset.

Nenhuma chamada de LLM acontece aqui. O módulo traduz HTTP em modelos e nada
mais.
"""

from __future__ import annotations

import httpx
from pydantic import BaseModel, Field

from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)


class AcervoIndisponivel(RuntimeError):
    """O acervo não respondeu.

    Levantar em vez de cair para busca web é deliberado: um fallback silencioso
    devolveria material sem caminho citável, que é exatamente o que este
    desenho elimina.
    """


class Passagem(BaseModel):
    """Espelha `PassageOut` da API. Campos extras da resposta são ignorados."""

    path: str
    book_id: int
    book_title: str
    authors: list[str] = Field(default_factory=list)
    breadcrumb: str = ""
    text: str
    url: str = ""
    score: float = 0.0


class Candidato(BaseModel):
    """Espelha `CandidateOut` do `/discover`: obra sugerida, ainda não ingerida."""

    id: int
    title: str
    authors: list[str] = Field(default_factory=list)
    ingested: bool = False


class Acervo:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        # `client` entra por injeção para que o teste use MockTransport e a
        # suíte inteira rode sem rede.
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"), timeout=timeout
        )

    def _get(self, rota: str, params: dict) -> dict:
        try:
            resp = self._client.get(rota, params=params)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError) as e:
            logger.error("Acervo request failed", rota=rota, error=str(e))
            raise AcervoIndisponivel(f"acervo não respondeu em {rota}: {e}") from e

    def saude(self) -> bool:
        try:
            self._get("/health", {})
        except AcervoIndisponivel:
            return False
        return True

    def buscar(
        self,
        q: str,
        *,
        top: int = 8,
        excerpt: int = 160,
        rerank: bool = False,
        neighbours: bool = False,
    ) -> list[Passagem]:
        dados = self._get(
            "/search",
            {
                "q": q,
                "top": top,
                "excerpt": excerpt,
                "rerank": rerank,
                "neighbours": neighbours,
            },
        )
        passagens = [Passagem(**p) for p in dados.get("passages", [])]
        logger.info("Acervo search", query=q, passagens=len(passagens))
        return passagens

    def descobrir(self, q: str, *, limite: int = 5) -> list[Candidato]:
        """Obras que o acervo *poderia* ter mas não tem.

        Usado só para relatar a lacuna ao usuário — o forge nunca ingere nada.
        """
        dados = self._get("/discover", {"q": q})
        candidatos = [Candidato(**c) for c in dados.get("candidates", [])]
        return candidatos[:limite]
