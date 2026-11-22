import httpx
import pytest

from forge.services.youtube import YouTubeClient


def test_catalogo_duas_paginas_confirma_canal_visibilidade_e_duplicatas():
    chamadas = []

    def responder(request):
        p = request.url.params
        chamadas.append((request.url.path, dict(p)))
        if request.url.path.endswith("/channels"):
            itens = [{"id": "A", "contentDetails": {"relatedPlaylists": {"uploads": "UU"}}}]
        elif request.url.path.endswith("/playlistItems"):
            ids = ["1", "2"] if "pageToken" not in p else ["1", "3", "4"]
            itens = [{"contentDetails": {"videoId": i}} for i in ids]
            if "pageToken" not in p:
                return httpx.Response(200, json={"items": itens, "nextPageToken": "dois"})
        else:
            itens = [
                {"id": i, "snippet": {"channelId": "B" if i == "3" else "A",
                 "title": i, "publishedAt": "2026-01-01T01:00:00Z"},
                 "status": {"privacyStatus": "private" if i == "2" else "public"},
                 "statistics": {"viewCount": "120", "commentCount": "3"}}
                for i in p["id"].split(",") if i != "4"
            ]
        return httpx.Response(200, json={"items": itens})

    with httpx.Client(transport=httpx.MockTransport(responder)) as http:
        yt = YouTubeClient(lambda: "teste", client=http)
        videos = list(yt.catalogo_publico("A"))
        assert [v["video_id"] for v in videos] == ["1"]
        assert videos[0]["views_total"] == 120
        assert videos[0]["comentarios_total"] == 3
        assert videos[0]["curtidas_total"] is None
        with pytest.raises(Exception, match="canal"):
            list(yt.catalogo_publico("B"))
    assert sum(path.endswith("/playlistItems") for path, _ in chamadas) == 2


def test_reinicio_recupera_posse_expirada_sem_publicar_geracao_antiga(tmp_path):
    from forge.repositories.connection import Database
    from forge.repositories.observacoes_canal import leitura
    from forge.repositories.schema import init_db

    db = Database(tmp_path / "catalogo.db")
    init_db(db)
    jobs = []
    def agendar(valor, forcar=False):
        return leitura(db, "A", "catalogo", ["leitura"], lambda: valor, jobs.append, forcar=forcar)

    assert agendar("antigo")[0] == "sincronizando"
    assert agendar("duplicado", True)[0] == "sincronizando" and len(jobs) == 1
    with db.transaction() as conn:
        conn.execute("UPDATE leituras_canal SET expira=0")
    assert agendar("novo")[0] == "sincronizando" and len(jobs) == 2
    jobs[1]()
    jobs[0]()
    estado, sucesso, valor = agendar("terceiro")
    assert (estado, valor) == ("atualizado", "novo") and sucesso
    assert len(jobs) == 2
