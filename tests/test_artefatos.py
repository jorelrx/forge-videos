from forge.domain.models import Fonte
from forge.services.artefatos import _fmt_fontes, _ler_fontes


def test_fonte_do_acervo_sobrevive_ao_round_trip():
    """path e book_id são a procedência; perdê-los no disco quebra o --retomar."""
    fontes = [
        Fonte(
            titulo="Beyond Good and Evil",
            autor="Friedrich Nietzsche",
            url="http://acervo.test/books/4363",
            path="4363/ch2/p7",
            book_id=4363,
        )
    ]

    linha = _fmt_fontes(fontes)
    lidas = _ler_fontes(linha)

    assert lidas == fontes


def test_fonte_antiga_sem_procedencia_ainda_carrega():
    """Runs gravadas antes do acervo não têm path; devem continuar legíveis."""
    lidas = _ler_fontes('fontes: [{"titulo": "Ética", "autor": "Espinosa", "url": null}]')

    assert lidas[0].titulo == "Ética"
    assert lidas[0].path is None
    assert lidas[0].book_id is None
