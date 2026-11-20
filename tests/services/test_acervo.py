import httpx
import pytest

from forge.services.acervo import Acervo, AcervoIndisponivel

BASE = "http://acervo.test"

PASSAGEM = {
    "path": "4363/ch2/p7",
    "book_id": 4363,
    "book_title": "Beyond Good and Evil",
    "authors": ["Friedrich Nietzsche"],
    "breadcrumb": "Chapter 2 > Section 3",
    "text": "trecho do livro",
    "url": "http://acervo.test/books/4363",
    "score": 0.81,
    "rerank_score": None,
}


def _acervo(handler) -> Acervo:
    """Cliente com transporte falso: o teste inteiro roda sem rede."""
    cliente = httpx.Client(base_url=BASE, transport=httpx.MockTransport(handler))
    return Acervo(BASE, client=cliente)


def test_buscar_converte_passagens():
    def handler(request):
        assert request.url.path == "/search"
        assert request.url.params["q"] == "livre-arbítrio"
        assert request.url.params["top"] == "3"
        return httpx.Response(200, json={
            "question": "livre-arbítrio", "took_ms": 12, "candidates": 1,
            "passages": [PASSAGEM],
        })

    passagens = _acervo(handler).buscar("livre-arbítrio", top=3)

    assert len(passagens) == 1
    p = passagens[0]
    assert p.path == "4363/ch2/p7"
    assert p.book_id == 4363
    assert p.book_title == "Beyond Good and Evil"
    assert p.authors == ["Friedrich Nietzsche"]
    assert p.score == 0.81


def test_buscar_sem_resultado_devolve_lista_vazia():
    def handler(request):
        return httpx.Response(200, json={
            "question": "x", "took_ms": 3, "candidates": 0, "passages": [],
        })

    assert _acervo(handler).buscar("x") == []


def test_acervo_fora_do_ar_levanta():
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(AcervoIndisponivel):
        _acervo(handler).buscar("x")


def test_resposta_de_erro_levanta():
    def handler(request):
        return httpx.Response(500, text="boom")

    with pytest.raises(AcervoIndisponivel):
        _acervo(handler).buscar("x")


def test_saude_devolve_false_em_vez_de_levantar():
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    assert _acervo(handler).saude() is False


def test_descobrir_converte_candidatos():
    def handler(request):
        assert request.url.path == "/discover"
        return httpx.Response(200, json={
            "query": "determinismo",
            "candidates": [
                {"id": 37358, "title": "Determinism or Free-Will?",
                 "authors": ["Chapman Cohen"], "ingested": False},
            ],
            "fronts": {},
        })

    candidatos = _acervo(handler).descobrir("determinismo")

    assert [c.id for c in candidatos] == [37358]
    assert candidatos[0].ingested is False


def test_resposta_200_nao_json_levanta():
    def handler(request):
        return httpx.Response(200, text="<html>not json</html>")

    with pytest.raises(AcervoIndisponivel):
        _acervo(handler).buscar("x")

    assert _acervo(handler).saude() is False


def test_livros_lista_o_catalogo():
    def handler(request):
        assert request.url.path == "/books"
        return httpx.Response(200, json={"total": 2, "books": [
            {"id": 1998, "title": "Thus Spake Zarathustra", "authors": [],
             "languages": ["en"], "subjects": ["Philosophy, German"],
             "fragments": None, "stage": "completed", "dense": "ok"},
            {"id": 7205, "title": "Also sprach Zarathustra", "languages": ["de"]},
        ]})

    livros = _acervo(handler).livros()

    assert [(livro.id, livro.title, livro.languages) for livro in livros] == [
        (1998, "Thus Spake Zarathustra", ["en"]),
        (7205, "Also sprach Zarathustra", ["de"]),
    ]
    assert livros[1].authors == [] and livros[1].subjects == []


def test_livros_com_acervo_fora_do_ar_levanta():
    def handler(request):
        return httpx.Response(503)

    with pytest.raises(AcervoIndisponivel):
        _acervo(handler).livros()
