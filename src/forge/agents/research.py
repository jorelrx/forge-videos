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

from forge.domain.models import Fonte, VeredictoRelevancia
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

# Motivo registrado quando uma query não achou passagem nenhuma — distinto do
# motivo do juiz, que só existe quando há passagens para rejeitar.
_MOTIVO_BUSCA_VAZIA = "a busca não retornou nenhuma passagem para esta query"


def pesquisar(
    model,
    tema: str,
    acervo: Acervo,
    pedido: str | None = None,
    *,
    top: int | None = None,
    settings=None,
) -> tuple[str, list[Fonte], str]:
    queries = formular_queries(model, tema, pedido)
    # `top=None` deixa o default do próprio `colher_por_query` decidir — não
    # duplicamos aqui o valor de fallback.
    por_query = (
        colher_por_query(acervo, queries, top=top)
        if top is not None
        else colher_por_query(acervo, queries)
    )
    passagens = _fundir(por_query)
    bruto = _bruto(queries, passagens)

    julgou = False
    if passagens and settings is not None and settings.juiz_relevancia:
        passagens = _julgar_e_registrar(model, tema, passagens, por_query, settings)
        julgou = True

    if not passagens:
        # Se o juiz rodou, ele já registrou lacuna por query dentro de
        # `_julgar_e_registrar` (rejeitadas e vazias). Se não rodou, é porque
        # NENHUMA query achou nada — o gate `if passagens` acima nem chegou a
        # olhar `juiz_relevancia`. Registrar aqui não depende dessa flag:
        # `juiz_relevancia=False` só significa "não gaste uma chamada de LLM
        # decidindo relevância"; constatar que a busca devolveu zero linhas
        # não exige julgamento nenhum, então amarrar isso à flag surpreenderia
        # quem a desligou só para economizar a chamada extra.
        if settings is not None and not julgou:
            _registrar_lacunas_de_busca_vazia(por_query, tema, settings)
        candidatos = acervo.descobrir(tema)
        logger.warning("Acervo gap", tema=tema, sugestoes=len(candidatos))
        return _brief_lacuna(tema, candidatos), [], bruto

    brief = _sintetizar(model, tema, pedido, passagens)
    logger.info("Research completed", queries=len(queries), passagens=len(passagens))
    return brief, _fontes(passagens), bruto


def _julgar_e_registrar(model, tema, passagens, por_query, settings):
    """Filtra pelo juiz e devolve ao acervo as queries que não renderam nada.

    A lacuna é por QUERY, não pelo tema: é a pergunta específica que o acervo não
    soube responder, e é ela que diz qual obra falta ingerir. "Não renderam nada"
    cobre duas formas, com motivo distinto: a busca não achou passagem nenhuma
    para a query (não passou pelo juiz — não há o que julgar), ou achou passagens
    e o juiz rejeitou todas.
    """
    # Import tardio: `lacunas` importa `Settings`, e o agente de pesquisa não
    # depende de config em lugar nenhum além daqui.
    from forge.services.lacunas import registrar_lacuna

    aprovadas, motivo_juiz = julgar_relevancia(model, tema, passagens)
    caminhos_ok = {p.path for p in aprovadas}
    for query, achadas in por_query.items():
        if not achadas:
            registrar_lacuna(
                settings, query=query, tema=tema,
                motivo=_MOTIVO_BUSCA_VAZIA, passagens=[],
            )
        elif not any(p.path in caminhos_ok for p in achadas):
            registrar_lacuna(
                settings, query=query, tema=tema, motivo=motivo_juiz, passagens=achadas
            )
    return aprovadas


def _registrar_lacunas_de_busca_vazia(por_query, tema, settings):
    """Registra cada query como lacuna quando a busca não achou NADA, sem juiz.

    Caminho irmão de `_julgar_e_registrar`, para quando o juiz nunca chega a
    rodar (nenhuma query achou passagem nenhuma): não há passagens para julgar,
    então não há chamada de LLM a fazer aqui.
    """
    from forge.services.lacunas import registrar_lacuna

    for query in por_query:
        registrar_lacuna(
            settings, query=query, tema=tema, motivo=_MOTIVO_BUSCA_VAZIA, passagens=[]
        )


def _fundir(por_query: dict[str, list[Passagem]]) -> list[Passagem]:
    """Dedupe por path guardando o maior score, ordenado por relevância.

    A mesma passagem costuma responder a mais de uma query; guardar a última
    vista destruiria a ordenação.
    """
    por_path: dict[str, Passagem] = {}
    for achadas in por_query.values():
        for p in achadas:
            atual = por_path.get(p.path)
            if atual is None or p.score > atual.score:
                por_path[p.path] = p
    return sorted(por_path.values(), key=lambda p: p.score, reverse=True)


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

    Delega a `colher_por_query` + `_fundir`: a origem por query importa para
    detectar lacuna, mas `colher` continua devolvendo só o pool ordenado.
    """
    return _fundir(colher_por_query(acervo, queries, top=top))


def colher_por_query(
    acervo: Acervo, queries: list[str], *, top: int = 8
) -> dict[str, list[Passagem]]:
    """Busca cada query preservando de qual delas veio cada passagem.

    `colher` funde tudo num pool ordenado, que é o que a síntese quer. A origem
    importa para outra coisa: saber qual pergunta o acervo não soube responder.
    """
    return {q: acervo.buscar(q, top=top) for q in queries}


def _fmt_passagens_curtas(passagens: list[Passagem], *, chars: int = 200) -> str:
    """Só o suficiente para julgar pertinência — o texto inteiro custaria minutos."""
    linhas = []
    for i, p in enumerate(passagens):
        autores = ", ".join(p.authors) or "autor não identificado"
        trecho = p.text[:chars].replace("\n", " ")
        linhas.append(f"[{i}] {p.book_title} — {autores} — {p.breadcrumb}\n{trecho}")
    return "\n\n".join(linhas)


def julgar_relevancia(
    model, tema: str, passagens: list[Passagem]
) -> tuple[list[Passagem], str]:
    prompt = load_prompt("juiz").format(
        tema=tema, passagens=_fmt_passagens_curtas(passagens)
    )
    veredicto = model.with_structured_output(VeredictoRelevancia).invoke(
        [HumanMessage(content=prompt)]
    )
    # Índice fora da faixa é erro de modelo, não motivo para estourar: descarta.
    validos = sorted({i for i in veredicto.relevantes if 0 <= i < len(passagens)})
    aprovadas = [passagens[i] for i in validos]
    logger.info(
        "Juiz de relevância",
        recebidas=len(passagens),
        aprovadas=len(aprovadas),
    )
    return aprovadas, veredicto.motivo


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
