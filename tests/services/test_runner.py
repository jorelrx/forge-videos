from contextlib import contextmanager

import pytest

from forge.domain.midia import Beat, BlocoNarracao, PlanoMidia
from forge.domain.operacao import ItemStatus, WorkItem
from forge.gpu.broker import GPUOcupada, LiberacaoFalhou
from forge.services.manifesto import carregar, criar_ou_carregar, pendentes
from forge.services.runner import executar


def test_runner_projects_current_sqlite_items_over_stale_manifest(tmp_path):
    from forge.services.manifesto import Manifesto

    items = [
        WorkItem(
            id="db-b001", stage_run_id="stage-1", item_key="b001",
            status=ItemStatus.SUCCEEDED, input={"texto": "Primeira."},
            input_hash="a" * 64, attempts=1,
        ),
        WorkItem(
            id="db-i001", stage_run_id="stage-1", item_key="i001",
            status=ItemStatus.PENDING, input={"prompt": "uma ampulheta"},
            input_hash="b" * 64,
        ),
    ]
    stale = Manifesto(itens=[])

    result = executar(
        tmp_path, stale, {"imagem": _ok}, BrokerFalso(), work_items=items
    )

    assert [(item.id, item.estado) for item in result.itens] == [("b001", "ok"), ("i001", "ok")]


def test_runner_accepts_sqlite_items_as_resume_source(tmp_path):
    items = [
        WorkItem(
            id="db-i001", stage_run_id="stage-1", item_key="i001",
            status=ItemStatus.PENDING, input={"prompt": "uma ampulheta"},
            input_hash="b" * 64,
        )
    ]

    result = executar(tmp_path, items, {"imagem": _ok}, BrokerFalso())

    assert result.itens[0].estado == "ok"


def test_runner_projects_item_events_and_checkpoints_manifest(tmp_path):
    class Projector:
        def __init__(self):
            self.events = []

        def project(self, kind, payload):
            self.events.append((kind, payload))

    items = [
        WorkItem(
            id="db-i001", stage_run_id="stage-1", item_key="i001",
            status=ItemStatus.PENDING, input={"prompt": "uma ampulheta"},
            input_hash="b" * 64,
        )
    ]
    projector = Projector()

    result = executar(
        tmp_path, items, {"imagem": _ok}, BrokerFalso(), projector=projector
    )

    assert [kind for kind, _ in projector.events] == [
        "item.started", "item.succeeded"
    ]
    assert result.itens[0].estado == "ok"
    assert carregar(tmp_path).itens[0].estado == "ok"


def test_runner_resume_does_not_execute_succeeded_sqlite_item(tmp_path):
    seen = []
    items = [
        WorkItem(
            id="db-b001", stage_run_id="stage-1", item_key="b001",
            status=ItemStatus.SUCCEEDED, input={"texto": "já pronto"},
            input_hash="a" * 64, attempts=1, duration_ms=900,
        ),
        WorkItem(
            id="db-i001", stage_run_id="stage-1", item_key="i001",
            status=ItemStatus.PENDING, input={"prompt": "uma ampulheta"},
            input_hash="b" * 64,
        ),
    ]

    def imagem(item, run_dir):
        seen.append(item.id)
        _ok(item, run_dir)

    result = executar(tmp_path, items, {"imagem": imagem}, BrokerFalso())

    assert seen == ["i001"]
    assert {item.id: item.estado for item in result.itens} == {
        "b001": "ok", "i001": "ok",
    }


class BrokerFalso:
    def __init__(self):
        self.slots = []

    @contextmanager
    def exclusivo(self, recurso):
        self.slots.append(recurso)
        yield


def _plano():
    return PlanoMidia(
        blocos=[
            BlocoNarracao(id="b001", secao="Hook", texto="Primeira."),
            BlocoNarracao(id="b002", secao="Hook", texto="Segunda."),
        ],
        beats=[Beat(id="i001", bloco_id="b001", prompt="uma ampulheta")],
    )


def _ok(item, run_dir):
    """Executor falso: preenche o item por mutação, como o contrato pede."""
    item.saida = f"video/{item.tipo}/{item.id}"
    item.duracao_ms = 1000


def test_executa_todos_os_pendentes(tmp_path):
    m = criar_ou_carregar(tmp_path, _plano())

    final = executar(tmp_path, m, {"audio": _ok, "imagem": _ok}, BrokerFalso())

    assert [i.estado for i in final.itens] == ["ok", "ok", "ok"]
    assert carregar(tmp_path) == final


def test_toma_o_slot_uma_vez_por_grupo(tmp_path):
    """Trocar de recurso por item pagaria um reload de modelo por item."""
    m = criar_ou_carregar(tmp_path, _plano())
    broker = BrokerFalso()

    executar(tmp_path, m, {"audio": _ok, "imagem": _ok}, broker)

    assert broker.slots == ["tts", "imagem"]


def test_item_que_estoura_nao_derruba_os_seguintes(tmp_path):
    m = criar_ou_carregar(tmp_path, _plano())

    def audio(item, run_dir):
        if item.id == "b001":
            raise RuntimeError("audiocpp morreu")
        _ok(item, run_dir)

    final = executar(tmp_path, m, {"audio": audio, "imagem": _ok}, BrokerFalso())

    por_id = {i.id: i for i in final.itens}
    assert por_id["b001"].estado == "falhou"
    assert "audiocpp morreu" in por_id["b001"].erro
    assert por_id["b001"].tentativas == 1
    assert por_id["b002"].estado == "ok"
    assert por_id["i001"].estado == "ok"


def test_retomada_so_roda_os_pendentes(tmp_path):
    m = criar_ou_carregar(tmp_path, _plano())
    m.itens[0].estado = "ok"
    vistos = []

    def audio(item, run_dir):
        vistos.append(item.id)
        _ok(item, run_dir)

    executar(tmp_path, m, {"audio": audio, "imagem": _ok}, BrokerFalso())

    assert vistos == ["b002"]


def test_so_um_grupo(tmp_path):
    m = criar_ou_carregar(tmp_path, _plano())
    broker = BrokerFalso()

    final = executar(tmp_path, m, {"audio": _ok, "imagem": _ok}, broker, so="audio")

    por_id = {i.id: i for i in final.itens}
    assert por_id["i001"].estado == "pendente"
    assert broker.slots == ["tts"]


def test_grupo_sem_pendente_nao_toma_o_slot(tmp_path):
    m = criar_ou_carregar(tmp_path, _plano())
    for item in m.itens:
        if item.tipo == "audio":
            item.estado = "ok"
    broker = BrokerFalso()

    executar(tmp_path, m, {"audio": _ok, "imagem": _ok}, broker)

    assert broker.slots == ["imagem"]


def test_so_com_grupo_desconhecido_falha_alto(tmp_path):
    """"imagens" (plural) é o typo que o CLI --so vai cometer um dia; sem essa
    checagem o loop faria continue em silêncio e devolveria o manifesto intacto,
    indistinguível de um run que não tinha nada pendente."""
    m = criar_ou_carregar(tmp_path, _plano())

    with pytest.raises(ValueError) as exc:
        executar(tmp_path, m, {"audio": _ok, "imagem": _ok}, BrokerFalso(), so="imagens")

    mensagem = str(exc.value)
    assert "imagens" in mensagem
    assert "audio" in mensagem
    assert "imagem" in mensagem


class BrokerQueEstoura:
    """Broker que recusa um recurso e aceita os demais."""

    def __init__(self, recurso_ruim, excecao):
        self.recurso_ruim = recurso_ruim
        self.excecao = excecao
        self.slots = []

    @contextmanager
    def exclusivo(self, recurso):
        self.slots.append(recurso)
        if recurso == self.recurso_ruim:
            raise self.excecao
        yield


@pytest.mark.parametrize("excecao", [
    LiberacaoFalhou("tts não liberou a VRAM em 60.0s"),
    GPUOcupada("outro processo segura a GPU há mais de 900.0s"),
])
def test_falha_de_broker_marca_o_grupo_e_segue(tmp_path, excecao):
    """Sem isto a exceção sobe e aborta o `executar` inteiro: os itens ficam
    pendentes com tentativas 0 e erro vazio, indistinguíveis em disco de um
    grupo que ainda não rodou. Numa noite sem ninguém olhando, cada iteração
    queima o timeout e reencontra os mesmos pendentes, para sempre."""
    m = criar_ou_carregar(tmp_path, _plano())
    broker = BrokerQueEstoura("tts", excecao)

    final = executar(tmp_path, m, {"audio": _ok, "imagem": _ok}, broker)

    por_id = {i.id: i for i in final.itens}
    assert por_id["b001"].estado == "falhou"
    assert por_id["b002"].estado == "falhou"
    assert str(excecao) in por_id["b001"].erro
    assert por_id["b001"].tentativas == 1
    # o grupo seguinte roda: a falha é do grupo, não do run
    assert por_id["i001"].estado == "ok"
    assert broker.slots == ["tts", "imagem"]
    assert pendentes(final) == []
    assert carregar(tmp_path) == final


def test_grupo_sem_executor_vira_falha_e_nao_pendente(tmp_path):
    """Mesma classe de skip silencioso: um dicionário de executores incompleto
    deixava os itens pendentes para sempre."""
    m = criar_ou_carregar(tmp_path, _plano())

    final = executar(tmp_path, m, {"audio": _ok}, BrokerFalso())

    por_id = {i.id: i for i in final.itens}
    assert por_id["i001"].estado == "falhou"
    assert "executor" in por_id["i001"].erro
    assert por_id["i001"].tentativas == 1
    assert pendentes(final) == []


def test_item_que_falha_nao_deixa_saida_parcial(tmp_path):
    """Manifesto com estado `falhou` ao lado do caminho de um WAV truncado é
    convite para a montagem consumir meio arquivo."""
    m = criar_ou_carregar(tmp_path, _plano())

    def audio(item, run_dir):
        item.saida = f"video/audio/{item.id}.wav"
        item.duracao_ms = 4200
        raise RuntimeError("audiocpp morreu no meio")

    final = executar(tmp_path, m, {"audio": audio, "imagem": _ok}, BrokerFalso())

    por_id = {i.id: i for i in final.itens}
    assert por_id["b001"].estado == "falhou"
    assert por_id["b001"].saida == ""
    assert por_id["b001"].duracao_ms is None
