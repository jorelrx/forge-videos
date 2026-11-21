from pathlib import Path

import pytest
from langgraph.graph import END
from forge.agents import plan, review, write
from forge.domain.fluxo_geracao import FLUXOS_INICIAIS
from forge.infrastructure.config import Settings
from forge.llms.model import invoke_structured
from forge.orchestration.graph import rotear, build_graph
from forge.domain.models import (
    BlocoRoteiro, ReviewResult, Nota, Plano, SecaoDraft,
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

CAMINHO = "4363/ch2/p7"


def _pedindo_pesquisa(pedido):
    """Rascunho do Gancho em que o escritor declara que falta material."""
    return SecaoDraft(
        conteudo="Gancho fala.", blocos=[BlocoRoteiro(texto="Gancho fala.")],
        falta_pesquisa=pedido,
    )

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

def test_grafo_aprova_apos_uma_reprovacao(scripted, tmp_path, grafo_com_acervo, secoes_draft):
    # invoke_texts: queries(research), brief(research)
    # structured:   plano, nove seções (v1), review(reprovado na Prova),
    #               só a Prova (v2), review(aprovado)
    prova_v2 = SecaoDraft(
        conteudo="Prova refeita.",
        blocos=[BlocoRoteiro(texto="Prova refeita.", referencias=[CAMINHO])],
    )
    model = scripted(
        invoke_texts=["busca sobre o tema", "notas de pesquisa"],
        structured=[
            Plano(tese="tese", esboco="esboço", eixo="niilismo-absurdo"),
            *secoes_draft(referencia=CAMINHO),
            ReviewResult(aprovado=False, notas=[
                Nota(dimensao="clareza", problema="p", sugestao="s", secao="Prova"),
            ]),
            prova_v2,
            ReviewResult(aprovado=True),
        ],
    )
    settings = Settings(_env_file=None, max_review_rounds=8, juiz_relevancia=False)
    graph = build_graph(model, settings)
    final = graph.invoke({"tema": "tema dado", "rounds": 0, "run_dir": tmp_path, "passos": 0})
    assert final["review"].aprovado is True
    assert final["rounds"] == 2
    assert final["roteiro"].secoes[0].nome == "Gancho"
    assert final["roteiro"].secoes[0].conteudo == "Gancho fala."
    assert final["roteiro"].secoes[5].conteudo == "Prova refeita."
    assert final["eixo"] == "niilismo-absurdo"
    assert final["fontes"][0].path == "4363/ch2/p7"
    assert model.structured == []


@pytest.mark.parametrize("fluxo", [None, *FLUXOS_INICIAIS])
def test_grafo_envia_o_fluxo_ao_plano_escrita_e_revisao(
    scripted, tmp_path, grafo_com_acervo, secoes_draft, monkeypatch, fluxo,
):
    prompts = {}

    def capturar(model, schema, messages, *, etapa, **kwargs):
        prompts.setdefault(etapa, []).append(messages[0].content)
        return invoke_structured(model, schema, messages, etapa=etapa, **kwargs)

    for modulo in (plan, write, review):
        monkeypatch.setattr(modulo, "invoke_structured", capturar)

    escritor = scripted(
        invoke_texts=["busca sobre o tema", "notas de pesquisa"],
        structured=[Plano(tese="tese", esboco="esboço"), *secoes_draft(referencia=CAMINHO)],
    )
    revisor = scripted(structured=[ReviewResult(aprovado=True)])
    settings = Settings(_env_file=None, juiz_relevancia=False)
    graph = build_graph(escritor, settings, revisor=revisor, fluxo_geracao=fluxo)
    final = graph.invoke({"tema": "tema dado", "rounds": 0, "run_dir": tmp_path, "passos": 0})
    assert final["review"].aprovado is True
    assert escritor.structured == []
    assert revisor.structured == []
    assert {etapa: len(items) for etapa, items in prompts.items()} == {
        "plan": 1, "write": 9, "review": 1,
    }
    for items in prompts.values():
        for prompt in items:
            if fluxo and fluxo.instrucoes:
                assert fluxo.instrucoes in prompt
            else:
                assert "## Fluxo de geração" not in prompt


def test_grafo_handoff_de_write_vai_so_para_research(scripted, tmp_path, grafo_com_acervo, secoes_draft):
    """Pedido de pesquisa do escritor não pode executar review em paralelo."""
    model = scripted(
        invoke_texts=["busca", "notas", "busca dirigida", "notas dirigidas"],
        structured=[
            Plano(tese="t1", esboco="e1"),
            *secoes_draft(referencia=CAMINHO, Gancho=_pedindo_pesquisa("Confirmar a afirmação.")),
            Plano(tese="t2", esboco="e2"),
            *secoes_draft(referencia=CAMINHO),
            ReviewResult(aprovado=True),
        ],
    )
    settings = Settings(_env_file=None, juiz_relevancia=False)
    graph = build_graph(model, settings)

    final = graph.invoke({"tema": "tema dado", "rounds": 0, "run_dir": tmp_path, "passos": 0})

    assert final["review"].aprovado is True

def test_grafo_para_no_teto(scripted, tmp_path, grafo_com_acervo, secoes_draft):
    model = scripted(
        invoke_texts=["busca", "notas"],
        structured=[
            Plano(tese="t", esboco="e"),
            *secoes_draft(referencia=CAMINHO), ReviewResult(aprovado=False),
            *secoes_draft(referencia=CAMINHO), ReviewResult(aprovado=False),
        ],
    )
    settings = Settings(_env_file=None, max_review_rounds=2, juiz_relevancia=False)
    graph = build_graph(model, settings)
    final = graph.invoke({"tema": "tema dado", "rounds": 0, "run_dir": tmp_path, "passos": 0})
    assert final["rounds"] == 2
    assert final["review"].aprovado is False

def test_grafo_termina_com_modelo_patologico(scripted, tmp_path, grafo_com_acervo, secoes_draft):
    """Model que sempre pede verificação não pode rodar para sempre.

    O handoff `review -> research` faz `node_research` rodar a cada volta, e
    cada volta consome dois `invoke_texts` (queries e brief) mais um `Plano`,
    nove `SecaoDraft` e um `ReviewResult` da fila estruturada. As filas abaixo
    repetem esse ciclo muito além do necessário: quem tem de encerrar o grafo é
    `max_passos`, não uma fila esgotada.

    `verificar` precisa de uma alegação de verdade (frase afirmativa, 3+
    palavras, sem "?") para sobreviver a `alegacoes_reais` — um placeholder
    como "x" seria descartado pelo filtro e o modelo pararia de forçar o
    handoff para research, o que descaracterizaria o teste.
    """
    n_ciclos = 40  # bem mais que o necessário para estourar max_passos=12
    textos = []
    estruturados = []
    for _ in range(n_ciclos):
        textos += ["busca", "notas"]
        estruturados += [
            Plano(tese="t", esboco="e"),
            *secoes_draft(referencia=CAMINHO),
            ReviewResult(aprovado=False, verificar=["Confirmar a data citada no texto."]),
        ]

    model = scripted(invoke_texts=textos, structured=estruturados)
    settings = Settings(_env_file=None, max_review_rounds=100, max_passos=12, juiz_relevancia=False)
    graph = build_graph(model, settings)

    final = graph.invoke({"tema": "tema dado", "rounds": 0, "run_dir": tmp_path, "passos": 0})

    assert 12 <= final["passos"] <= 13, f"orçamento furou: {final['passos']} passos"

def test_orcamento_encerra_handoff_de_write(scripted, tmp_path, grafo_com_acervo, secoes_draft):
    """Modelo que só sabe pedir pesquisa não pode furar o teto de passos.

    O caminho `write -> research` (`falta_pesquisa`) não passa por `rotear` —
    que era o único lugar onde `max_passos` era conferido. Com o pedido sempre
    presente, o grafo seguia rodando depois do orçamento estourado, até o prazo
    do subprocesso da etapa.

    Sequência exata com max_passos=6: tema(1) research(2) plan(3) write(4, pedido
    aceito) research(5) plan(6) write(7, pedido ignorado -> review) review(8);
    o roteador então encerra em 8 >= 6. As filas extras existem para o
    comportamento antigo falhar alto (fila esgotada) em vez de passar.
    """
    n_ciclos = 2
    estruturados = []
    for _ in range(n_ciclos):
        estruturados += [
            Plano(tese="t", esboco="e"),
            *secoes_draft(
                referencia=CAMINHO,
                Gancho=_pedindo_pesquisa("Confirmar a afirmação citada no texto."),
            ),
        ]
    estruturados += [ReviewResult(aprovado=False)]
    for _ in range(5):  # o modelo patológico nunca pararia de pedir pesquisa
        estruturados += [
            Plano(tese="t", esboco="e"),
            *secoes_draft(
                referencia=CAMINHO,
                Gancho=_pedindo_pesquisa("Confirmar a afirmação citada no texto."),
            ),
        ]

    model = scripted(
        invoke_texts=["busca", "notas"] * 12,
        structured=estruturados,
    )
    settings = Settings(
        _env_file=None, max_review_rounds=100, max_passos=6, juiz_relevancia=False
    )
    graph = build_graph(model, settings)

    final = graph.invoke({"tema": "tema dado", "rounds": 0, "run_dir": tmp_path, "passos": 0})

    assert final["passos"] >= 6, f"encerrou antes do orçamento: {final['passos']}"
    assert final["passos"] <= 12, f"orçamento furou: {final['passos']} passos"


def test_grafo_sem_tema_usa_o_seletor(scripted, tmp_path, grafo_com_acervo, secoes_draft):
    """Sem tema informado, o grafo pergunta ao acervo o que ele sustenta."""
    from forge.agents.tema import TemaCandidato, TemasPropostos, VeredictoTema, VeredictoTemas
    from forge.services.acervo import Passagem

    grafo_com_acervo.por_query["busca do candidato"] = [
        Passagem(path=f"4363/ch2/p{n}", book_id=4363, book_title="Obra",
                 authors=["Autor"], text=f"trecho {n}")
        for n in range(7, 10)
    ]
    model = scripted(
        invoke_texts=["busca", "notas"],
        structured=[
            TemasPropostos(candidatos=[TemaCandidato(
                tema="Tema do seletor", eixo="niilismo-absurdo", dor="d", promessa="p",
                buscas=["busca do candidato"],
            )]),
            VeredictoTemas(veredictos=[
                VeredictoTema(indice=0, sustentado=True, apelo=4, motivo="m"),
            ]),
            Plano(tese="t", esboco="e"),
            *secoes_draft(referencia=CAMINHO),
            ReviewResult(aprovado=True),
        ],
    )
    settings = Settings(
        _env_file=None, juiz_relevancia=False, output_dir=tmp_path / "roteiros",
        studio_runs_dir=tmp_path / "studio",
    )
    graph = build_graph(model, settings)

    final = graph.invoke({"tema": None, "rounds": 0, "run_dir": tmp_path, "passos": 0})

    assert final["tema"] == "Tema do seletor"
    assert final["review"].aprovado is True


def test_research_nao_chama_a_camada_de_conhecimento():
    """Retriever fica dormente até K5: nada no fluxo de roteiro pode tocá-lo."""
    import forge.orchestration.graph as modulo

    fonte = Path(modulo.__file__).read_text(encoding="utf-8")
    assert "knowledge" not in fonte
    assert "consultar_e_aprender" not in fonte
