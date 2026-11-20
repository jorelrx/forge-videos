"""Escrita por seção: uma chamada de modelo para cada uma das nove partes.

Uma chamada única para ~2.000 palavras encurtava o texto e errava a conferência
palavra por palavra entre `conteudo` e `blocos`. Por seção, cada chamada tem o
seu alvo e a revisão pode mexer só no que o revisor apontou.
"""
import pytest

from forge.agents.research import PassageEvidence
from forge.agents.write import escrever
from forge.domain.models import BlocoRoteiro, CitacaoLiteral, Fonte, Nota, SecaoDraft
from forge.domain.roteiro import SECOES_NOMES


def _rascunho(texto, referencias=(), citacoes=(), falta=None):
    return SecaoDraft(
        conteudo=texto,
        blocos=[BlocoRoteiro(
            texto=texto, referencias=list(referencias), citacoes_literais=list(citacoes),
        )],
        falta_pesquisa=falta,
    )


def test_escrever_faz_uma_chamada_por_secao(scripted, secoes_draft):
    model = scripted(structured=secoes_draft())
    fontes = [Fonte(titulo="Obra", autor="Autor")]

    roteiro, falta = escrever(model, "tema", "tese", "esboço", "notas", fontes)

    assert [s.nome for s in roteiro.secoes] == SECOES_NOMES
    assert model.structured == []
    assert roteiro.tema == "tema" and roteiro.tese == "tese"
    assert roteiro.fontes == fontes
    assert falta is None


def test_prompt_da_secao_traz_alvo_papel_e_secoes_anteriores(monkeypatch, secoes_draft):
    from forge.agents import write

    prompts = {}
    fila = secoes_draft()

    def invoke(model, schema, messages, *, subfase, **kwargs):
        prompts[subfase] = messages[0].content
        return fila.pop(0)

    monkeypatch.setattr(write, "invoke_structured", invoke)
    escrever(object(), "tema", "tese", "esboço", "notas", [])

    assert list(prompts) == SECOES_NOMES
    assert "260" in prompts["Filosofo"] and "380" in prompts["Filosofo"]
    assert "ideia encarnada" in prompts["Filosofo"]
    # Cada seção enxerga o que já foi escrito, para não repetir abertura.
    assert "Gancho fala." in prompts["Estake"]
    assert "Estake fala." not in prompts["Estake"]


def test_prompt_da_secao_recebe_a_referencia_do_eixo(monkeypatch, secoes_draft):
    from forge.agents import write

    prompts = []
    fila = secoes_draft()

    def invoke(model, schema, messages, **kwargs):
        prompts.append(messages[0].content)
        return fila.pop(0)

    monkeypatch.setattr(write, "invoke_structured", invoke)
    escrever(object(), "tema", "tese", "esboço", "notas", [], eixo="estoicismo")

    assert all("Will Durant" in prompt for prompt in prompts)


def test_revisao_reescreve_so_a_secao_citada(scripted, roteiro_longo):
    anterior = roteiro_longo()
    model = scripted(structured=[_rascunho("Prova refeita.")])
    notas = [Nota(dimensao="retention", problema="p", sugestao="s", secao="Prova")]

    roteiro, _ = escrever(model, "Tema", "Tese", "e", "n", [], notas, anterior=anterior)

    novas = {s.nome: s for s in roteiro.secoes}
    antigas = {s.nome: s for s in anterior.secoes}
    assert model.structured == []
    assert novas["Prova"].conteudo == "Prova refeita."
    assert all(novas[nome] == antigas[nome] for nome in SECOES_NOMES if nome != "Prova")


def test_revisao_mostra_o_texto_anterior_e_a_nota_da_secao(monkeypatch, roteiro_longo):
    from forge.agents import write

    prompts = []

    def invoke(model, schema, messages, **kwargs):
        prompts.append(messages[0].content)
        return _rascunho("Prova refeita.")

    monkeypatch.setattr(write, "invoke_structured", invoke)
    anterior = roteiro_longo()
    notas = [
        Nota(dimensao="retention", problema="bloco abstrato", sugestao="dar exemplo", secao="Prova"),
    ]
    escrever(object(), "Tema", "Tese", "e", "n", [], notas, anterior=anterior)

    prova = next(s for s in anterior.secoes if s.nome == "Prova")
    assert len(prompts) == 1
    assert prova.conteudo in prompts[0]
    assert "bloco abstrato" in prompts[0] and "dar exemplo" in prompts[0]


def test_nota_com_secao_acentuada_e_canonizada(scripted, roteiro_longo):
    """O revisor escreve português correto; o contrato é sem acento."""
    model = scripted(structured=[_rascunho("Tensão refeita.")])
    notas = [Nota(dimensao="story", problema="p", sugestao="s", secao=" tensão ")]

    roteiro, _ = escrever(model, "Tema", "Tese", "e", "n", [], notas, anterior=roteiro_longo())

    assert model.structured == []
    assert {s.nome: s for s in roteiro.secoes}["Tensao"].conteudo == "Tensão refeita."


@pytest.mark.parametrize("secao", [None, "Introdução", ""])
def test_nota_sem_secao_valida_reescreve_tudo(scripted, roteiro_longo, secoes_draft, secao):
    """Nota que não aponta uma das nove seções nunca é descartada em silêncio."""
    model = scripted(structured=secoes_draft())
    notas = [Nota(dimensao="clareza", problema="p", sugestao="s", secao=secao)]

    roteiro, _ = escrever(model, "Tema", "Tese", "e", "n", [], notas, anterior=roteiro_longo())

    assert model.structured == []
    assert roteiro.secoes[0].conteudo == "Gancho fala."


def test_notas_sem_roteiro_anterior_escrevem_tudo(scripted, secoes_draft):
    model = scripted(structured=secoes_draft())
    notas = [Nota(dimensao="clareza", problema="p", sugestao="s", secao="Prova")]

    roteiro, _ = escrever(model, "t", "te", "e", "n", [], notas)

    assert model.structured == [] and len(roteiro.secoes) == 9


def test_tese_nova_invalida_a_revisao_dirigida(scripted, roteiro_longo, secoes_draft):
    """Depois de nova pesquisa o plano é refeito: seções antigas defendem outra tese."""
    model = scripted(structured=secoes_draft())
    notas = [Nota(dimensao="clareza", problema="p", sugestao="s", secao="Prova")]

    roteiro, _ = escrever(
        model, "Tema", "Tese refeita", "e", "n", [], notas, anterior=roteiro_longo(),
    )

    assert model.structured == []
    assert roteiro.tese == "Tese refeita"


def test_falta_pesquisa_devolve_roteiro_completo_e_o_primeiro_pedido(scripted, secoes_draft):
    drafts = secoes_draft(
        Tensao=_rascunho("Tensao fala.", falta="Confirmar X."),
        Prova=_rascunho("Prova fala.", falta="Confirmar Y."),
    )

    roteiro, falta = escrever(scripted(structured=drafts), "t", "te", "e", "n", [])

    assert len(roteiro.secoes) == 9
    assert falta == "Confirmar X."


def test_secao_so_com_blocos_tem_o_conteudo_reconstruido(scripted, secoes_draft):
    """Alguns modelos entregam a narração nos blocos e deixam `conteudo` vazio."""
    draft = SecaoDraft(conteudo="", blocos=[
        BlocoRoteiro(texto="Primeira frase."), BlocoRoteiro(texto="Segunda frase."),
    ])

    roteiro, _ = escrever(scripted(structured=secoes_draft(Gancho=draft)), "t", "te", "e", "n", [])

    assert roteiro.secoes[0].conteudo == "Primeira frase. Segunda frase."


def test_secao_vazia_e_recusada(scripted, secoes_draft):
    drafts = secoes_draft(Estake=SecaoDraft(conteudo=" ", blocos=[]))

    with pytest.raises(ValueError, match="Estake"):
        escrever(scripted(structured=drafts), "t", "te", "e", "n", [])


def test_escrever_rejeita_referencia_inventada(scripted, secoes_draft):
    passage = PassageEvidence(path="real/ch1/p1", title="Obra", text="trecho")
    drafts = secoes_draft(Gancho=_rascunho("Uma frase.", referencias=["inventado/path"]))

    with pytest.raises(ValueError, match="sem passagem do acervo"):
        escrever(scripted(structured=drafts), "t", "te", "e", "n", [], research_passages=[passage])


def test_secao_factual_sem_referencia_e_recusada(scripted, secoes_draft):
    passage = PassageEvidence(path="real/ch1/p1", title="Obra", text="trecho")
    drafts = secoes_draft(referencia=passage.path, Prova=_rascunho("Prova sem fonte."))

    with pytest.raises(ValueError, match="sem referências do acervo: Prova"):
        escrever(scripted(structured=drafts), "t", "te", "e", "n", [], research_passages=[passage])


def test_escrever_confere_citacao_literal_no_acervo_e_na_fala(scripted, secoes_draft):
    passage = PassageEvidence(path="real/ch1/p1", title="Obra", text="A liberdade exige escolha.")
    citacao = CitacaoLiteral(path=passage.path, trecho="A liberdade exige escolha.")
    bom = _rascunho("A liberdade exige escolha.", [passage.path], [citacao])

    roteiro, _ = escrever(
        scripted(structured=secoes_draft(referencia=passage.path, Estake=bom)),
        "t", "te", "e", "n", [], research_passages=[passage],
    )
    assert roteiro.secoes[1].blocos[0].referencias == [passage.path]

    ruim = _rascunho(
        "A liberdade exige escolha.", [passage.path],
        [CitacaoLiteral(path=passage.path, trecho="inventado")],
    )
    with pytest.raises(ValueError, match="não confere"):
        escrever(
            scripted(structured=secoes_draft(referencia=passage.path, Estake=ruim)),
            "t", "te", "e", "n", [], research_passages=[passage],
        )


def test_escrever_rejeita_divergencia_entre_secao_e_blocos(scripted, secoes_draft):
    draft = SecaoDraft(
        conteudo="Texto principal.", blocos=[BlocoRoteiro(texto="Texto diferente.")],
    )
    passage = PassageEvidence(path="1/ch1/p1", title="Obra", text="evidência")

    with pytest.raises(ValueError, match="não reproduzem"):
        escrever(
            scripted(structured=secoes_draft(Gancho=draft)),
            "t", "te", "e", "n", [], research_passages=[passage],
        )


def test_canonizar_nome_aceita_acento_caixa_e_desconhecido():
    from forge.domain.roteiro import canonizar_nome

    assert canonizar_nome("Tensão") == "Tensao"
    assert canonizar_nome("Aplicação") == "Aplicacao"
    assert canonizar_nome("  filósofo ") == "Filosofo"
    assert canonizar_nome("FECHO") == "Fecho"
    # Nome fora do contrato não é inventado nem descartado.
    assert canonizar_nome("Hook") == "Hook"


def test_write_le_o_roteiro_anterior_e_o_eixo():
    from forge.agents import write

    assert {"roteiro", "eixo", "review"} <= set(write.LE)


# --- citação traduzida: o acervo é em inglês e alemão, a narração em português ---

_ORIGINAL = PassageEvidence(
    path="1998/150.f1", title="Thus Spake Zarathustra", authors=["Nietzsche"],
    text="All delight longs for repetitions, and the child cries again.",
)


def _traduzido(trecho, traducao, fala=None):
    fala = fala or f'Nietzsche escreve, em tradução livre: "{traducao}".'
    return _rascunho(fala, [_ORIGINAL.path], [
        CitacaoLiteral(path=_ORIGINAL.path, trecho=trecho, traducao=traducao),
    ])


def _escrever_estake(scripted, secoes_draft, rascunho):
    return escrever(
        scripted(structured=secoes_draft(referencia=_ORIGINAL.path, Estake=rascunho)),
        "t", "te", "e", "n", [], research_passages=[_ORIGINAL],
    )


def test_traducao_confere_original_na_passagem_e_traducao_na_fala(scripted, secoes_draft):
    rascunho = _traduzido("All delight longs for repetitions", "todo deleite anseia por repetição")

    roteiro, _ = _escrever_estake(scripted, secoes_draft, rascunho)

    citacao = roteiro.secoes[1].blocos[0].citacoes_literais[0]
    assert citacao.traducao == "todo deleite anseia por repetição"


def test_traducao_com_original_fora_da_passagem_e_recusada(scripted, secoes_draft):
    rascunho = _traduzido("All joy wants eternity", "todo deleite anseia por repetição")

    with pytest.raises(ValueError, match="não confere"):
        _escrever_estake(scripted, secoes_draft, rascunho)


def test_traducao_ausente_da_fala_e_recusada(scripted, secoes_draft):
    rascunho = _traduzido(
        "All delight longs for repetitions", "todo deleite anseia por repetição",
        fala="Nietzsche fala de repetição.",
    )

    with pytest.raises(ValueError, match="não confere"):
        _escrever_estake(scripted, secoes_draft, rascunho)


def test_traducao_tolera_diferenca_de_espacos(scripted, secoes_draft):
    """O modelo quebra linha e duplica espaço ao copiar; a palavra é a mesma."""
    rascunho = _traduzido(
        "All delight  longs\nfor repetitions", "todo deleite  anseia por\nrepetição",
        fala='Nietzsche escreve, em tradução livre: "todo deleite anseia por repetição".',
    )

    roteiro, _ = _escrever_estake(scripted, secoes_draft, rascunho)

    assert roteiro.secoes[1].blocos[0].citacoes_literais
