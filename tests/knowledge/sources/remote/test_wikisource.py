from forge.knowledge.sources.remote.wikisource import (
    Wikisource,
    extrair_plaintext,
    parse_busca,
)


def test_parse_busca_prefixa_lang_no_id():
    payload = {"query": {"search": [{"title": "A República"}, {"title": "Ética"}]}}
    refs = parse_busca(payload, "pt")
    assert [r.id_externo for r in refs] == ["pt:A República", "pt:Ética"]
    assert refs[0].idioma == "pt"
    assert refs[0].fonte == "wikisource"


def test_extrair_plaintext_pega_extract_da_pagina():
    payload = {"query": {"pages": {"123": {"title": "A República", "extract": "corpo"}}}}
    assert extrair_plaintext(payload) == "corpo"


def test_buscar_varre_langs_configurados():
    chamadas = []

    class FakeHttp:
        def get_json(self, url, *, params=None):
            chamadas.append(url)
            lang = "pt" if "pt." in url else "en"
            return {"query": {"search": [{"title": f"Obra {lang}"}]}}

    refs = Wikisource(["pt", "en"]).buscar("tema", http=FakeHttp(), pagina=1)
    assert {r.idioma for r in refs} == {"pt", "en"}
    assert any("pt.wikisource" in c for c in chamadas)
    assert any("en.wikisource" in c for c in chamadas)


def test_baixar_monta_documento():
    class FakeHttp:
        def get_json(self, url, *, params=None):
            return {"query": {"pages": {"1": {"extract": "texto da obra"}}}}

    from forge.knowledge.sources.remote.base import Referencia

    ref = Referencia(fonte="wikisource", id_externo="pt:A República",
                     titulo="A República", url="https://pt.wikisource.org/w/api.php", idioma="pt")
    doc = Wikisource(["pt"]).baixar(ref, http=FakeHttp())
    assert doc.texto == "texto da obra"
    assert doc.proveniencia.idioma == "pt"
