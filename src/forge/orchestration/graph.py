from langgraph.graph import END, StateGraph
from langgraph.types import Command

from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)

from forge.orchestration.state import RoteiroState
from forge.agents import plan as plan_stage
from forge.agents import research as research_stage
from forge.agents import review as review_stage
from forge.agents import tema as tema_stage
from forge.agents import write as write_stage
from forge.agents.research import PassageEvidence
from forge.services.acervo import Acervo
from forge.services.artefatos import gravar_artefato, gravar_bruto

def com_wrapper(nome, fn, le):
    """Estreita o state pelo LE do agente, grava o artefato, conta o passo."""
    def wrapped(state):
        entrada = {k: state[k] for k in le if k in state}
        resultado = fn(entrada)
        if isinstance(resultado, Command):
            atualizacao = dict(resultado.update or {})
            bruto = atualizacao.pop("_raw", None)
            gravar_artefato(state["run_dir"], nome, atualizacao)
            if bruto is not None:
                gravar_bruto(state["run_dir"], nome, bruto)
            return Command(
                graph=resultado.graph,
                resume=resultado.resume,
                goto=resultado.goto,
                update={**atualizacao, "passos": state.get("passos", 0) + 1},
            )
        bruto = resultado.pop("_raw", None)
        gravar_artefato(state["run_dir"], nome, resultado)
        if bruto is not None:
            gravar_bruto(state["run_dir"], nome, bruto)
        return {**resultado, "passos": state.get("passos", 0) + 1}
    return wrapped

def rotear(state: dict, max_rounds: int, max_passos: int) -> str:
    passos = state.get("passos", 0)
    if passos >= max_passos:
        logger.warning("Budget exhausted - stopping", passos=passos, max=max_passos)
        return END

    review = state.get("review")
    rounds = state.get("rounds", 0)
    if review is None:
        return "write"

    if review.verificar:
        logger.info("Handoff to research", alegacoes=len(review.verificar))
        return "research"

    if review.aprovado:
        logger.info("Review approved - stopping", round=rounds)
        return END

    if rounds >= max_rounds:
        logger.warning("Max review rounds reached", round=rounds, max=max_rounds)
        return END

    logger.debug("Continuing to write phase", round=rounds)
    return "write"

def build_graph(model, settings, inicio: str = "tema"):
    logger.info("Building graph", stages=["tema", "research", "plan", "write", "review"])

    # Um cliente por grafo: `research` é reentrado pelo reviewer e pelo write,
    # e abrir conexão nova a cada passagem não paga nada.
    acervo = Acervo(settings.acervo_url, timeout=settings.acervo_timeout)

    def node_tema(state):
        logger.debug("Running tema generation", tema=state.get("tema"))
        result = {"tema": tema_stage.gerar_tema(model, state.get("tema"))}
        logger.info("Tema generated", tema=result["tema"])
        return result

    def node_research(state):
        pedido = state.get("pedido")
        run_dir = state.get("run_dir")
        logger.debug("Starting research phase", tema=state["tema"], reentrada=bool(pedido))
        bundle = research_stage.pesquisar(
            model, state["tema"], acervo, pedido, top=settings.acervo_top, settings=settings,
            run_dir=run_dir,
        )
        brief, fontes, raw = bundle
        anterior = state.get("research_notes", "")
        combinado = f"{anterior}\n\n## Verificação dirigida\n\n{brief}".strip() if anterior else brief
        anteriores = list(state.get("research_passages", []))
        por_caminho = {
            evidencia.path: evidencia
            for evidencia in anteriores
            if getattr(evidencia, "path", None)
        }
        for evidencia in bundle.passages:
            por_caminho[evidencia.path] = evidencia
        combinadas = list(por_caminho.values())
        # Evidence without canonical path is retained too; it cannot anchor a
        # citation, but dropping it would make the typed research artifact lie
        # about what the acervo returned.
        combinadas.extend(
            evidencia for evidencia in [*anteriores, *bundle.passages]
            if not getattr(evidencia, "path", None)
        )
        logger.info("Research completed", num_fontes=len(fontes), reentrada=bool(pedido))
        return {
            "research_notes": combinado,
            "fontes": fontes,
            "research_passages": combinadas,
            "pedido": None,
            "_raw": raw,
        }

    def node_plan(state):
        logger.debug("Starting planning phase")
        tese, esboco = plan_stage.planejar(
            model, state["tema"], state["research_notes"], run_dir=state.get("run_dir")
        )
        result = {"tese": tese, "esboco": esboco}
        logger.info("Planning completed", tese=tese[:100] + "..." if len(tese) > 100 else tese)
        return result

    def node_write(state):
        review = state.get("review")
        notas = review.notas if review is not None else None
        logger.debug("Starting write phase", tema=state["tema"])
        roteiro, falta = write_stage.escrever(
            model,
            state["tema"],
            state["tese"],
            state["esboco"],
            state["research_notes"],
            state["fontes"],
            notas,
            run_dir=state.get("run_dir"),
        )
        if falta:
            logger.info("Handoff to research from write", motivo=falta[:120])
            return Command(goto="research", update={"roteiro": roteiro, "pedido": falta})
        logger.debug("Write phase completed", secoes_count=len(roteiro.secoes))
        return Command(goto="review", update={"roteiro": roteiro})

    def node_review(state):
        logger.debug("Starting review phase")
        result = review_stage.revisar(
            model, state["roteiro"], run_dir=state.get("run_dir")
        )
        rounds = state.get("rounds", 0) + 1
        pedido = "\n".join(result.verificar) if result.verificar else None
        logger.info("Review completed", aprovado=result.aprovado, round=rounds)
        return {"review": result, "rounds": rounds, "pedido": pedido}

    g = StateGraph(RoteiroState)
    g.add_node("tema",     com_wrapper("tema",     node_tema,     tema_stage.LE))
    g.add_node("research", com_wrapper("research", node_research, research_stage.LE))
    g.add_node("plan",     com_wrapper("plan",     node_plan,     plan_stage.LE))
    g.add_node("write",    com_wrapper("write",    node_write,    write_stage.LE),
               destinations=("research", "review"))
    g.add_node("review",   com_wrapper("review",   node_review,   review_stage.LE))

    g.set_entry_point(inicio)
    g.add_edge("tema", "research")
    g.add_edge("research", "plan")
    g.add_edge("plan", "write")
    g.add_conditional_edges(
        "review",
        lambda s: rotear(s, settings.max_review_rounds, settings.max_passos),
        {"write": "write", "research": "research", END: END},
    )
    logger.info("Graph compiled successfully")
    return g.compile()
