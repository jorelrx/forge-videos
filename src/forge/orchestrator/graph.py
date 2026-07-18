from langgraph.graph import END, StateGraph

from forge.orchestrator.state import RoteiroState
from forge.writer import plan as plan_stage
from forge.writer import research as research_stage
from forge.writer import review as review_stage
from forge.writer import tema as tema_stage
from forge.writer import write as write_stage


def should_continue(state: dict, max_rounds: int) -> str:
    review = state.get("review")
    if review is not None and review.aprovado:
        return END
    if state.get("rounds", 0) >= max_rounds:
        return END
    return "write"


def build_graph(model, settings):
    def node_tema(state):
        return {"tema": tema_stage.gerar_tema(model, state.get("tema"))}

    def node_research(state):
        notes, fontes = research_stage.pesquisar(model, state["tema"])
        return {"research_notes": notes, "fontes": fontes}

    def node_plan(state):
        tese, esboco = plan_stage.planejar(model, state["tema"], state["research_notes"])
        return {"tese": tese, "esboco": esboco}

    def node_write(state):
        review = state.get("review")
        notas = review.notas if review is not None else None
        roteiro = write_stage.escrever(
            model,
            state["tema"],
            state["tese"],
            state["esboco"],
            state["research_notes"],
            state["fontes"],
            notas,
        )
        return {"roteiro": roteiro}

    def node_review(state):
        result = review_stage.revisar(model, state["roteiro"])
        return {"review": result, "rounds": state.get("rounds", 0) + 1}

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
    return g.compile()
