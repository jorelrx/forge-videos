"""Contrato das fontes remotas + orquestrador buscar->baixar paginado.

`buscar(query, pagina)` devolve uma página de candidatos leves (Referencia); o
orquestrador pagina cada fonte até juntar `limite` documentos NOVOS, pulando os
que já estão na base (`ja_ingerido`) e seguindo para o próximo da lista. Tudo
best-effort: fonte ou referência que falha loga e é pulada, nunca derruba o
lote (mesmo ethos da camada de conhecimento).
"""
from collections.abc import Callable
from typing import Protocol

from pydantic import BaseModel

from forge.infrastructure.logging import get_logger
from forge.knowledge.domain.models import Documento

logger = get_logger(__name__)


class Referencia(BaseModel):
    fonte: str
    id_externo: str
    titulo: str
    autor: str | None = None
    url: str
    idioma: str | None = None

    @property
    def chave_externa(self) -> str:
        """Identidade da obra na fonte. Conhecida antes do download, ao contrário
        do hash — é o que permite pular o que já está na base."""
        return f"{self.fonte}::{self.id_externo}"

    @property
    def chave(self) -> str:
        return self.chave_externa


class FonteRemota(Protocol):
    nome: str
    # Opcional: idioma no qual a fonte só busca (ex: "en" para SEP). Quando
    # definido, a query é traduzida para esse idioma antes de buscar.
    idioma_busca: str | None

    def buscar(self, query: str, *, http, pagina: int) -> list[Referencia]: ...

    def baixar(self, ref: Referencia, *, http) -> Documento: ...


def _nunca(_chave: str) -> bool:
    return False


def _query_da_fonte(fonte, query: str, traduzir, cache: dict[str, str]) -> str:
    """Traduz a query para o idioma_busca da fonte, se houver. Memoiza por idioma
    para não traduzir a mesma coisa em toda página/fonte."""
    idioma = getattr(fonte, "idioma_busca", None)
    if not idioma or traduzir is None:
        return query
    if idioma not in cache:
        cache[idioma] = traduzir(query, idioma)
    return cache[idioma]


def buscar_e_baixar(
    fontes,
    query: str,
    *,
    limite: int,
    http,
    ja_ingerido: Callable[[str], bool] = _nunca,
    max_paginas: int = 10,
    traduzir: Callable[[str, str], str] | None = None,
) -> list[Documento]:
    """Para cada fonte, pagina a busca até juntar `limite` documentos novos.

    `ja_ingerido(chave)` diz se um doc já está na base: True -> pula e segue para
    o próximo da lista (não sobrescreve por padrão). Uma fonte para quando junta
    `limite`, quando uma página não traz nenhuma referência inédita (esgotou ou
    não pagina), ou ao atingir `max_paginas`. `traduzir(texto, idioma)` traduz a
    query para fontes que declaram `idioma_busca` (ex: SEP só-inglês).
    """
    vistos: set[str] = set()
    trad_cache: dict[str, str] = {}
    docs: list[Documento] = []
    for fonte in fontes:
        query_fonte = _query_da_fonte(fonte, query, traduzir, trad_cache)
        novos = 0
        for pagina in range(1, max_paginas + 1):
            if novos >= limite:
                break
            try:
                refs = fonte.buscar(query_fonte, http=http, pagina=pagina)
            except Exception as e:
                logger.warning("Fonte falhou na busca", fonte=fonte.nome, pagina=pagina, error=str(e))
                break
            if not refs:
                break  # fonte esgotou
            viu_inedito = False
            for ref in refs:
                if ref.chave in vistos:
                    continue
                viu_inedito = True
                vistos.add(ref.chave)
                if ja_ingerido(ref.chave):
                    logger.info("Já ingerido, pulando", fonte=ref.fonte, id=ref.id_externo)
                    continue
                try:
                    doc = fonte.baixar(ref, http=http)
                except Exception as e:
                    logger.warning("Download falhou", fonte=ref.fonte, id=ref.id_externo, error=str(e))
                    continue
                if not doc.texto.strip():
                    logger.warning("Documento vazio descartado", fonte=ref.fonte, id=ref.id_externo)
                    continue
                docs.append(doc)
                novos += 1
                if novos >= limite:
                    break
            if not viu_inedito:
                break  # página sem nada inédito -> esgotou ou não pagina
        logger.info("Fonte concluída", fonte=fonte.nome, novos=novos)
    logger.info("Aquisição concluída", docs=len(docs))
    return docs
