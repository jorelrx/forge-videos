import httpx

from forge.knowledge.sources.remote.gutenberg import (
    Gutenberg,
    limpar_boilerplate,
    parse_busca,
)


def test_buscar_404_pagina_alem_do_fim_devolve_vazio():
    class FakeHttp:
        def get_json(self, url, *, params=None):
            req = httpx.Request("GET", url)
            raise httpx.HTTPStatusError(
                "not found", request=req, response=httpx.Response(404, request=req)
            )

    # Gutendex 404 em página além da última = esgotou, não erro.
    assert Gutenberg().buscar("x", http=FakeHttp(), pagina=99) == []


def test_parse_busca_extrai_url_texto_plano():
    payload = {
        "results": [
            {
                "id": 1497,
                "title": "The Republic",
                "authors": [{"name": "Plato"}],
                "languages": ["en"],
                "formats": {
                    "text/html": "https://x/1497.html",
                    "text/plain; charset=utf-8": "https://x/1497.txt",
                },
            },
            {  # sem formato texto -> descartado
                "id": 2,
                "title": "Só imagem",
                "authors": [],
                "languages": ["fr"],
                "formats": {"image/jpeg": "https://x/2.jpg"},
            },
        ]
    }
    refs = parse_busca(payload)
    assert len(refs) == 1
    r = refs[0]
    assert r.fonte == "gutenberg"
    assert r.id_externo == "1497"
    assert r.autor == "Plato"
    assert r.idioma == "en"
    assert r.url == "https://x/1497.txt"


def test_limpar_boilerplate_corta_marcadores():
    bruto = (
        "cabeçalho legal\n"
        "*** START OF THE PROJECT GUTENBERG EBOOK THE REPUBLIC ***\n"
        "corpo real\n"
        "*** END OF THE PROJECT GUTENBERG EBOOK THE REPUBLIC ***\n"
        "rodapé licença"
    )
    assert limpar_boilerplate(bruto) == "corpo real"


def test_baixar_usa_cache_e_limpa():
    class FakeHttp:
        def get_text_cacheado(self, url, *, fonte, id_externo, ext="txt"):
            return "*** START OF THE PROJECT GUTENBERG EBOOK X ***\noi\n*** END OF THE PROJECT GUTENBERG EBOOK X ***"

    from forge.knowledge.sources.remote.base import Referencia

    ref = Referencia(fonte="gutenberg", id_externo="1497", titulo="The Republic", url="https://x/1497.txt", idioma="en")
    doc = Gutenberg().baixar(ref, http=FakeHttp())
    assert doc.texto == "oi"
    assert doc.proveniencia.fonte == "gutenberg"
    assert doc.proveniencia.idioma == "en"
    assert doc.titulo == "The Republic"
