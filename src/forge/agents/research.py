"""Pesquisa contra o acervo.

Três fases, nesta ordem: o LLM formula as queries, o cliente HTTP busca, o LLM
sintetiza o brief a partir do que voltou. As fontes NÃO passam pelo modelo —
são construídas das passagens. A extração por LLM que existia aqui antes era a
origem das citações inventadas: o modelo relia o próprio brief e reconstruía
referências de memória.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from forge.domain.models import Fonte, VeredictoRelevancia
from forge.infrastructure.logging import get_logger
from forge.llms.parsing import MARCADOR_LISTA, _texto
from forge.llms.model import invoke_structured
from forge.prompts.loader import load_prompt
from forge.services.acervo import AcervoIndisponivel, Acervo, Candidato, Passagem, fmt_catalogo
from forge.services.lacunas import registrar_lacuna
from forge.services.progresso import ProgressoLogger
from forge.skills.loader import load_skills

logger = get_logger(__name__)

SKILLS = ["fact_check"]
LE = ["tema", "pedido", "research_notes", "research_passages", "run_dir"]

MAX_QUERIES = 5

# Motivo registrado quando uma query não achou passagem nenhuma — distinto do
# motivo do juiz, que só existe quando há passagens para rejeitar.
_MOTIVO_BUSCA_VAZIA = "a busca não retornou nenhuma passagem para esta query"

# Tamanho de pool a partir do qual uma reprovação TOTAL do juiz é lida como
# defeito do juiz, não como lacuna do acervo.
#
# O raciocínio é de plausibilidade. `acervo_top` é 8 por query: um pool de uma
# ou duas passagens reprovado inteiro é perfeitamente possível — uma query
# marginal, dois resultados de raspa. Um pool de uma dúzia, montado a partir de
# várias queries e sobrevivendo ao dedupe, reprovado item por item sem exceção,
# é muito mais provavelmente um veredicto degenerado (lista vazia por falha de
# structured output, um 9B local perdendo o formato) do que um acervo que
# devolveu doze passagens de alto score e nenhuma serve.
#
# A troca é consciente e assimétrica: acima do piso perdemos a detecção de
# lacuna que D8 existe para fazer, e ganhamos a garantia de que um veredicto
# ruim não produza um roteiro sem fonte nenhuma. Abaixo do piso a lacuna
# continua sendo registrada normalmente.
POOL_MINIMO_PARA_DESCONFIAR_DO_JUIZ = 12


class PassageEvidence(BaseModel):
    """Evidence returned by the acervo, kept separate from model prose."""

    path: str
    book_id: int | None = None
    title: str
    authors: list[str] = Field(default_factory=list)
    text: str
    # Endereço público da obra (Project Gutenberg), quando o acervo informa.
    # Vai para a seção de fontes da descrição do vídeo.
    url: str = ""


class ResearchBundle(BaseModel):
    """Typed research result with the raw passages used by the stage gate.

    ``pesquisar`` historically returned ``(brief, fontes, raw_markdown)``.
    Iteration preserves that small public contract for the graph and older
    callers while exposing the evidence needed by Studio executors.
    """

    brief: str
    fontes: list[Fonte]
    raw_markdown: str
    passages: list[PassageEvidence]
    passage_count: int
    canonical_paths: list[str]
    unanswered_queries: list[str] = Field(default_factory=list)

    def __iter__(self):
        yield self.brief
        yield self.fontes
        yield self.raw_markdown


def pesquisar(
    model,
    tema: str,
    acervo: Acervo,
    pedido: str | None = None,
    *,
    top: int | None = None,
    settings=None,
    run_dir=None,
) -> ResearchBundle:
    progresso = ProgressoLogger(run_dir) if run_dir else None

    catalogo = _catalogo(acervo)
    queries = formular_queries(model, tema, pedido, catalogo)
    if progresso:
        progresso.log("research", "queries_formuladas",
                      prompt=load_prompt("queries").format(
                          tema=tema, pedido=_fmt_pedido(pedido), catalogo=catalogo,
                      ),
                      resultado="\n".join(queries),
                      metadados={"num_queries": len(queries)})

    # `top=None` deixa o default do próprio `colher_por_query` decidir — não
    # duplicamos aqui o valor de fallback.
    por_query = (
        colher_por_query(acervo, queries, top=top)
        if top is not None
        else colher_por_query(acervo, queries)
    )
    passagens = _fundir(por_query)
    bruto = _bruto(queries, passagens)

    if progresso:
        texto_passagens = "\n".join(
            f"[{i}] {p.book_title} — score={p.score:.4f} — {p.text[:300]}"
            for i, p in enumerate(passagens)
        )
        progresso.log("research", "busca_completada",
                      resultado=texto_passagens,
                      metadados={"total_passagens": len(passagens),
                                 "queries": queries})

    julgou = False
    if passagens and settings is not None and settings.juiz_relevancia:
        passagens = _julgar_e_registrar(
            model, tema, passagens, por_query, settings, queries=queries, pedido=pedido,
            run_dir=run_dir,
        )
        julgou = True
        if progresso:
            progresso.log("research", "juiz_relevancia",
                          resultado=f"Aprovadas: {len(passagens)}/{len(_fundir(por_query))}",
                          metadados={"aprovadas": len(passagens)})

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
        if progresso:
            progresso.log("research", "lacuna_detectada",
                          metadados={"candidatos": len(candidatos)})
        return _bundle(
            _brief_lacuna(tema, candidatos), [], bruto, passagens,
            unanswered_queries=list(por_query),
        )

    if settings is not None and not julgou:
        # With the relevance judge disabled, a partial pool still contains
        # queries the acervo answered with zero passages. Record those as
        # evidence just as in the all-empty branch; otherwise the lacuna would
        # disappear merely because another query happened to succeed.
        vazias = {query: achadas for query, achadas in por_query.items() if not achadas}
        if vazias:
            _registrar_lacunas_de_busca_vazia(vazias, tema, settings)

    brief = _sintetizar(model, tema, pedido, passagens)
    if progresso:
        progresso.log("research", "sintese_concluida",
                      resultado=brief,
                      metadados={"passagens_usadas": len(passagens)})
    logger.info("Research completed", queries=len(queries), passagens=len(passagens))
    return _bundle(
        brief,
        _fontes(passagens),
        bruto,
        passagens,
        unanswered_queries=_unanswered_queries(por_query, passagens),
    )


def _julgar_e_registrar(
    model, tema, passagens, por_query, settings, *, queries=None, pedido=None,
    run_dir=None,
):
    """Filtra pelo juiz e devolve ao acervo as queries que não renderam nada.

    A lacuna é por QUERY, não pelo tema: é a pergunta específica que o acervo não
    soube responder, e é ela que diz qual obra falta ingerir. "Não renderam nada"
    cobre duas formas, com motivo distinto: a busca não achou passagem nenhuma
    para a query (não passou pelo juiz — não há o que julgar), ou achou passagens
    e o juiz rejeitou todas.

    **A atribuição por query é aproximada, e continua sendo.** O juiz recebe o
    pool FUNDIDO de todas as queries e devolve um veredicto só; nós inferimos
    "esta query não rendeu nada" olhando se sobrou algum caminho dela entre as
    aprovadas. Uma passagem que veio de duas queries salva as duas. Isso é o
    preço de uma chamada de LLM por pesquisa em vez de uma por query: cinco
    chamadas de 3-9 min cada são inviáveis nesta máquina. Passar as queries ao
    prompt melhora o veredicto — o juiz passa a julgar contra a necessidade de
    informação real, não contra o tema nu —, mas não desfaz a fusão.

    O juiz é OPCIONAL (`FORGE_JUIZ_RELEVANCIA`); o roteiro não é. Por isso as
    duas guardas abaixo: falha da chamada e veredicto degenerado ambos caem
    para "mantém tudo, registra nada".
    """
    # Import tardio: `lacunas` importa `Settings`, e o agente de pesquisa não
    # depende de config em lugar nenhum além daqui.
    from forge.services.lacunas import registrar_lacuna

    try:
        aprovadas, motivo_juiz = julgar_relevancia(
            model, tema, passagens, queries=queries, pedido=pedido, run_dir=run_dir
        )
    except Exception as e:
        # Timeout de 10 min, `400 Model unloaded by user` (que o cliente OpenAI
        # não retenta), validação de structured output que o modelo local erra:
        # qualquer uma matava o grafo duas horas run adentro. Falhar em produzir
        # um benefício opcional não pode destruir a saída obrigatória — mesma
        # postura que `services/lacunas.py` documenta para as escritas.
        logger.error(
            "Juiz de relevância falhou; seguindo com todas as passagens",
            erro=str(e), passagens=len(passagens),
        )
        return passagens

    if not aprovadas and len(passagens) >= POOL_MINIMO_PARA_DESCONFIAR_DO_JUIZ:
        # Piso de sanidade, irmão do piso de cobertura do plano de mídia. Sem
        # ele, um único veredicto vazio esvazia `passagens`, o controle cai no
        # ramo de "o acervo não tem o livro", a síntese é pulada, `fontes` fica
        # vazia — e `write` não tem guarda para isso, então o pipeline redige
        # nove seções em cima de um brief que diz não haver fonte alguma, e
        # `storage.py` renderiza o roteiro com o bloco de fontes vazio.
        # Afirmar sem caminho citável é o pecado original deste projeto.
        #
        # `error`, e com mensagem distinta do `warning "Acervo gap"`: no log de
        # um loop desassistido isto precisa ser separável de uma lacuna real.
        logger.error(
            "Juiz reprovou o pool inteiro; tratando como falha do juiz, não como lacuna",
            passagens=len(passagens), piso=POOL_MINIMO_PARA_DESCONFIAR_DO_JUIZ,
            motivo=motivo_juiz,
        )
        return passagens

    caminhos_ok = {p.path for p in aprovadas}
    for query, achadas in por_query.items():
        if not achadas:
            # `so_evidencia`: o acervo já anotou esta pergunta sozinho durante
            # a busca que acabamos de fazer. Ver `registrar_lacuna`.
            registrar_lacuna(
                settings, query=query, tema=tema,
                motivo=_MOTIVO_BUSCA_VAZIA, passagens=[], so_evidencia=True,
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

    Só evidência, nunca o `gaps_file`: o acervo registra a pergunta ele mesmo
    quando a busca não casa com nada (`routers/search.py`, ramo
    `if not passages: container.log_unanswered(q)`), e ele o faz dentro da
    mesma chamada HTTP que acabamos de fazer. A nossa cópia era pura
    duplicação — o dedupe da leitura a suprimia, então esse ramo não
    contribuía nada para o arquivo deles. O que o acervo NÃO detecta, e por
    isso continua indo para lá, é a rejeição do juiz.
    """
    from forge.services.lacunas import registrar_lacuna

    for query in por_query:
        registrar_lacuna(
            settings, query=query, tema=tema, motivo=_MOTIVO_BUSCA_VAZIA,
            passagens=[], so_evidencia=True,
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


CATALOGO_INDISPONIVEL = "(catálogo indisponível)"


def _catalogo(acervo) -> str:
    """Catálogo para orientar as queries; nunca impede a pesquisa.

    Sem saber que livros existem e em que idioma estão, o modelo escreve as
    buscas em português contra um acervo em inglês e alemão, e a busca semântica
    volta com trechos fora do tema. O catálogo é só orientação: se a rota falhar
    ou o cliente não a tiver, a pesquisa segue como antes.
    """
    livros = getattr(acervo, "livros", None)
    if livros is None:
        return CATALOGO_INDISPONIVEL
    try:
        return fmt_catalogo(livros())
    except AcervoIndisponivel as erro:
        logger.warning("Catálogo indisponível para as queries", error=str(erro))
        return CATALOGO_INDISPONIVEL


def formular_queries(
    model, tema: str, pedido: str | None = None, catalogo: str | None = None,
) -> list[str]:
    prompt = load_prompt("queries").format(
        tema=tema, pedido=_fmt_pedido(pedido),
        catalogo=catalogo or CATALOGO_INDISPONIVEL,
    )
    resp = model.invoke([HumanMessage(content=prompt)])
    queries = _parse_queries(_texto(resp))
    logger.debug("Queries formuladas", queries=queries)
    return queries


def _parse_queries(texto: str) -> list[str]:
    """Uma query por linha, sem marcador e sem aspas, deduplicadas."""
    queries: list[str] = []
    for linha in texto.splitlines():
        q = MARCADOR_LISTA.sub("", linha).strip().strip('"')
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
        # `\r` junto com `\n`: o acervo indexa livros de domínio público cujo
        # texto-fonte vem com quebra CRLF, e um `\r` solto no meio do prompt
        # embaralha a numeração `[i]` que o juiz precisa ler.
        trecho = p.text[:chars].replace("\r", " ").replace("\n", " ")
        linhas.append(f"[{i}] {p.book_title} — {autores} — {p.breadcrumb}\n{trecho}")
    return "\n\n".join(linhas)


def _fmt_queries_juiz(queries: list[str] | None) -> str:
    """As perguntas que de fato foram ao acervo.

    Sem elas o juiz via só o tema, e o spec (S8) pede "a query e as passagens".
    A diferença é concreta: uma passagem pode estar no tema e não responder à
    query — e era registrada como respondida —, ou responder à query e parecer
    fora do tema — e ia parar no arquivo de lacunas do usuário como
    irrespondível.
    """
    if not queries:
        return "(as perguntas exatas não foram informadas; julgue pelo assunto)"
    return "\n".join(f"- {q}" for q in queries)


def _fmt_pedido_juiz(pedido: str | None) -> str:
    """O pedido dirigido do handoff `review → research`.

    Nessa volta `pedido` carrega a alegação específica a conferir, e o juiz não
    a via: ele aprovava qualquer coisa vagamente sobre livre-arbítrio enquanto
    a alegação seguia sem checagem. Essa volta custa ~50 min nesta máquina.
    """
    if not pedido:
        return ""
    return (
        "\nEsta pesquisa é dirigida: o que precisa ser confirmado ou refutado é\n"
        f"exatamente isto.\n\n{pedido}\n\n"
        "Uma passagem que não toca nisso NÃO serve, por mais que fale do assunto.\n"
    )


def julgar_relevancia(
    model,
    tema: str,
    passagens: list[Passagem],
    *,
    queries: list[str] | None = None,
    pedido: str | None = None,
    run_dir=None,
) -> tuple[list[Passagem], str]:
    prompt = load_prompt("juiz").format(
        tema=tema,
        queries=_fmt_queries_juiz(queries),
        pedido=_fmt_pedido_juiz(pedido),
        passagens=_fmt_passagens_curtas(passagens),
    )
    veredicto = invoke_structured(
        model, VeredictoRelevancia, [HumanMessage(content=prompt)],
        run_dir=run_dir, etapa="research", subfase="juiz_relevancia_structured",
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


def _unanswered_queries(
    por_query: dict[str, list[Passagem]], passagens: list[Passagem]
) -> list[str]:
    """Return queries with no accepted canonical evidence.

    Query attribution is intentionally approximate: a fused passage can answer
    more than one query. A missing path never counts as accepted evidence.
    """
    accepted = {p.path for p in passagens if p.path}
    return [
        query
        for query, candidates in por_query.items()
        if not candidates or not any(p.path in accepted for p in candidates)
    ]


def _bundle(
    brief: str,
    fontes: list[Fonte],
    raw_markdown: str,
    passagens: list[Passagem],
    *,
    unanswered_queries: list[str],
) -> ResearchBundle:
    evidence = [
        PassageEvidence(
            path=p.path or "",
            book_id=p.book_id,
            title=p.book_title,
            authors=list(p.authors),
            text=p.text,
            url=p.url,
        )
        for p in passagens
    ]
    canonical_paths = list(dict.fromkeys(item.path for item in evidence if item.path))
    return ResearchBundle(
        brief=brief,
        fontes=fontes,
        raw_markdown=raw_markdown,
        passages=evidence,
        passage_count=len(evidence),
        canonical_paths=canonical_paths,
        unanswered_queries=list(dict.fromkeys(unanswered_queries)),
    )


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
