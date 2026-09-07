from pathlib import Path

import pytest
from langgraph.graph import END
from forge.infrastructure.config import Settings
from forge.orchestration.graph import rotear, build_graph
from forge.domain.models import (
    ReviewResult, Nota, Plano, RoteiroDraft, Secao,
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

def _passagem():
    from forge.services.acervo import Passagem

    return Passagem(
        path="4363/ch2/p7", book_id=4363, book_title="Obra",
        authors=["Autor"], breadcrumb="Cap 2", text="trecho",
        url="http://acervo.test/books/4363", score=0.9,
    )

@pytest.fixture
def grafo_com_acervo(monkeypatch, acervo_fake):
    """Troca o cliente real do grafo por um falso que sempre acha uma passagem.

    `build_graph` constrói o `Acervo` a partir de `Settings`; sem esta troca o
    teste tentaria falar com 127.0.0.1:8000.
    """
    import forge.orchestration.graph as graph_mod

    fake = acervo_fake(padrao=[_passagem()])
    monkeypatch.setattr(graph_mod, "Acervo", lambda *a, **k: fake)
    return fake

def test_grafo_aprova_apos_uma_reprovacao(scripted, tmp_path, grafo_com_acervo):
    # invoke_texts: tema, queries(research), brief(research)
    # structured:   plano, draft(v1), review(reprovado), draft(v2), review(aprovado)
    model = scripted(
        invoke_texts=["tema gerado", "busca sobre o tema", "notas de pesquisa"],
        structured=[
            Plano(tese="tese", esboco="esboço"),
            _draft(),
            ReviewResult(aprovado=False, notas=[Nota(dimensao="clareza", problema="p", sugestao="s")]),
            _draft(),
            ReviewResult(aprovado=True),
        ],
    )
    settings = Settings(_env_file=None, max_review_rounds=8, juiz_relevancia=False)
    graph = build_graph(model, settings)
    final = graph.invoke({"tema": None, "rounds": 0, "run_dir": tmp_path, "passos": 0})
    assert final["review"].aprovado is True
    assert final["rounds"] == 2
    assert final["roteiro"].secoes[0].nome == "Hook"
    assert final["fontes"][0].path == "4363/ch2/p7"

def test_grafo_para_no_teto(scripted, tmp_path, grafo_com_acervo):
    model = scripted(
        invoke_texts=["tema", "busca", "notas"],
        structured=[
            Plano(tese="t", esboco="e"),
            _draft(), ReviewResult(aprovado=False),
            _draft(), ReviewResult(aprovado=False),
        ],
    )
    settings = Settings(_env_file=None, max_review_rounds=2, juiz_relevancia=False)
    graph = build_graph(model, settings)
    final = graph.invoke({"tema": None, "rounds": 0, "run_dir": tmp_path, "passos": 0})
    assert final["rounds"] == 2
    assert final["review"].aprovado is False

def test_grafo_termina_com_modelo_patologico(scripted, tmp_path, grafo_com_acervo):
    """Model que sempre pede verificação não pode rodar para sempre.

    O handoff `review -> research` faz `node_research` rodar a cada volta, e
    cada volta consome dois `invoke_texts` (queries e brief) mais um `Plano`,
    um `RoteiroDraft` e um `ReviewResult` da fila estruturada. As filas abaixo
    repetem esse ciclo muito além do necessário: quem tem de encerrar o grafo é
    `max_passos`, não uma fila esgotada.

    `verificar` precisa de uma alegação de verdade (frase afirmativa, 3+
    palavras, sem "?") para sobreviver a `alegacoes_reais` — um placeholder
    como "x" seria descartado pelo filtro e o modelo pararia de forçar o
    handoff para research, o que descaracterizaria o teste.
    """
    n_ciclos = 40  # bem mais que o necessário para estourar max_passos=12
    textos = ["tema"]
    estruturados = []
    for _ in range(n_ciclos):
        textos += ["busca", "notas"]
        estruturados += [
            Plano(tese="t", esboco="e"),
            _draft(),
            ReviewResult(aprovado=False, verificar=["Confirmar a data citada no texto."]),
        ]

    model = scripted(invoke_texts=textos, structured=estruturados)
    settings = Settings(_env_file=None, max_review_rounds=100, max_passos=12, juiz_relevancia=False)
    graph = build_graph(model, settings)

    final = graph.invoke({"tema": None, "rounds": 0, "run_dir": tmp_path, "passos": 0})

    assert 12 <= final["passos"] <= 13, f"orçamento furou: {final['passos']} passos"

def test_research_nao_chama_a_camada_de_conhecimento():
    """Retriever fica dormente até K5: nada no fluxo de roteiro pode tocá-lo."""
    import forge.orchestration.graph as modulo

    fonte = Path(modulo.__file__).read_text(encoding="utf-8")
    assert "knowledge" not in fonte
    assert "consultar_e_aprender" not in fonte
