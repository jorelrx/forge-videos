from fastapi.testclient import TestClient

from forge.repositories.board_criativo import BoardRepository
from forge.services.insights_canal import periodo

from .conftest import autenticar
from .test_insights import fonte


API = "/api/canais/UC1/board"


def proposta(tipo, titulo, refs=None):
    return {
        "tipo": tipo, "justificativa": "Justificativa editorial", "diferenca": "Um ângulo distinto",
        "referencias": refs or [],
        "pauta": {"titulo": titulo, "tema": titulo, "pergunta": "Por quê?",
                  "recorte": "Uma situação concreta sobre " + titulo, "promessa": "Explorar o problema"},
    }


class Modelo:
    chamadas = 0

    def __init__(self, *, inventar=False, falhar=False, historico=False):
        self.inventar, self.falhar = inventar, falhar
        self.historico = historico

    def with_structured_output(self, schema, **kwargs):
        self.schema = schema
        return self

    def invoke(self, messages):
        self.chamadas += 1
        if self.falhar:
            raise TimeoutError()
        if self.schema.__name__ == "PropostaModelo":
            return {"parsed": proposta("experimento", "Combinação")}
        refs = ["fonte-inventada"] if self.inventar else (["desempenho:a"] if self.historico else [])
        return {"parsed": {"propostas": [
            proposta("continuacao", "A origem", refs),
            proposta("publico", "Uma dúvida", ["comentario:c1"] if self.historico else []),
            proposta("experimento", "Um teste"),
        ]}}


def estado(client):
    resp = client.get(API)
    assert resp.status_code == 200, resp.text
    return resp.json()


def alterar(client, board, acao, **dados):
    resp = client.put(API, json={"revisao": board["revisao"], "acao": acao, **dados})
    assert resp.status_code == 200, resp.text
    return resp.json()


def analisar(client, board, tipo="sugestoes", **dados):
    resp = client.post(API + "/analises", json={"revisao": board["revisao"], "tipo": tipo, **dados})
    assert resp.status_code == 202, resp.text
    return estado(client)


def test_canal_novo_salva_tres_hipoteses_e_recupera_sem_chamar_modelo(client):
    modelo = Modelo()
    client.app.state.modelo_board = lambda: modelo
    vazio = estado(client)
    assert vazio["contexto"]["precisa_posicionamento"]
    com_contexto = alterar(client, vazio, "posicionamento", texto="Ensaios sobre escolhas cotidianas")
    board = analisar(client, com_contexto)
    assert len(board["propostas"]) == 3
    assert all(item["hipotese"] for item in board["propostas"])
    assert estado(client)["propostas"] == board["propostas"]
    resp = client.post(API + "/analises", json={"revisao": board["revisao"], "tipo": "sugestoes"})
    assert resp.status_code == 202
    assert modelo.chamadas == 1


def test_guardar_descartar_combinar_e_confirmar_preserva_rascunho(client):
    client.app.state.modelo_board = Modelo
    board = alterar(client, estado(client), "posicionamento", texto="Canal de filosofia")
    board = analisar(client, board)
    a, b, c = [p["id"] for p in board["propostas"]]
    board = alterar(client, board, "guardar", ideia_id=a)
    board = alterar(client, board, "descartar", ideia_id=c, motivo="Já coberto")
    board = alterar(client, board, "desenvolver", ideia_id=a)
    assert board["pauta"]["titulo"] == "A origem"
    board = analisar(client, board, "combinacao", ideias=[a, b])
    assert board["candidata"]["pauta"]["titulo"] == "Combinação"
    assert board["pauta"]["titulo"] == "A origem"
    stale = client.put(API, json={"revisao": board["revisao"] - 1, "acao": "desenvolver", "ideia_id": b})
    assert stale.status_code == 409
    board = alterar(client, board, "desenvolver", ideia_id=board["candidata"]["id"])
    assert board["pauta"]["titulo"] == "Combinação"
    assert [p["id"] for p in estado(client)["guardadas"]] == [a]
    client.post("/api/canais/UC1/sincronizacoes")
    assert estado(client)["pauta"] == board["pauta"]
    regenerado = analisar(client, board, atualizar=True)
    assert regenerado["propostas"][0]["id"] != a
    assert regenerado["guardadas"][0]["id"] == a
    assert regenerado["pauta"] == board["pauta"]


def test_fonte_inventada_ou_falha_libera_pauta_manual(client):
    vazio = alterar(client, estado(client), "posicionamento", texto="Ensaios")
    for modelo in (Modelo(inventar=True), Modelo(falhar=True)):
        client.app.state.modelo_board = lambda: modelo
        vazio = analisar(client, vazio)
        assert vazio["erro"] == "analise_indisponivel"
        assert vazio["propostas"] == []
    board = alterar(client, vazio, "pauta", pauta={"tema": "Escolhas", "titulo": "Um ensaio"})
    assert estado(client)["pauta"] == board["pauta"]


def test_isolamento_distingue_contas_mesmo_no_mesmo_canal(client, services):
    adaptar = alterar(client, estado(client), "posicionamento", texto="Posicionamento da conta A")
    outro = autenticar(TestClient(client.app), services, conta="outra", canais=("UC1",))
    assert estado(outro)["posicionamento"] == ""
    assert estado(client)["posicionamento"] == adaptar["posicionamento"]
    assert outro.get("/api/canais/B/board").status_code == 404
    assert TestClient(client.app).get(API).status_code == 401


def test_historico_real_do_catalogo_e_insights_chega_com_fontes(client, fonte):
    fonte.comentarios_publicos = lambda video: (
        [{"id": "c1", "texto": "Por que escolhemos assim?", "publicado_em": "2026-11-20"}] if video == "a" else [])
    client.app.state.modelo_board = lambda: Modelo(historico=True)
    client.post("/api/canais/UC1/sincronizacoes")
    board = estado(client)
    assert not board["contexto"]["precisa_posicionamento"]
    board = analisar(client, board)
    continuacao, publico, experimento = board["propostas"]
    assert continuacao["referencias"][0]["observacao"]["valor"] == 70
    assert "/videos/a?" in continuacao["referencias"][0]["url"]
    assert publico["referencias"][0]["texto"] == "Por que escolhemos assim?"
    assert not publico["hipotese"] and experimento["hipotese"]

    with client.app.state.services.commands.db.transaction() as conn:
        conn.execute("UPDATE acesso_canais SET escopos=? WHERE canal_id='UC1'",
                     ("https://www.googleapis.com/auth/youtube.readonly",))
    limitado = estado(client)["propostas"]
    assert limitado[0]["referencias"] == []
    assert limitado[0]["hipotese"]
    assert limitado[1]["referencias"][0]["id"] == "comentario:c1"


def test_board_reutiliza_duracao_media_que_ja_esta_no_detalhe(client, fonte):
    consultar = fonte.consultar

    def com_duracao(canal, inicio, fim, metricas, *, dimensao=None, video=None):
        if metricas == ("averageViewDuration",) and video == "a":
            return [{"dia": str(inicio), "duracao_media": 87}] if dimensao == "day" else [{"duracao_media": 87}]
        return consultar(canal, inicio, fim, metricas, dimensao=dimensao, video=video)

    fonte.consultar = com_duracao
    inicio, fim = periodo()
    janela = {"inicio": str(inicio), "fim": str(fim)}
    client.post("/api/canais/UC1/sincronizacoes", params=janela)
    client.get("/api/canais/UC1/videos/a", params=janela)
    observacoes = estado(client)["contexto"]["observacoes"]
    duracao = next(fonte for fonte in observacoes if fonte["observacao"]["medida"] == "duracao_media")
    assert duracao["observacao"]["valor"] == 87
    assert duracao["observacao"]["unidade"] == "segundos"


def test_reserva_unica_e_conclusao_nao_sobrescreve_edicao(client, services):
    repo = BoardRepository(services.commands.db, "pessoa", "UC1")
    dono, _ = repo.reservar(0, "sugestoes", 60, lambda board: "entrada")
    assert repo.reservar(0, "sugestoes", 60, lambda board: "entrada") is None
    board = alterar(client, estado(client), "pauta", pauta={"tema": "Texto escrito durante a análise"})
    repo.concluir(dono, lambda atual: setattr(atual, "analisado_em", "2026-11-22T12:00:00Z"))
    atual = estado(client)
    assert atual["operacao"] is None
    assert atual["pauta"] == board["pauta"]
    assert atual["revisao"] == board["revisao"] + 1
