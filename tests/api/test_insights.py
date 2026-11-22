import json

import pytest
from fastapi.testclient import TestClient

from forge.services.catalogo_canal import ANALYTICS, LEITURA
from forge.services.youtube import YouTubeAuthError


class CanalTeste:
    visiveis = ("a", "b", "antigo", "sem-medida")
    falha = False
    revogado = False

    def catalogo_publico(self, canal):
        for i in self.visiveis:
            yield dict(video_id=i, titulo="Externo " + i, thumbnail=None,
                       publicado_em="2025-01-05T12:00:00+00:00")
            if self.falha:
                raise RuntimeError("segunda página")

    def consultar(self, canal, inicio, fim, metricas, *, dimensao=None, video=None):
        if self.revogado:
            raise YouTubeAuthError("Revogado")
        if dimensao == "video":
            return [dict(video_id="a", views=70), dict(video_id="antigo", views=50),
                    dict(video_id="b", views=0)]
        if metricas[0] != "views":
            return []
        total = 120 if not video else 70
        if dimensao == "day":
            return [dict(dia=str(inicio), views=total, minutos=0)]
        return [dict(views=total, minutos=0)]


@pytest.fixture
def fonte(client, services, tmp_path):
    token = tmp_path / "credencial-local"
    token.write_text(json.dumps({"tokens": {"access_token": "teste", "refresh_token": "teste",
                                            "scope": " ".join([LEITURA, ANALYTICS])}}))
    with services.commands.db.transaction() as conn:
        conn.execute("UPDATE acesso_canais SET escopos=?,credencial=? WHERE canal_id='UC1'",
                     (" ".join([ANALYTICS, LEITURA]), str(token)))
    fonte = CanalTeste()
    client.app.state.clientes_insights = lambda cred: (fonte, fonte)
    return fonte


BASE = "/api/canais/UC1"
JANELA = {"inicio": "2026-01-01", "fim": "2026-01-01"}


def test_fluxo_publicado_externo_e_paginacao(client, fonte):
    r = client.post(BASE+"/sincronizacoes", params=JANELA)
    assert r.status_code == 202, r.text
    resumo = client.get(BASE+"/resumo", params=JANELA).json()
    assert resumo["views"] == 120
    assert {item["titulo"] for item in resumo["contribuicoes"]} == {
        "Externo a", "Externo b", "Externo antigo",
    }
    params = dict(**JANELA, limite=1, ordem="resultado", busca="Externo")
    ids = []
    while True:
        resposta = client.get(BASE+"/videos", params=params).json()
        item, = resposta["videos"]
        ids.append((item["video_id"], item["views"]))
        if not resposta["proximo_cursor"]:
            break
        params["cursor"] = resposta["proximo_cursor"]
    assert ids == [("a", 70), ("antigo", 50), ("b", 0), ("sem-medida", None)]
    assert client.get(BASE+"/resumo", params=JANELA).json()["views"] == 120
    client.get(BASE+"/videos/a", params=JANELA)
    detalhe = client.get(BASE+"/videos/a", params=JANELA).json()
    assert detalhe["video"]["run_id"] is None
    assert detalhe["observacoes"][0]["evidencia"].startswith("/canais/UC1/videos/a?")
    assert client.get(BASE+"/videos", params={**params, "busca": "diferente"}).status_code == 422
    assert client.get("/api/canais/B/videos/a", params=JANELA).status_code == 404
    assert TestClient(client.app).get(BASE+"/resumo").status_code == 401


def test_falha_preserva_geracao_e_retry_remove_videos(client, fonte):
    client.post(BASE+"/sincronizacoes", params=JANELA)
    anterior = client.get(BASE+"/resumo", params=JANELA).json()["ultima_atualizacao_catalogo"]
    fonte.visiveis = ("novo",)
    fonte.falha = True
    client.post(BASE+"/sincronizacoes", params=JANELA)
    resumo = client.get(BASE+"/resumo", params=JANELA).json()
    assert resumo["estado_catalogo"] == "falha_temporaria"
    assert resumo["ultima_atualizacao_catalogo"] == anterior
    assert len(client.get(BASE+"/videos", params=JANELA).json()["videos"]) == 4
    fonte.falha = False
    client.post(BASE+"/sincronizacoes", params=JANELA)
    assert [v["video_id"] for v in client.get(BASE+"/videos", params=JANELA).json()["videos"]] == ["novo"]
    assert client.get(BASE+"/videos/a", params=JANELA).status_code == 404


def test_revogacao_limita_cache_e_recusa_preserva_catalogo(client, fonte, services):
    client.post(BASE+"/sincronizacoes", params=JANELA)
    client.get(BASE+"/videos/a", params=JANELA)
    fonte.revogado = True
    client.post(BASE+"/sincronizacoes", params=JANELA)
    assert client.get(BASE+"/resumo", params=JANELA).json()["views"] is None
    assert client.get(BASE+"/videos/a", params=JANELA).json()["views"] is None
    with services.commands.db.transaction() as conn:
        conn.execute("UPDATE acesso_canais SET escopos=? WHERE canal_id='UC1'", (LEITURA,))
    s = client.get(BASE+"/resumo", params=JANELA).json()
    assert s["estado"] == "sem_autorizacao" and s["views"] is None
    itens = client.get(BASE+"/videos", params=JANELA).json()["videos"]
    assert len(itens) == 4 and all(v["views"] is None for v in itens)


def test_entrada_direta_a_frio_completa_leitura_em_segundo_plano(client, fonte):
    primeira = client.get(BASE+"/videos/a", params=JANELA)
    assert primeira.status_code == 503 and primeira.headers["retry-after"] == "3"
    assert client.get(BASE+"/videos/a", params=JANELA).status_code == 200


def test_reconciliacao_historico_com_medicao_manual(client, fonte, create_video, services):
    from forge.services.desempenho import Medicao, salvar_medicao
    from forge.services.publicacao import EstadoPublicacao

    run = create_video()["run"]["id"]
    raiz = services.settings.studio_runs_dir / run
    pasta = raiz / "video"
    pasta.mkdir(parents=True, exist_ok=True)
    estado = EstadoPublicacao(etapa="concluida", titulo="Externo a", video_id="a")
    (pasta / "publicacao.json").write_text(estado.model_dump_json(), encoding="utf-8")
    salvar_medicao(raiz, estado, Medicao(janela=7, visualizacoes=15, impressoes=20))
    with services.commands.db.transaction() as conn:
        conn.execute("UPDATE runs SET canal_id=NULL WHERE id=?", (run,))
    client.post(BASE+"/sincronizacoes", params=JANELA)
    client.get(BASE+"/videos/a", params=JANELA)
    resposta = client.get(BASE+"/videos/a", params=JANELA).json()
    assert resposta["video"]["run_id"] == run
    manual = resposta["janelas"]["d7"][0]
    assert manual["valor"] == 15 and manual["origem"] == "Medição manual"
    assert manual["cobertura"] is None and manual["inicio"] == "2025-01-05"
    with services.commands.db.connection() as conn:
        assert conn.execute("SELECT canal_id FROM runs WHERE id=?", (run,)).fetchone()[0] == "UC1"
