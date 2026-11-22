from .test_board_criativo import API, PAUTA, alterar, estado


def pauta_pronta(client):
    board = alterar(client, estado(client), "pauta", pauta=PAUTA)
    return alterar(client, board, "fluxo", fluxo_id="padrao")


def aprovar(client, board, status=201):
    resp = client.post(API + "/aprovacoes", json={"revisao": board["revisao"], "fluxo_id": "padrao"})
    assert resp.status_code == status, resp.text
    return resp.json()


def runs(services):
    with services.commands.db.connection() as conn:
        return conn.execute("SELECT id, canal_id FROM runs").fetchall()


def test_aprovar_cria_uma_execucao_e_abre_novo_rascunho(client, services):
    board = pauta_pronta(client)
    board = alterar(client, board, "posicionamento", texto="Canal de ensaios")
    resposta = aprovar(client, board)
    [run] = runs(services)
    assert run["id"] == resposta["run_id"] and run["canal_id"] == "UC1"
    detalhe = client.get(f"/api/runs/{run['id']}").json()
    snapshot = detalhe["run"]["config_snapshot"]
    assert snapshot["pauta_aprovada"]["revisao"] == board["revisao"]
    assert snapshot["pauta_aprovada"]["abertura"] == PAUTA["abertura"]
    assert snapshot["fluxo_geracao"]["id"] == "padrao"
    assert "revisao_editorial" not in snapshot
    assert detalhe["video"]["tema"] == PAUTA["tema"]
    novo = resposta["board"]
    assert novo["pauta"] is None and novo["conversa"] == [] and novo["fluxo_id"] is None
    assert novo["posicionamento"] == "Canal de ensaios"
    assert novo["ultima_aprovacao"]["run_id"] == run["id"]
    assert estado(client)["revisao"] == novo["revisao"]


def test_repetir_aprovacao_devolve_mesma_execucao(client, services):
    board = pauta_pronta(client)
    primeira = aprovar(client, board)
    segunda = aprovar(client, board, status=200)
    assert segunda["run_id"] == primeira["run_id"]
    assert segunda["aprovacao"]["id"] == primeira["aprovacao"]["id"]
    assert len(runs(services)) == 1


def test_aprovacao_com_revisao_vencida_ou_pendente(client, services):
    board = pauta_pronta(client)
    vencida = client.post(API + "/aprovacoes", json={"revisao": board["revisao"] - 1, "fluxo_id": "padrao"})
    assert vencida.status_code == 409
    assert vencida.json()["error"]["code"] == "revisao_board"
    board = alterar(client, board, "pauta", pauta={**PAUTA, "blocos": []})
    pendente = client.post(API + "/aprovacoes", json={"revisao": board["revisao"], "fluxo_id": "padrao"})
    assert pendente.status_code == 422
    assert "bloco" in pendente.json()["detail"]["error"]["message"]
    assert runs(services) == []


def test_geracao_direta_continua(client):
    resp = client.post("/api/videos?canal_id=UC1", json={"tema": "Tema direto"})
    assert resp.status_code == 201, resp.text
    assert "pauta_aprovada" not in resp.json()["run"]["config_snapshot"]

