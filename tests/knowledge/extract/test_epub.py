from forge.knowledge.sources.extract.epub import itens_do_spine, montar_itens


class _ItemFalso:
    def __init__(self, item_id: str, nome: str, titulo: str, html: str):
        self.item_id = item_id
        self._nome = nome
        self.title = titulo
        self._html = html

    def get_name(self) -> str:
        return self._nome

    def get_content(self) -> bytes:
        return self._html.encode("utf-8")


class _LivroFalso:
    def __init__(self, itens: list[_ItemFalso], spine: list[tuple[str, int]]):
        self._itens = itens
        self.spine = spine

    def get_item_with_id(self, idref: str):
        for item in self._itens:
            if item.item_id == idref:
                return item
        return None

    def get_items_of_type(self, _tipo):
        return list(self._itens)


def test_cada_item_do_spine_vira_marca_de_capitulo():
    extraido = montar_itens([("Capítulo 1", "<p>um</p>"), ("Capítulo 2", "<p>dois</p>")])
    capitulos = [m for m in extraido.marcas if m.nivel == 1]
    assert [m.titulo for m in capitulos] == ["Capítulo 1", "Capítulo 2"]


def test_headings_do_html_viram_subniveis_abaixo_do_capitulo():
    extraido = montar_itens([("Capítulo 1", "<h2>Parte A</h2><p>um</p><h3>Trecho</h3><p>dois</p>")])
    assert [(m.nivel, m.titulo) for m in extraido.marcas] == [
        (1, "Capítulo 1"),
        (2, "Parte A"),
        (3, "Trecho"),
    ]


def test_marca_aponta_para_o_offset_real_do_titulo_no_texto_montado():
    extraido = montar_itens([("Capítulo 1", "<h2>Parte A</h2><p>corpo</p>")])
    for marca in extraido.marcas:
        assert extraido.texto[marca.offset:].startswith(marca.titulo)


def test_epub_nao_tem_paginas():
    extraido = montar_itens([("Capítulo 1", "<p>um</p>")])
    assert extraido.paginas == []


def test_texto_do_html_e_preservado_no_corpo():
    extraido = montar_itens([("Capítulo 1", "<p>o homem é livre</p>")])
    assert "o homem é livre" in extraido.texto


def test_ordem_de_leitura_segue_o_spine_e_nao_o_manifesto():
    item_a = _ItemFalso("id-a", "a.xhtml", "Capítulo A", "<p>a</p>")
    item_b = _ItemFalso("id-b", "b.xhtml", "Capítulo B", "<p>b</p>")
    # manifesto traz B antes de A, mas o spine manda ler A antes de B.
    livro = _LivroFalso(itens=[item_b, item_a], spine=[("id-a", 1), ("id-b", 1)])

    itens = itens_do_spine(livro)

    assert [titulo for titulo, _ in itens] == ["Capítulo A", "Capítulo B"]


def test_spine_vazio_cai_para_ordem_do_manifesto():
    item_a = _ItemFalso("id-a", "a.xhtml", "Capítulo A", "<p>a</p>")
    item_b = _ItemFalso("id-b", "b.xhtml", "Capítulo B", "<p>b</p>")
    livro = _LivroFalso(itens=[item_a, item_b], spine=[])

    itens = itens_do_spine(livro)

    assert [titulo for titulo, _ in itens] == ["Capítulo A", "Capítulo B"]


def test_spine_com_idrefs_que_nao_resolvem_cai_para_manifesto():
    item_a = _ItemFalso("id-a", "a.xhtml", "Capítulo A", "<p>a</p>")
    livro = _LivroFalso(itens=[item_a], spine=[("id-fantasma", 1)])

    itens = itens_do_spine(livro)

    assert [titulo for titulo, _ in itens] == ["Capítulo A"]


def test_elemento_aninhado_nao_duplica_texto():
    extraido = montar_itens([("Capítulo 1", "<p>fora <p>dentro</p></p>")])

    assert extraido.texto.count("dentro") == 1
    for marca in extraido.marcas:
        assert extraido.texto[marca.offset:].startswith(marca.titulo)
