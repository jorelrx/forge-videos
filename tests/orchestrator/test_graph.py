from langgraph.graph import END
from forge.config import Settings
from forge.orchestrator.graph import should_continue, build_graph
from forge.writer.models import (
    ReviewResult, Nota, Plano, RoteiroDraft, Secao, FonteList, Fonte,
)

# --- should_continue (puro) ---

def test_should_continue_aprovado():
    state = {"review": ReviewResult(aprovado=True), "rounds": 1}
    assert should_continue(state, max_rounds=8) == END

def test_should_continue_reprovado_volta_para_write():
    state = {"review": ReviewResult(aprovado=False, notas=[]), "rounds": 1}
    assert should_continue(state, max_rounds=8) == "write"

def test_should_continue_bate_teto():
    state = {"review": ReviewResult(aprovado=False), "rounds": 8}
    assert should_continue(state, max_rounds=8) == END

# --- grafo completo com model roteirizado ---

def _draft():
    return RoteiroDraft(secoes=[Secao(nome="Hook", conteudo="c")])

def test_grafo_aprova_apos_uma_reprovacao(scripted):
    # sequência de structured: fontes, plano, draft(v1), review(reprovado),
    #                          draft(v2), review(aprovado)
    model = scripted(
        invoke_texts=["tema gerado", "notas de pesquisa"],
        structured=[
            FonteList(fontes=[Fonte(titulo="Obra", autor="Autor")]),
            Plano(tese="tese", esboco="esboço"),
            _draft(),
            ReviewResult(aprovado=False, notas=[Nota(dimensao="clareza", problema="p", sugestao="s")]),
            _draft(),
            ReviewResult(aprovado=True),
        ],
    )
    settings = Settings(_env_file=None, max_review_rounds=8)
    graph = build_graph(model, settings)
    final = graph.invoke({"tema": None, "rounds": 0})
    assert final["review"].aprovado is True
    assert final["rounds"] == 2
    assert final["roteiro"].secoes[0].nome == "Hook"

def test_grafo_para_no_teto(scripted):
    model = scripted(
        invoke_texts=["tema", "notas"],
        structured=[
            FonteList(),
            Plano(tese="t", esboco="e"),
            _draft(), ReviewResult(aprovado=False),
            _draft(), ReviewResult(aprovado=False),
        ],
    )
    settings = Settings(_env_file=None, max_review_rounds=2)
    graph = build_graph(model, settings)
    final = graph.invoke({"tema": None, "rounds": 0})
    assert final["rounds"] == 2
    assert final["review"].aprovado is False
