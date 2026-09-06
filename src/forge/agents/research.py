"""Pesquisa contra o acervo.

Três fases, nesta ordem: o LLM formula as queries, o cliente HTTP busca, o LLM
sintetiza o brief a partir do que voltou. As fontes NÃO passam pelo modelo —
são construídas das passagens. A extração por LLM que existia aqui antes era a
origem das citações inventadas: o modelo relia o próprio brief e reconstruía
referências de memória.
"""

from __future__ import annotations

import re

from langchain_core.messages import HumanMessage

from forge.domain.models import Fonte
from forge.infrastructure.logging import get_logger
from forge.llms.parsing import _texto
from forge.prompts.loader import load_prompt
from forge.services.acervo import Acervo, Candidato, Passagem
from forge.skills.loader import load_skills

logger = get_logger(__name__)

SKILLS = ["fact_check"]
LE = ["tema", "pedido", "research_notes"]

MAX_QUERIES = 5

# Marcador de lista que o modelo insiste em emitir mesmo quando o prompt pede
# uma linha limpa.
_MARCADOR = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")


def pesquisar(
    model, tema: str, acervo: Acervo, pedido: str | None = None
) -> tuple[str, list[Fonte], str]:
    queries = formular_queries(model, tema, pedido)
    passagens = colher(acervo, queries)
    bruto = _bruto(queries, passagens)

    if not passagens:
        candidatos = acervo.descobrir(tema)
        logger.warning("Acervo gap", tema=tema, sugestoes=len(candidatos))
        return _brief_lacuna(tema, candidatos), [], bruto

    brief = _sintetizar(model, tema, pedido, passagens)
    logger.info("Research completed", queries=len(queries), passagens=len(passagens))
    return brief, _fontes(passagens), bruto


def formular_queries(model, tema: str, pedido: str | None = None) -> list[str]:
    prompt = load_prompt("queries").format(tema=tema, pedido=_fmt_pedido(pedido))
    resp = model.invoke([HumanMessage(content=prompt)])
    queries = _parse_queries(_texto(resp))
    logger.debug("Queries formuladas", queries=queries)
    return queries


def _parse_queries(texto: str) -> list[str]:
    """Uma query por linha, sem marcador e sem aspas, deduplicadas."""
    queries: list[str] = []
    for linha in texto.splitlines():
        q = _MARCADOR.sub("", linha).strip().strip('"')
        if q and q not in queries:
            queries.append(q)
    return queries[:MAX_QUERIES]


def colher(acervo: Acervo, queries: list[str], *, top: int = 8) -> list[Passagem]:
    """Busca cada query e funde os resultados.

    A mesma passagem costuma responder a mais de uma query. Deduplicar por
    `path` e guardar o maior score preserva a ordenação por relevância; guardar
    o último visto a destruiria.
    """
    por_path: dict[str, Passagem] = {}
    for q in queries:
        for p in acervo.buscar(q, top=top):
            atual = por_path.get(p.path)
            if atual is None or p.score > atual.score:
                por_path[p.path] = p
    return sorted(por_path.values(), key=lambda p: p.score, reverse=True)


def _sintetizar(model, tema: str, pedido: str | None, passagens: list[Passagem]) -> str:
    prompt = load_prompt("research").format(
        tema=tema,
        skills=load_skills(SKILLS, "research"),
        pedido=_fmt_pedido(pedido),
        passagens=_fmt_passagens(passagens),
    )
    return _texto(model.invoke([HumanMessage(content=prompt)]))


def _fmt_passagens(passagens: list[Passagem]) -> str:
    blocos = []
    for p in passagens:
        autores = ", ".join(p.authors) or "autor não identificado"
        blocos.append(f"[{p.path}] {p.book_title} — {autores}\n{p.breadcrumb}\n\n{p.text}")
    return "\n\n---\n\n".join(blocos)


def _fontes(passagens: list[Passagem]) -> list[Fonte]:
    return [
        Fonte(
            titulo=p.book_title,
            autor=", ".join(p.authors) or None,
            url=p.url or None,
            frase=p.text,
            path=p.path,
            book_id=p.book_id,
        )
        for p in passagens
    ]


def _brief_lacuna(tema: str, candidatos: list[Candidato]) -> str:
    """Brief de acervo vazio.

    Relatar a lacuna é o comportamento correto: o modelo não é chamado, então
    não tem como preencher o vazio de memória.
    """
    linhas = [
        "## Lacuna no acervo",
        "",
        f"Nenhuma passagem do acervo cobre: {tema}",
        "",
        "Sem fonte, o roteiro não pode afirmar nada sobre este ponto.",
        "Ingira uma destas obras no acervo e rode de novo:",
        "",
    ]
    if not candidatos:
        linhas.append("- (o /discover do acervo não sugeriu nenhuma obra)")
    for c in candidatos:
        autores = ", ".join(c.authors) or "autor não identificado"
        linhas.append(f"- [{c.id}] {c.title} — {autores}")
    return "\n".join(linhas)


def _bruto(queries: list[str], passagens: list[Passagem]) -> str:
    """Sidecar `.raw.md`: o que foi perguntado e o que voltou, sem síntese."""
    cabeca = "\n".join(f"- {q}" for q in queries) or "(nenhuma)"
    corpo = _fmt_passagens(passagens) if passagens else "(nenhuma passagem)"
    return f"## Queries\n\n{cabeca}\n\n## Passagens\n\n{corpo}"


def _fmt_pedido(pedido: str | None) -> str:
    if not pedido:
        return ""
    return (
        "ATENÇÃO — esta é uma passagem dirigida, não uma pesquisa do zero.\n"
        "Verifique apenas os pontos abaixo e devolva o que confirmou ou não:\n"
        f"{pedido}"
    )
