import json
from datetime import UTC, datetime, timedelta

from forge.services.persistencia import gravar_modelo
from forge.services.publicacao import EstadoPublicacao

from .test_board_aprovacao import aprovar, pauta_pronta
from .test_board_criativo import PAUTA, Modelo, alterar, analisar, estado, proposta
from .test_insights import fonte  # noqa: F401


def _aprovado(client):
    return aprovar(client, pauta_pronta(client))["run_id"]


def _publicar(settings, run_id, **campos):
    gravar_modelo(settings.studio_runs_dir / run_id / "video" / "publicacao.json", EstadoPublicacao(
        etapa="concluida", titulo="Um ensaio", video_id="vid-board", canal_id="UC1",
        abertura_sha256="sha-da-abertura", **campos))


def _catalogar(services, run_id, dias):
    publicado = (datetime.now(UTC) - timedelta(days=dias)).isoformat()
    with services.commands.db.transaction() as conn:
        conn.execute("""INSERT INTO catalogo_canal (canal_id,video_id,titulo,thumbnail,publicado_em,run_id)
            VALUES ('UC1','vid-board','Um ensaio','',?,?)""", (publicado, run_id))


def _episodio(client):
    [item] = estado(client)["episodios"]
    return item


def test_percurso_do_episodio(client, services, settings):
    run_id = _aprovado(client)
    item = _episodio(client)
    assert item["momento"] == "em_producao" and item["run_id"] == run_id
    assert item["abertura"] == PAUTA["abertura"]

    _publicar(settings, run_id, publicar_em="2026-12-01T18:00:00-03:00")
    item = _episodio(client)
    assert item["momento"] == "agendado" and item["janelas"] is None
    assert item["abertura_sha256"] == "sha-da-abertura"

    _catalogar(services, run_id, dias=10)
    item = _episodio(client)
    assert item["momento"] == "janela_completa"
    assert item["janelas"]["d7"]["completa"] and not item["janelas"]["d28"]["completa"]
    assert item["url"].startswith("/canais/UC1/videos/vid-board?")


def test_publicacao_ilegivel_nao_derruba_board(client, settings):
    run_id = _aprovado(client)
    destino = settings.studio_runs_dir / run_id / "video" / "publicacao.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("{quebrado", encoding="utf-8")
    assert _episodio(client)["momento"] == "em_producao"


class ModeloQueGuardaFontes(Modelo):
    fontes = None

    def invoke(self, messages):
        type(self).fontes = json.loads(messages[-1].content)["fontes"]
        self.chamadas += 1
        return {"parsed": {"propostas": [
            proposta("continuacao", "A volta", ["episodio:vid-board"]),
            proposta("publico", "Uma dúvida"),
            proposta("experimento", "Um teste"),
        ]}}


def test_episodio_publicado_vira_fonte_da_analise(client, services, settings):
    run_id = _aprovado(client)
    _publicar(settings, run_id)
    _catalogar(services, run_id, dias=3)
    client.app.state.modelo_board = ModeloQueGuardaFontes
    board = alterar(client, estado(client), "posicionamento", texto="Canal")
    board = analisar(client, board)
    fonte = ModeloQueGuardaFontes.fontes["episodio:vid-board"]
    assert "Abertura aprovada: " + PAUTA["abertura"] in fonte["texto"]
    continuacao = board["propostas"][0]
    assert continuacao["referencias"][0]["tipo"] == "episodio"
    assert continuacao["hipotese"] is False


def test_publicacao_do_board_mantem_canal_aprovado(client, settings):
    run_id = _aprovado(client)
    (settings.studio_runs_dir / run_id).mkdir(parents=True, exist_ok=True)
    resp = client.post(f"/api/runs/{run_id}/publication", json={"canal_id": "OUTRO"})
    assert resp.status_code == 404


def test_detalhe_do_video_mostra_pauta_de_origem(client, settings, fonte):
    run_id = _aprovado(client)
    gravar_modelo(settings.studio_runs_dir / run_id / "video" / "publicacao.json", EstadoPublicacao(
        etapa="concluida", titulo="Um ensaio", video_id="a", canal_id="UC1", abertura_sha256="sha-da-abertura"))
    janela = {"inicio": "2026-01-01", "fim": "2026-01-01"}
    assert client.post("/api/canais/UC1/sincronizacoes", params=janela).status_code == 202
    origem = client.get("/api/canais/UC1/videos/a", params=janela).json()["episodio_board"]
    assert origem["abertura"] == PAUTA["abertura"] and origem["revisao"] >= 1
    assert origem["abertura_sha256"] == "sha-da-abertura"
    assert client.get("/api/canais/UC1/videos/b", params=janela).json()["episodio_board"] is None
