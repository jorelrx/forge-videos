from forge.domain.models import RoteiroDraft, Secao, Fonte
from forge.agents.write import escrever

def _draft():
    return RoteiroDraft(secoes=[Secao(nome="Hook", conteudo="c")])

def test_escrever_monta_roteiro(scripted):
    model = scripted(structured=[_draft()])
    fontes = [Fonte(titulo="Obra", autor="Autor")]
    r, falta = escrever(model, "tema", "tese", "esboço", "notas", fontes)
    assert r.tema == "tema" and r.tese == "tese"
    assert r.secoes[0].nome == "Hook"
    assert r.fontes == fontes
    assert falta is None

def test_escrever_aceita_notas(scripted):
    model = scripted(structured=[_draft()])
    from forge.domain.models import Nota
    r, falta = escrever(model, "t", "te", "e", "n", [], notas=[Nota(dimensao="clareza", problema="p", sugestao="s")])
    assert r.secoes  # não quebra com notas
    assert falta is None


def test_escrever_canoniza_nome_de_secao_com_acento(scripted):
    """`Tensão` no lugar de `Tensao` reprovava as nove seções de uma vez.

    O contrato das seções é um conjunto fechado sem acento (`SECOES_NOMES`). O
    modelo escreve a palavra correta em português; sem canonizar na fronteira,
    `conferir_roteiro` lia seção ausente, pulava a checagem de TODAS as outras e
    a run morria em `script_gate_failed` por um acento.
    """
    from forge.domain.roteiro import canonizar_nome

    draft = RoteiroDraft(secoes=[Secao(nome="Tensão", conteudo="c")])
    model = scripted(structured=[draft])

    r, _ = escrever(model, "t", "te", "e", "n", [])

    assert r.secoes[0].nome == "Tensao"
    assert r.secoes[0].conteudo == "c"


def test_canonizar_nome_aceita_acento_caixa_e_desconhecido():
    from forge.domain.roteiro import canonizar_nome

    assert canonizar_nome("Tensão") == "Tensao"
    assert canonizar_nome("Aplicação") == "Aplicacao"
    assert canonizar_nome("  filósofo ") == "Filosofo"
    assert canonizar_nome("FECHO") == "Fecho"
    # Nome fora do contrato não é inventado nem descartado.
    assert canonizar_nome("Hook") == "Hook"
