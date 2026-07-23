from forge.knowledge.sources.remote.base import Referencia
from forge.knowledge.sources.remote.sep import SEP, extrair_artigo, parse_busca


def _bloco(slug, titulo, autor):
    # Reproduz o markup real do SEP: link de resultado é um redirect
    # /search/r?entry=/entries/<slug>/&..., não um link direto /entries/<slug>/.
    href = (
        f"https://plato.stanford.edu/search/r?entry=/entries/{slug}/"
        f"&amp;page=1&amp;rank=0&amp;query=estoicismo"
    )
    return f"""
    <div class="result_listing">
      <div class="result_title"><a class="l" href="{href}">{titulo}</a></div>
      <div class="result_snippet">trecho <b>Estoicismo</b> ...</div>
      <div class="result_author">{autor}</div>
      <div class="result_url"><a href="{href}">https://plato.stanford.edu/entries/{slug}/</a></div>
    </div>
    """


def test_parse_busca_extrai_slug_titulo_autor_do_result_listing():
    html = (
        "<html><body>"
        '<a href="/entries/nav-link/">nav fora de result_listing (ignorar)</a>'
        + _bloco("justus-lipsius", "Justus Lipsius", "Jan Papy")
        + _bloco("stoicism", "Stoicism", "")
        + _bloco("justus-lipsius", "Justus Lipsius", "Jan Papy")  # duplicata
        + "</body></html>"
    )
    refs = parse_busca(html)
    assert [r.id_externo for r in refs] == ["justus-lipsius", "stoicism"]  # dedupe + nav ignorado
    assert refs[0].titulo == "Justus Lipsius"
    assert refs[0].autor == "Jan Papy"
    assert refs[0].url == "https://plato.stanford.edu/entries/justus-lipsius/"
    assert refs[0].idioma == "en"
    assert refs[1].autor is None  # result_author vazio -> None


def test_extrair_artigo_pega_conteudo():
    html = """
    <html><body>
      <div id="article-content"><p>Primeira frase.</p><p>Segunda.</p></div>
      <div id="bibliography">refs...</div>
    </body></html>
    """
    texto = extrair_artigo(html)
    assert "Primeira frase." in texto
    assert "Segunda." in texto
    assert "refs..." not in texto


def test_baixar_monta_documento_autoridade_09():
    class FakeHttp:
        def get_text_cacheado(self, url, *, fonte, id_externo, ext="txt"):
            return '<div id="article-content"><p>corpo</p></div>'

    ref = Referencia(fonte="sep", id_externo="stoicism", titulo="Stoicism",
                     url="https://plato.stanford.edu/entries/stoicism/", idioma="en")
    doc = SEP().baixar(ref, http=FakeHttp())
    assert "corpo" in doc.texto
    assert doc.proveniencia.autoridade == 0.9
    assert doc.proveniencia.fonte == "sep"
