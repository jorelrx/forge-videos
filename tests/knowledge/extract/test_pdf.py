from forge.knowledge.sources.extract.pdf import montar_paginas
from forge.knowledge.sources.extract.tipos import pagina_de_offset


def test_montar_paginas_concatena_e_devolve_offset_inicial_de_cada_uma():
    texto, paginas = montar_paginas(["um", "dois", "três"])
    assert texto == "um\n\ndois\n\ntrês"
    assert paginas == [0, 4, 10]
    assert texto[paginas[1]:].startswith("dois")
    assert texto[paginas[2]:].startswith("três")


def test_offset_de_cada_pagina_resolve_para_o_numero_certo():
    texto, paginas = montar_paginas(["um", "dois", "três"])
    assert pagina_de_offset(paginas, texto.index("um")) == 1
    assert pagina_de_offset(paginas, texto.index("dois")) == 2
    assert pagina_de_offset(paginas, texto.index("três")) == 3


def test_pagina_vazia_ocupa_offset_mas_nao_quebra_a_contagem():
    texto, paginas = montar_paginas(["um", "", "três"])
    assert len(paginas) == 3
    assert pagina_de_offset(paginas, texto.index("três")) == 3


def test_lista_vazia_devolve_texto_vazio_e_nenhuma_pagina():
    assert montar_paginas([]) == ("", [])
