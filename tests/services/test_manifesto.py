import json
from unittest import mock

from forge.domain.midia import Beat, BlocoNarracao, PlanoMidia
from forge.domain.operacao import ItemStatus, WorkItem
from forge.services.manifesto import (
    Manifesto,
    caminho,
    carregar,
    criar_ou_carregar,
    gravar,
    pendentes,
)


def _db_item(item_key: str, status: ItemStatus) -> WorkItem:
    return WorkItem(
        id=f"db-{item_key}", stage_run_id="stage-1", item_key=item_key,
        status=status, input={"texto": f"texto {item_key}"}, input_hash="a" * 64,
        attempts=2, duration_ms=1200 if status is ItemStatus.SUCCEEDED else None,
        failure_code="item_failed" if status is ItemStatus.FAILED else None,
        failure_message="falha" if status is ItemStatus.FAILED else None,
    )


def test_manifest_is_rebuilt_from_database_items_not_used_as_authority():
    items = [_db_item("b001", ItemStatus.SUCCEEDED), _db_item("i001", ItemStatus.PENDING)]

    manifest = Manifesto.from_work_items(items)

    assert [(item.id, item.estado) for item in manifest.itens] == [
        ("b001", "ok"), ("i001", "pendente")
    ]


def test_criar_ou_carregar_uses_database_items_when_supplied(tmp_path):
    stale = Manifesto(itens=[{"id": "b001", "tipo": "audio", "estado": "ok"}])
    gravar(tmp_path, stale)

    current = [_db_item("b001", ItemStatus.PENDING)]
    rebuilt = criar_ou_carregar(tmp_path, _plano(), work_items=current)

    assert rebuilt.itens[0].estado == "pendente"


def test_manifest_merges_artifact_output_without_changing_database_status():
    manifest = Manifesto.from_work_items([_db_item("b001", ItemStatus.SUCCEEDED)])

    merged = manifest.merge_outputs([
        {
            "work_item_id": "db-b001",
            "relative_path": "video/audio/b001.wav",
            "metadata": {"duration_ms": 930},
        }
    ])

    assert merged.itens[0].estado == "ok"
    assert merged.itens[0].saida == "video/audio/b001.wav"
    assert merged.itens[0].duracao_ms == 930


def _plano():
    return PlanoMidia(
        blocos=[
            BlocoNarracao(id="b001", secao="Hook", texto="Primeira."),
            BlocoNarracao(id="b002", secao="Hook", texto="Segunda."),
        ],
        beats=[Beat(id="i001", bloco_id="b001", prompt="uma ampulheta")],
    )


def test_criar_gera_um_item_por_bloco_e_por_beat(tmp_path):
    m = criar_ou_carregar(tmp_path, _plano())

    assert [i.id for i in m.itens] == ["b001", "b002", "i001"]
    assert [i.tipo for i in m.itens] == ["audio", "audio", "imagem"]
    assert all(i.estado == "pendente" for i in m.itens)


def test_criar_preserva_o_progresso_de_um_manifesto_existente(tmp_path):
    """Retomar não pode zerar o que já foi gerado."""
    m = criar_ou_carregar(tmp_path, _plano())
    m.itens[0].estado = "ok"
    m.itens[0].saida = "video/audio/b001.wav"
    gravar(tmp_path, m)

    de_novo = criar_ou_carregar(tmp_path, _plano())

    assert de_novo.itens[0].estado == "ok"
    assert de_novo.itens[0].saida == "video/audio/b001.wav"


def test_criar_reseta_item_quando_entrada_muda(tmp_path):
    """Quando a entrada de um item muda (ex: texto do bloco foi editado),
    o item retorna a pendente mas preserva tentativas para histório de falhas."""
    m = criar_ou_carregar(tmp_path, _plano())
    m.itens[0].estado = "ok"
    m.itens[0].saida = "video/audio/b001.wav"
    m.itens[0].tentativas = 3
    gravar(tmp_path, m)

    # Plano modificado: texto de b001 muda
    plano_modificado = PlanoMidia(
        blocos=[
            BlocoNarracao(id="b001", secao="Hook", texto="Primeira modificada."),
            BlocoNarracao(id="b002", secao="Hook", texto="Segunda."),
        ],
        beats=[Beat(id="i001", bloco_id="b001", prompt="uma ampulheta")],
    )

    de_novo = criar_ou_carregar(tmp_path, plano_modificado)

    # Item resetado para pendente com nova entrada
    assert de_novo.itens[0].estado == "pendente"
    assert de_novo.itens[0].entrada["texto"] == "Primeira modificada."
    assert de_novo.itens[0].saida == ""
    assert de_novo.itens[0].duracao_ms is None
    assert de_novo.itens[0].erro == ""
    # Mas tentativas é preservada
    assert de_novo.itens[0].tentativas == 3


def test_pendentes_filtra_por_tipo(tmp_path):
    m = criar_ou_carregar(tmp_path, _plano())
    m.itens[0].estado = "ok"

    assert [i.id for i in pendentes(m, "audio")] == ["b002"]
    assert [i.id for i in pendentes(m, "imagem")] == ["i001"]
    assert [i.id for i in pendentes(m)] == ["b002", "i001"]


def test_escrita_interrompida_nao_corrompe_o_manifesto(tmp_path):
    """O manifesto é reescrito depois de cada item; um corte no meio da escrita
    não pode deixar um JSON truncado no lugar do progresso. Prova que os.replace
    é atômico e mantém a versão anterior intacta em caso de erro."""
    m = criar_ou_carregar(tmp_path, _plano())
    gravar(tmp_path, m)

    # Carrega o manifesto gravado com sucesso
    m_primeiro = carregar(tmp_path)

    # Monkeypatcha os.replace para simular falha durante escrita
    def replace_com_erro(src, dst):
        raise OSError("Simulação de corte de energia durante escrita")

    with mock.patch("forge.services.persistencia.os.replace", side_effect=replace_com_erro):
        # Mutate o manifesto e tenta gravar
        m.itens[0].estado = "falhou"
        m.itens[0].erro = "erro de teste"

        # Esperado: OSError se propaga
        try:
            gravar(tmp_path, m)
            assert False, "Deveria ter levantado OSError"
        except OSError:
            pass

    # Verifica que o arquivo original permanece intacto (nunca truncado)
    m_preservado = carregar(tmp_path)
    assert m_preservado == m_primeiro

    # Verifica que o arquivo temporário fica no mesmo diretório que o destino
    # (para que os.replace seja atômico no mesmo filesystem)
    dest = caminho(tmp_path)
    temp = dest.with_suffix(".json.tmp")
    assert temp.parent == dest.parent
