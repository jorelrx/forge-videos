from forge.domain.models import ReviewResult, Nota, Roteiro, Secao
from forge.agents.review import revisar, alegacoes_reais

def _roteiro():
    return Roteiro(tema="t", tese="te", secoes=[Secao(nome="Hook", conteudo="c")])

def test_revisar_aprovado(scripted):
    model = scripted(structured=[ReviewResult(aprovado=True)])
    rr = revisar(model, _roteiro())
    assert rr.aprovado is True

def test_revisar_reprovado_com_notas(scripted):
    model = scripted(structured=[ReviewResult(aprovado=False, notas=[Nota(dimensao="fato", problema="p", sugestao="s")])])
    rr = revisar(model, _roteiro())
    assert rr.aprovado is False and rr.notas[0].dimensao == "fato"


def test_checklist_do_revisor_nao_vira_alegacao():
    """Payload real do run de 2026-09-06 (04-review-r2.md).

    O modelo usa `Verificar` como checklist de autoavaliação. Cada linha virava
    um item, `verificar` nunca esvaziava, e o grafo voltava para research em toda
    rodada — ~50 min por volta nesta máquina.
    """
    itens = [
        "Hook sem preâmbulo?",
        "Sim",
        "Conclusão transforma Hook?",
        "Sim (carro volta)",
        "Zero aspas indevidas?",
        "Sim",
    ]

    assert alegacoes_reais(itens) == []


def test_alegacao_de_verdade_sobrevive():
    itens = [
        "Bergson afirma em Time and Free Will que a duração não é mensurável.",
        "Leibniz chamou o poder sobre a vontade de oblíquo na Teodiceia.",
    ]

    assert alegacoes_reais(itens) == itens


def test_afirmacao_solta_e_pergunta_caem_mas_o_resto_fica():
    itens = [
        "Sim",
        "não",
        "  ",
        "O roteiro atribui a Hume a definição de liberdade como ausência de coação?",
        "Hume define liberdade como ausência de coação externa.",
    ]

    assert alegacoes_reais(itens) == ["Hume define liberdade como ausência de coação externa."]


def test_negativa_longa_que_abre_com_resposta_sobrevive():
    """A regra de resposta olha só a palavra de abertura — precisa do teto de
    tamanho para não engolir uma negativa de verdade junto com o "Não" do
    checklist.
    """
    itens = ["Não há registro de que Hume tenha escrito isso."]

    assert alegacoes_reais(itens) == itens


def test_pontuacao_colada_na_resposta_tambem_cai():
    """Uma vírgula na palavra de abertura não pode driblar a regra 1 — é a
    forma mais natural do modelo pontuar uma resposta de checklist.
    """
    itens = ["OK, confere isso.", "Sim, confere direitinho.", "Ok confere tudo certo."]

    assert alegacoes_reais(itens) == []


def test_na_contracao_nao_e_resposta_de_checklist():
    """"na" é grafia de "n/a" na lista de respostas, mas colide com a
    contração portuguesa comum — não pode derrubar uma alegação real.
    """
    itens = ["Na obra ele erra.", "Na carta ele nega."]

    assert alegacoes_reais(itens) == itens


def test_negativa_curta_cai_por_desenho_nao_por_acidente():
    """Pino da troca deliberada: um veredito negativo curto que abre com
    palavra de resposta é descartado de propósito. `verificar` é para
    alegações do ROTEIRO, não para o veredito do revisor — isso é `notas`.
    Este teste existe para que a próxima pessoa que mexer no teto de seis
    palavras veja que está desfazendo uma escolha, não corrigindo um bug.
    """
    itens = ["Não há registro."]

    assert alegacoes_reais(itens) == []


def test_revisar_entrega_verificar_ja_filtrado(scripted):
    bruto = ReviewResult(aprovado=True, verificar=["Hook sem preâmbulo?", "Sim"])
    model = scripted(structured=[bruto])
    roteiro = Roteiro(tema="t", tese="t", secoes=[Secao(nome="Hook", conteudo="c")])

    resultado = revisar(model, roteiro)

    assert resultado.verificar == []
    assert resultado.aprovado is True
