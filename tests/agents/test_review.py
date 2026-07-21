from forge.domain.models import ReviewResult, Nota, Roteiro, Secao
from forge.agents.review import revisar

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
