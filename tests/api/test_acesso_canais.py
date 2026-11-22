from fastapi.testclient import TestClient

from .conftest import autenticar
from .test_youtube_conta import CLIENTE, concluir, montar


def test_isola_duas_tentativas_e_revogacao(services, settings, tmp_path):
    a, liberar, canais = montar(services, settings, tmp_path)
    canais.salvar_cliente(CLIENTE)
    b = autenticar(TestClient(a.app), services, conta="outra", canais=())
    primeira = a.post("/api/youtube/login").json()["tentativa_id"]
    segunda = b.post("/api/youtube/login").json()["tentativa_id"]
    assert primeira != segunda
    assert b.get("/api/youtube/login/" + primeira).status_code == 404
    assert b.get(liberar.retornos[primeira]).status_code == 404
    assert a.get(liberar.retornos[primeira]).status_code == 200
    assert a.post("/api/sessao/sair").status_code == 204
    assert concluir(b, segunda, liberar)["status"] == "concluido"
    assert a.app.state.tentativas_youtube[primeira].login.aguardar(3)
    autenticar(a, services, canais=())
    assert a.get("/api/canais").json()["canais"] == []
    assert len(b.get("/api/canais").json()["canais"]) == 1


def test_reconexao_exige_o_mesmo_canal_e_preserva_credencial(services, settings, tmp_path):
    api, liberar, canais = montar(services, settings, tmp_path)
    canais.salvar_cliente(CLIENTE)
    tentativa = api.post("/api/youtube/login").json()["tentativa_id"]
    assert concluir(api, tentativa, liberar)["status"] == "concluido"
    from forge.repositories.acesso_canais import AcessoCanais
    fachada = AcessoCanais(services.commands.db, "pessoa", canais.settings)
    snapshot = fachada.credenciais("UC1")
    canais._identificar = lambda cred: {"id": "UC2", "titulo": "Canal 2"}
    diferente = api.post("/api/youtube/login", json={"canal_id": "UC1", "analytics": True})
    assert concluir(api, diferente.json()["tentativa_id"], liberar)["status"] == "falhou"
    assert [c.id for c in fachada.listar()] == ["UC1"]
    api.post("/api/youtube/channels/UC1/disconnect")
    assert snapshot.disponivel()
    snapshot.liberar()
    assert not snapshot.path.exists()


def test_canais_e_preferencia_sao_pessoais(services, settings, tmp_path):
    api, _, canais = montar(services, settings, tmp_path)
    # O índice legado da instalação nunca concede vínculo.
    canais.dir.mkdir(parents=True)
    (canais.dir / "canais.json").write_text('{"padrao":"A","canais":{"A":{"titulo":"Legado"}}}')
    (canais.dir / "A.json").write_text("{}")
    assert [c.id for c in canais.listar()] == ["A"]
    assert api.get("/api/canais").json()["canais"] == []
    a = autenticar(api, services, conta="um", canais=("A","B"))
    b = autenticar(TestClient(a.app), services, conta="dois", canais=("B",))
    assert a.put("/api/sessao/canal",json={"canal_id":"A"}).status_code == 204
    assert b.put("/api/sessao/canal",json={"canal_id":"A"}).status_code == 404
    assert b.get("/api/canais").json()["ultimo_canal_id"] is None
    assert a.get("/api/canais").json()["ultimo_canal_id"] == "A"
    assert a.post("/api/youtube/channels/A/disconnect").json()["ultimo_canal_id"] is None
    assert a.put("/api/sessao/canal",json={"canal_id":"A"}).status_code == 404
