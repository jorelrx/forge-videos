import httpx

from forge.knowledge.sources.remote.http import Http


def _http_fake(handler, tmp_path, tentativas=3):
    cliente = httpx.Client(transport=httpx.MockTransport(handler))
    return Http(cache_dir=tmp_path, rate_delay=0, tentativas=tentativas, cliente=cliente)


def test_cache_grava_e_relê_do_disco(tmp_path):
    chamadas = []

    def handler(request):
        chamadas.append(str(request.url))
        return httpx.Response(200, text="corpo do livro")

    http = _http_fake(handler, tmp_path)
    a = http.get_text_cacheado("https://x/1", fonte="gutenberg", id_externo="1")
    b = http.get_text_cacheado("https://x/1", fonte="gutenberg", id_externo="1")

    assert a == b == "corpo do livro"
    assert len(chamadas) == 1  # segunda leitura veio do disco


def test_get_json_desserializa(tmp_path):
    def handler(request):
        return httpx.Response(200, json={"ok": 1})

    http = _http_fake(handler, tmp_path)
    assert http.get_json("https://x/j") == {"ok": 1}


def test_retry_em_503_depois_sucesso(tmp_path):
    estado = {"n": 0}

    def handler(request):
        estado["n"] += 1
        if estado["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, text="ok")

    http = _http_fake(handler, tmp_path)
    assert http.get_text("https://x/r") == "ok"
    assert estado["n"] == 2


def test_status_nao_retriavel_nao_faz_retry(tmp_path):
    chamadas = []

    def handler(request):
        chamadas.append(str(request.url))
        return httpx.Response(404)

    http = _http_fake(handler, tmp_path)
    try:
        http.get_text("https://x/notfound")
        assert False, "should have raised HTTPStatusError"
    except httpx.HTTPStatusError:
        pass

    assert len(chamadas) == 1  # handler called exactly once, no retry


def test_retry_esgotado_relança_erro(tmp_path):
    chamadas = []

    def handler(request):
        chamadas.append(str(request.url))
        return httpx.Response(503)

    http = _http_fake(handler, tmp_path, tentativas=3)
    try:
        http.get_text("https://x/service-unavail")
        assert False, "should have raised HTTPStatusError"
    except httpx.HTTPStatusError:
        pass

    assert len(chamadas) == 3  # retried exactly tentativas times


def test_latin1_sem_charset_no_header_decodifica_certo(tmp_path):
    # Fonte serve bytes latin-1 e NÃO declara charset. httpx `.text` assumiria
    # utf-8 e injetaria U+FFFD; get_text tem que cair para cp1252/latin-1.
    corpo = "existência decadência coração".encode("latin-1")

    def handler(request):
        return httpx.Response(
            200, content=corpo, headers={"Content-Type": "text/plain"}
        )

    http = _http_fake(handler, tmp_path)
    texto = http.get_text("https://x/latin1")
    assert texto == "existência decadência coração"
    assert "�" not in texto  # nenhum replacement char


def test_charset_declarado_no_header_e_respeitado(tmp_path):
    corpo = "café society".encode("cp1252")

    def handler(request):
        return httpx.Response(
            200, content=corpo,
            headers={"Content-Type": "text/plain; charset=windows-1252"},
        )

    http = _http_fake(handler, tmp_path)
    assert http.get_text("https://x/decl") == "café society"


def test_utf8_continua_funcionando(tmp_path):
    corpo = "existência".encode("utf-8")

    def handler(request):
        return httpx.Response(
            200, content=corpo,
            headers={"Content-Type": "text/plain; charset=utf-8"},
        )

    http = _http_fake(handler, tmp_path)
    texto = http.get_text("https://x/utf8")
    assert texto == "existência"
    assert "�" not in texto
