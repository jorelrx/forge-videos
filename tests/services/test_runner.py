from contextlib import contextmanager

from forge.domain.midia import Beat, BlocoNarracao, PlanoMidia
from forge.services.manifesto import carregar, criar_ou_carregar
from forge.services.runner import executar


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
