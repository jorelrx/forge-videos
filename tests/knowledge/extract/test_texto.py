from forge.knowledge.sources.extract.texto import extrair_texto, marcas_de_texto
from forge.knowledge.sources.extract.tipos import pagina_de_offset

MD = """# Parte I

abertura

## Capítulo 1

corpo do capítulo

### Seção A

detalhe
"""


def test_marcas_de_markdown_carregam_nivel_pelo_numero_de_cerquilhas():
    marcas = marcas_de_texto(MD)
    assert [(m.nivel, m.titulo) for m in marcas] == [
        (1, "Parte I"),
        (2, "Capítulo 1"),
        (3, "Seção A"),
    ]


def test_marca_aponta_para_o_offset_do_cabecalho_no_texto_original():
    marcas = marcas_de_texto(MD)
    for marca in marcas:
        assert MD[marca.offset:].startswith("#")


def test_comprimento_cobre_a_linha_inteira_do_cabecalho():
    marca = marcas_de_texto(MD)[1]
    assert MD[marca.offset:marca.offset + marca.comprimento] == "## Capítulo 1"
    # O corpo começa depois do cabeçalho inteiro, não depois do título.
    assert MD[marca.offset + marca.comprimento:].lstrip().startswith("corpo")


def test_cabecalho_em_prosa_e_reconhecido_sem_markdown():
    texto = "prólogo\n\nCapítulo 3\n\ncorpo\n\nCAPÍTULO IV\n\nmais\n"
    marcas = marcas_de_texto(texto)
    assert [m.titulo for m in marcas] == ["Capítulo 3", "CAPÍTULO IV"]
    assert all(m.nivel == 1 for m in marcas)


def test_cerquilha_no_meio_da_linha_nao_vira_marca():
    texto = "ele escreveu # sobre isso\n\ncorpo\n"
    assert marcas_de_texto(texto) == []


def test_texto_sem_cabecalho_nao_gera_marca():
    assert marcas_de_texto("só prosa corrida\n\nmais prosa\n") == []


def test_extrair_texto_preserva_o_original_e_nao_tem_paginas():
    extraido = extrair_texto(MD)
    assert extraido.texto == MD
    assert extraido.paginas == []
    assert len(extraido.marcas) == 3


def test_pagina_de_offset_mapeia_para_a_pagina_que_contem_o_offset():
    paginas = [0, 100, 250]
    assert pagina_de_offset(paginas, 0) == 1
    assert pagina_de_offset(paginas, 99) == 1
    assert pagina_de_offset(paginas, 100) == 2
    assert pagina_de_offset(paginas, 999) == 3


def test_pagina_de_offset_sem_paginas_devolve_nulo():
    assert pagina_de_offset([], 10) is None
