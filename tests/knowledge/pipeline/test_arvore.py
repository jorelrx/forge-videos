from forge.knowledge.pipeline.arvore import construir_arvore, texto_de
from forge.knowledge.sources.extract.texto import extrair_texto

LIVRO = """# Capítulo 1

Primeiro parágrafo do capítulo um, longo o suficiente para virar chunk próprio.

Segundo parágrafo do capítulo um, também com tamanho adequado para sobreviver.

## Seção 1.1

Parágrafo dentro da seção, com comprimento suficiente para não ser mesclado.

# Capítulo 2

Parágrafo do capítulo dois, escrito com folga para passar do mínimo exigido.
"""


def arvore():
    return construir_arvore("doc-1", extrair_texto(LIVRO))


def por_nivel(chunks, nivel):
    return [c for c in chunks if c.nivel == nivel]


def test_raiz_e_o_livro_inteiro_sem_pai():
    raiz = arvore()[0]
    assert raiz.nivel == "livro"
    assert raiz.pai_id is None
    assert raiz.caminho == "0001"
    assert (raiz.offset_inicio, raiz.offset_fim) == (0, len(LIVRO))


def test_capitulos_penduram_na_raiz():
    chunks = arvore()
    raiz = chunks[0]
    capitulos = por_nivel(chunks, "capitulo")
    assert [c.titulo for c in capitulos] == ["Capítulo 1", "Capítulo 2"]
    assert all(c.pai_id == raiz.id for c in capitulos)


def test_subnivel_pendura_no_capitulo_e_nao_na_raiz():
    chunks = arvore()
    capitulo_um = next(c for c in chunks if c.titulo == "Capítulo 1")
    secao = next(c for c in chunks if c.titulo == "Seção 1.1")
    assert secao.nivel == "subcapitulo"
    assert secao.pai_id == capitulo_um.id
    assert secao.caminho.startswith(capitulo_um.caminho + ".")


def test_paragrafo_tem_texto_e_demais_niveis_nao():
    chunks = arvore()
    assert all(c.texto for c in por_nivel(chunks, "paragrafo"))
    assert all(c.texto is None for c in chunks if c.nivel != "paragrafo")


def test_sentencas_penduram_no_paragrafo():
    chunks = arvore()
    paragrafo = por_nivel(chunks, "paragrafo")[0]
    filhas = [c for c in chunks if c.pai_id == paragrafo.id]
    assert filhas
    assert all(c.nivel == "sentenca" for c in filhas)


def test_texto_de_reconstroi_qualquer_nivel_por_offset():
    chunks = arvore()
    capitulo = next(c for c in chunks if c.titulo == "Capítulo 2")
    assert "Parágrafo do capítulo dois" in texto_de(LIVRO, capitulo)


def test_fidelidade_paragrafos_reproduzem_o_original_na_ordem():
    chunks = arvore()
    trechos = [c.texto for c in por_nivel(chunks, "paragrafo")]
    posicao = 0
    for trecho in trechos:
        posicao = LIVRO.index(trecho, posicao)
        posicao += len(trecho)


def folhas_e_sentencas(chunks):
    return {c.id for c in chunks if c.nivel in {"paragrafo", "sentenca"}}


def test_estabilidade_insercao_no_meio_preserva_ids_das_folhas():
    """Propriedade que sustenta o acúmulo semântico: a anotação de K2-K4 vive
    sobre parágrafo e sentença, e essas têm que sobreviver à reingestão.

    Nó contêiner (raiz, capítulo) muda de id de propósito: o texto dele é o
    intervalo inteiro, que de fato passou a incluir o parágrafo novo.
    """
    antes = folhas_e_sentencas(arvore())
    alterado = LIVRO.replace(
        "# Capítulo 2",
        "Parágrafo novo inserido no meio do livro, com tamanho mais que suficiente.\n\n# Capítulo 2",
    )
    depois = folhas_e_sentencas(construir_arvore("doc-1", extrair_texto(alterado)))
    assert antes <= depois


def test_caminho_nao_colide_entre_secao_e_paragrafo_do_mesmo_pai():
    com_prefacio = "Prefácio longo o bastante para virar parágrafo próprio aqui.\n\n" + LIVRO
    chunks = construir_arvore("doc-1", extrair_texto(com_prefacio))
    raiz = chunks[0]
    filhos = [c for c in chunks if c.pai_id == raiz.id]
    assert len({c.caminho for c in filhos}) == len(filhos)


def test_texto_repetido_no_mesmo_documento_gera_ids_distintos():
    repetido = (
        "Mesmo parágrafo repetido duas vezes no livro para testar ocorrência.\n\n"
        "Mesmo parágrafo repetido duas vezes no livro para testar ocorrência.\n"
    )
    chunks = construir_arvore("doc-1", extrair_texto(repetido))
    paragrafos_ = por_nivel(chunks, "paragrafo")
    assert len(paragrafos_) == 2
    assert paragrafos_[0].id != paragrafos_[1].id


def test_documento_sem_cabecalho_pendura_paragrafos_direto_na_raiz():
    plano = (
        "Parágrafo um sem nenhum cabeçalho, longo o bastante para virar chunk.\n\n"
        "Parágrafo dois sem nenhum cabeçalho, também com tamanho adequado aqui.\n"
    )
    chunks = construir_arvore("doc-1", extrair_texto(plano))
    raiz = chunks[0]
    assert not [c for c in chunks if c.nivel in {"capitulo", "subcapitulo", "secao"}]
    assert all(c.pai_id == raiz.id for c in chunks if c.nivel == "paragrafo")


def test_pagina_e_propagada_quando_a_extracao_tem_paginas():
    from forge.knowledge.sources.extract.pdf import montar_paginas
    from forge.knowledge.sources.extract.tipos import TextoExtraido

    texto, offsets = montar_paginas([
        "Parágrafo da primeira página, com comprimento acima do mínimo exigido.",
        "Parágrafo da segunda página, também com comprimento acima do mínimo.",
    ])
    chunks = construir_arvore("doc-1", TextoExtraido(texto=texto, paginas=offsets))
    paginas = [c.pagina for c in chunks if c.nivel == "paragrafo"]
    assert paginas == [1, 2]
