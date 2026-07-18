from forge.writer.models import RoteiroDraft, Secao, Fonte
from forge.writer.write import escrever

def _draft():
    return RoteiroDraft(secoes=[Secao(nome="Hook", conteudo="c")])

def test_escrever_monta_roteiro(scripted):
    model = scripted(structured=[_draft()])
    fontes = [Fonte(titulo="Obra", autor="Autor")]
    r = escrever(model, "tema", "tese", "esboço", "notas", fontes)
    assert r.tema == "tema" and r.tese == "tese"
    assert r.secoes[0].nome == "Hook"
    assert r.fontes == fontes

def test_escrever_aceita_notas(scripted):
    model = scripted(structured=[_draft()])
    from forge.writer.models import Nota
    r = escrever(model, "t", "te", "e", "n", [], notas=[Nota(dimensao="clareza", problema="p", sugestao="s")])
    assert r.secoes  # não quebra com notas
