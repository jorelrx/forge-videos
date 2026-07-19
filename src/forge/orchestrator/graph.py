from langgraph.graph import END, StateGraph

from forge.logging import get_logger

logger = get_logger(__name__)

from forge.orchestrator.state import RoteiroState
from forge.writer import plan as plan_stage
from forge.writer import research as research_stage
from forge.writer import review as review_stage
from forge.writer import tema as tema_stage
from forge.writer import write as write_stage


def should_continue(state: dict, max_rounds: int) -> str:
    review = state.get("review")
    rounds = state.get("rounds", 0)
    if review is not None and review.aprovado:
        logger.info("Review approved - stopping", round=rounds, aprovados=review.aprovado)
        return END
    if rounds >= max_rounds:
        logger.warning("Max review rounds reached", round=rounds, max=max_rounds)
        return END
    logger.debug("Continuing to write phase", round=rounds)
    return "write"


def build_graph(model, settings):
    logger.info("Building graph", stages=["tema", "research", "plan", "write", "review"])

    def node_tema(state):
        logger.debug("Running tema generation", tema=state.get("tema"))
        result = {"tema": tema_stage.gerar_tema(model, state.get("tema"))}
        logger.info("Tema generated", tema=result["tema"])
        return result

    def node_research(state):
        logger.debug("Starting research phase", tema=state["tema"])
        notes, fontes = research_stage.pesquisar(model, state["tema"], settings.provider)
        result = {"research_notes": notes, "fontes": fontes}
        logger.info("Research completed", num_fontes=len(fontes))
        return result

    def node_plan(state):
        logger.debug("Starting planning phase")
        tese, esboco = plan_stage.planejar(model, state["tema"], state["research_notes"])
        result = {"tese": tese, "esboco": esboco}
        logger.info("Planning completed", tese=tese[:100] + "..." if len(tese) > 100 else tese)
        return result

    def node_write(state):
        review = state.get("review")
        notas = review.notas if review is not None else None
        logger.debug("Starting write phase", tema=state["tema"])
        roteiro = write_stage.escrever(
            model,
            state["tema"],
            state["tese"],
            state["esboco"],
            state["research_notes"],
            state["fontes"],
            notas,
        )
        result = {"roteiro": roteiro}
        logger.debug("Write phase completed", secoes_count=len(roteiro.secoes))
        return result

    def node_review(state):
        logger.debug("Starting review phase")
        result = review_stage.revisar(model, state["roteiro"])
        new_result = {"review": result, "rounds": state.get("rounds", 0) + 1}
        logger.info("Review completed", aprovado=result.aprovado, round=new_result["rounds"])
        return new_result

    g = StateGraph(RoteiroState)
    g.add_node("tema", node_tema)
    g.add_node("research", node_research)
    g.add_node("plan", node_plan)
    g.add_node("write", node_write)
    g.add_node("review", node_review)

    g.set_entry_point("tema")
    g.add_edge("tema", "research")
    g.add_edge("research", "plan")
    g.add_edge("plan", "write")
    g.add_edge("write", "review")
    g.add_conditional_edges(
        "review",
        lambda s: should_continue(s, settings.max_review_rounds),
        {"write": "write", END: END},
    )
    logger.info("Graph compiled successfully")
    return g.compile()
