from forge.knowledge.domain.models import Proveniencia


def test_de_fonte_remota_preenche_idioma_e_tipo_livro():
    p = Proveniencia.de_fonte_remota(
        fonte="gutenberg", autor="Marco Aurélio", obra="Meditações",
        url="https://x/1", idioma="en", autoridade=1.0,
    )
    assert p.tipo == "livro"
    assert p.fonte == "gutenberg"
    assert p.idioma == "en"
    assert p.autoridade == 1.0


def test_idioma_default_none_em_de_livro():
    p = Proveniencia.de_livro(fonte="a.txt")
    assert p.idioma is None
