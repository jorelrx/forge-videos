from langgraph.graph import END
from forge.infrastructure.config import Settings
from forge.orchestration.graph import rotear, build_graph
from forge.domain.models import (
    ReviewResult, Nota, Plano, RoteiroDraft, Secao, FonteList, Fonte,
)

# --- rotear (puro) ---

def test_rotear_orcamento_vence_verificar():
    """Orçamento estourado encerra mesmo com verificação pendente."""
    state = {
        "review": ReviewResult(aprovado=False, verificar=["aspa de Nietzsche"]),
        "rounds": 0,
        "passos": 20,
    }
    assert rotear(state, max_rounds=8, max_passos=20) == END

def test_rotear_orcamento_vence_reprovacao():
    """Orçamento estourado encerra mesmo com review reprovado e rounds baixo."""
    state = {"review": ReviewResult(aprovado=False), "rounds": 0, "passos": 25}
    assert rotear(state, max_rounds=8, max_passos=20) == END

def test_rotear_verificar_vai_para_research():
    state = {
        "review": ReviewResult(aprovado=False, verificar=["aspa"]),
        "rounds": 1,
        "passos": 3,
    }
    assert rotear(state, max_rounds=8, max_passos=20) == "research"

def test_rotear_aprovado_encerra():
    state = {"review": ReviewResult(aprovado=True), "rounds": 1, "passos": 3}
    assert rotear(state, max_rounds=8, max_passos=20) == END

def test_rotear_verificar_vence_aprovado():
    """Aprovado com verificação pendente ainda vai para research.

    Guarda a ordem das condições: se `aprovado` fosse checado antes de
    `verificar`, uma aspa não confirmada passaria direto para o roteiro final.
    """
    state = {
        "review": ReviewResult(aprovado=True, verificar=["aspa de Nietzsche"]),
        "rounds": 1,
        "passos": 3,
    }
    assert rotear(state, max_rounds=8, max_passos=20) == "research"

def test_rotear_reprovado_volta_para_write():
    state = {"review": ReviewResult(aprovado=False), "rounds": 1, "passos": 3}
    assert rotear(state, max_rounds=8, max_passos=20) == "write"

# --- grafo completo com model roteirizado ---

def _draft():
    return RoteiroDraft(secoes=[Secao(nome="Hook", conteudo="c")])

def test_grafo_aprova_apos_uma_reprovacao(scripted, tmp_path):
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
    final = graph.invoke({"tema": None, "rounds": 0, "run_dir": tmp_path, "passos": 0})
    assert final["review"].aprovado is True
    assert final["rounds"] == 2
    assert final["roteiro"].secoes[0].nome == "Hook"

def test_grafo_para_no_teto(scripted, tmp_path):
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
    final = graph.invoke({"tema": None, "rounds": 0, "run_dir": tmp_path, "passos": 0})
    assert final["rounds"] == 2
    assert final["review"].aprovado is False

def test_grafo_termina_com_modelo_patologico(scripted, tmp_path):
    """Model que sempre pede verificação não pode rodar para sempre.

    O handoff `review -> research` faz `node_research` rodar de novo a cada
    volta, e cada passagem por `research` consome um `FonteList` do queue
    estruturado (via `_extrair_fontes`), não só a primeira. Um queue com
    `FonteList`/`Plano` só no início dessincroniza a partir da segunda volta
    — o item errado (um `RoteiroDraft`) cai em `_extrair_fontes`, que engole
    o `AttributeError` e cai para parsing de JSON (consumindo mais um
    `invoke_texts`), e o próximo `plan` recebe um `ReviewResult` no lugar de
    um `Plano`, estourando com `AttributeError: 'ReviewResult' object has no
    attribute 'tese'` — não o orçamento. Por isso cada ciclo abaixo repete
    `FonteList, Plano, Draft, Review` inteiro, igual ao que `node_research`
    de fato consome em cada volta.
    """
    n_ciclos = 40  # bem mais que o necessário para estourar max_passos=12
    estruturados = []
    for _ in range(n_ciclos):
        estruturados += [
            FonteList(),
            Plano(tese="t", esboco="e"),
            _draft(),
            ReviewResult(aprovado=False, verificar=["x"]),
        ]
    model = scripted(
        invoke_texts=["tema"] + ["notas"] * n_ciclos,
        structured=estruturados,
    )
    settings = Settings(_env_file=None, max_review_rounds=99, max_passos=12)
    graph = build_graph(model, settings)
    final = graph.invoke({
        "tema": None, "rounds": 0, "passos": 0, "run_dir": tmp_path,
    })
    assert final["passos"] <= 13, f"orçamento furou: {final['passos']} passos"
