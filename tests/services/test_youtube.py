import json

import httpx
import pytest

SESSAO = "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=abc"


def cliente(handler, trecho=4):
    from forge.services.youtube import YouTubeClient
    return YouTubeClient(lambda: "tok", client=httpx.Client(
        transport=httpx.MockTransport(handler)), trecho=trecho, espera=lambda s: None)


def erro(status, reason, message="falhou"):
    return httpx.Response(status, json={"error": {
        "code": status, "message": message, "errors": [{"reason": reason}]}})


def test_iniciar_upload_pede_sessao_retomavel_com_metadados():
    def handler(request):
        assert request.method == "POST"
        assert request.url.params["uploadType"] == "resumable"
        assert request.url.params["part"] == "snippet,status"
        assert request.headers["Authorization"] == "Bearer tok"
        assert request.headers["X-Upload-Content-Length"] == "10"
        assert request.headers["X-Upload-Content-Type"] == "video/mp4"
        assert json.loads(request.content)["snippet"]["title"] == "T"
        return httpx.Response(200, headers={"Location": SESSAO})

    assert cliente(handler).iniciar_upload({"snippet": {"title": "T"}}, 10) == SESSAO


def test_envio_em_trechos_com_content_range_ate_o_video(tmp_path):
    arquivo = tmp_path / "v.mp4"
    arquivo.write_bytes(b"0123456789")
    vistos, avancos = [], []

    def handler(request):
        intervalo = request.headers["Content-Range"]
        vistos.append((intervalo, request.content))
        if intervalo.endswith("/10") and intervalo.startswith("bytes 8-"):
            return httpx.Response(200, json={"id": "vid123"})
        fim = int(intervalo.split("-")[1].split("/")[0])
        return httpx.Response(308, headers={"Range": f"bytes=0-{fim}"})

    video = cliente(handler).enviar_arquivo(SESSAO, arquivo, inicio=0, ao_avancar=avancos.append)
    assert video["id"] == "vid123"
    assert vistos == [("bytes 0-3/10", b"0123"), ("bytes 4-7/10", b"4567"), ("bytes 8-9/10", b"89")]
    assert avancos == [4, 8]


def test_falha_de_rede_consulta_a_sessao_e_continua_do_offset(tmp_path):
    arquivo = tmp_path / "v.mp4"
    arquivo.write_bytes(b"0123456789")
    chamadas = []

    def handler(request):
        intervalo = request.headers["Content-Range"]
        chamadas.append(intervalo)
        if intervalo == "bytes */10":
            return httpx.Response(308, headers={"Range": "bytes=0-5"})
        if intervalo == "bytes 0-7/10":
            raise httpx.ConnectError("caiu")
        return httpx.Response(200, json={"id": "v"})

    assert cliente(handler, trecho=8).enviar_arquivo(SESSAO, arquivo, inicio=0)["id"] == "v"
    # O servidor guardou só 6 bytes do trecho cortado: continua do 6, não do 8.
    assert chamadas == ["bytes 0-7/10", "bytes */10", "bytes 6-9/10"]


def test_retomar_de_offset_salvo_consulta_antes(tmp_path):
    arquivo = tmp_path / "v.mp4"
    arquivo.write_bytes(b"0123456789")
    chamadas = []

    def handler(request):
        chamadas.append(request.headers["Content-Range"])
        if request.headers["Content-Range"] == "bytes */10":
            return httpx.Response(308)  # sem Range: nada recebido
        return httpx.Response(201, json={"id": "v"})

    cliente(handler, trecho=100).enviar_arquivo(SESSAO, arquivo, inicio=6)
    assert chamadas == ["bytes */10", "bytes 0-9/10"]


def test_erros_5xx_esgotam_tentativas_com_erro_transitorio(tmp_path):
    from forge.services.youtube import YouTubeError
    arquivo = tmp_path / "v.mp4"
    arquivo.write_bytes(b"01")
    with pytest.raises(YouTubeError, match="rede|servidor"):
        cliente(lambda r: httpx.Response(503)).enviar_arquivo(SESSAO, arquivo, inicio=0)


@pytest.mark.parametrize("resposta, tipo", [
    (erro(403, "quotaExceeded"), "YouTubeQuotaError"),
    (erro(400, "uploadLimitExceeded"), "YouTubeQuotaError"),
    (erro(401, "authError"), "YouTubeAuthError"),
    (erro(400, "invalidTitle", "título inválido"), "YouTubeError"),
])
def test_erros_tipados(resposta, tipo):
    import forge.services.youtube as yt
    with pytest.raises(getattr(yt, tipo)) as capturado:
        cliente(lambda r: resposta).iniciar_upload({}, 1)
    if tipo == "YouTubeError":
        assert "título inválido" in str(capturado.value)


def test_sessao_expirada_e_erro_proprio(tmp_path):
    from forge.services.youtube import YouTubeSessaoExpirada
    arquivo = tmp_path / "v.mp4"
    arquivo.write_bytes(b"01")
    with pytest.raises(YouTubeSessaoExpirada):
        cliente(lambda r: httpx.Response(404)).enviar_arquivo(SESSAO, arquivo, inicio=1)


def test_thumbnail_vai_como_media_jpeg(tmp_path):
    thumb = tmp_path / "t.jpg"
    thumb.write_bytes(b"\xff\xd8jpeg")

    def handler(request):
        assert request.url.path.endswith("/thumbnails/set")
        assert request.url.params["videoId"] == "vid"
        assert request.headers["Content-Type"] == "image/jpeg"
        assert request.content == b"\xff\xd8jpeg"
        return httpx.Response(200, json={})

    cliente(handler).definir_thumbnail("vid", thumb)


def test_legenda_vai_multipart_com_snippet(tmp_path):
    srt = tmp_path / "l.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nOi\n", encoding="utf-8")

    def handler(request):
        assert request.url.path.endswith("/captions")
        assert request.url.params["uploadType"] == "multipart"
        assert request.headers["Content-Type"].startswith("multipart/related; boundary=")
        corpo = request.content.decode()
        assert '"videoId": "vid"' in corpo and '"language": "pt-BR"' in corpo
        assert "Oi" in corpo
        return httpx.Response(200, json={"id": "cap"})

    cliente(handler).enviar_legenda("vid", srt, idioma="pt-BR", nome="Português")


def test_meu_canal_le_id_titulo_e_foto():
    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/youtube/v3/channels"
        assert request.url.params["mine"] == "true"
        assert request.url.params["part"] == "snippet"
        return httpx.Response(200, json={"items": [{"id": "UC1", "snippet": {
            "title": "Conquistas Cósmicas",
            "thumbnails": {"default": {"url": "https://img/d"}, "medium": {"url": "https://img/m"}},
        }}]})

    assert cliente(handler).meu_canal() == {
        "id": "UC1", "titulo": "Conquistas Cósmicas", "thumbnail": "https://img/m"}


def test_conta_sem_canal_e_erro_com_acao():
    from forge.services.youtube import YouTubeError
    with pytest.raises(YouTubeError, match="canal"):
        cliente(lambda r: httpx.Response(200, json={"items": []})).meu_canal()
