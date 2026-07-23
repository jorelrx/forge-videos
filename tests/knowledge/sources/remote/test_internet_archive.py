import pytest

from forge.knowledge.sources.remote.base import Referencia
from forge.knowledge.sources.remote.internet_archive import (
    InternetArchive,
    escolher_arquivo_texto,
    parse_busca,
)


def test_parse_busca_normaliza_creator_e_language_lista():
    payload = {
        "response": {
            "docs": [
                {
                    "identifier": "meditations00",
                    "title": "Meditations",
                    "creator": ["Marcus Aurelius"],
                    "language": ["eng"],
                },
                {"title": "sem id"},  # sem identifier -> descartado
            ]
        }
    }
    refs = parse_busca(payload)
    assert len(refs) == 1
    r = refs[0]
    assert r.id_externo == "meditations00"
    assert r.autor == "Marcus Aurelius"
    assert r.idioma == "eng"
    assert r.url == "https://archive.org/metadata/meditations00"


def test_escolher_arquivo_prefere_djvu_txt():
    meta = {"files": [{"name": "scan.pdf"}, {"name": "book_djvu.txt"}, {"name": "notas.txt"}]}
    assert escolher_arquivo_texto(meta) == "book_djvu.txt"


def test_escolher_arquivo_none_quando_sem_texto():
    meta = {"files": [{"name": "scan.pdf"}, {"name": "img.jp2"}]}
    assert escolher_arquivo_texto(meta) is None


def test_baixar_sem_texto_levanta():
    class FakeHttp:
        def get_json(self, url, *, params=None):
            return {"files": [{"name": "scan.pdf"}]}

    ref = Referencia(fonte="internet_archive", id_externo="x", titulo="X",
                     url="https://archive.org/metadata/x")
    with pytest.raises(ValueError):
        InternetArchive().baixar(ref, http=FakeHttp())


def test_baixar_monta_documento():
    class FakeHttp:
        def get_json(self, url, *, params=None):
            return {"files": [{"name": "book_djvu.txt"}]}

        def get_text_cacheado(self, url, *, fonte, id_externo, ext="txt"):
            assert url == "https://archive.org/download/x/book_djvu.txt"
            return "conteúdo"

    ref = Referencia(fonte="internet_archive", id_externo="x", titulo="X",
                     url="https://archive.org/metadata/x", idioma="eng")
    doc = InternetArchive().baixar(ref, http=FakeHttp())
    assert doc.texto == "conteúdo"
    assert doc.proveniencia.fonte == "internet_archive"
