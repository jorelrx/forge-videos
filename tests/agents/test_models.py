from forge.domain.models import (
    Fonte, Secao, Roteiro, Nota, ReviewResult, SECOES_NOMES,
)

def test_secoes_nomes_ordem():
    assert SECOES_NOMES == [
        "Gancho", "Estake", "Tensao", "Virada", "Filosofo",
        "Prova", "Espelho", "Aplicacao", "Fecho",
    ]

def test_roteiro_defaults():
    r = Roteiro(tema="T", tese="Te", secoes=[Secao(nome="Hook", conteudo="c")])
    assert r.fontes == []
    assert r.secoes[0].nome == "Hook"

def test_review_result():
    rr = ReviewResult(aprovado=False, notas=[Nota(dimensao="clareza", problema="p", sugestao="s")])
    assert rr.aprovado is False
    assert rr.notas[0].dimensao == "clareza"

def test_fonte_optional_fields():
    f = Fonte(titulo="Livro")
    assert f.autor is None and f.frase is None
