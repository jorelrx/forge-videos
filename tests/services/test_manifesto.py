import json

from forge.domain.midia import Beat, BlocoNarracao, PlanoMidia
from forge.services.manifesto import (
    caminho,
    carregar,
    criar_ou_carregar,
    gravar,
    pendentes,
)


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


def test_pendentes_filtra_por_tipo(tmp_path):
    m = criar_ou_carregar(tmp_path, _plano())
    m.itens[0].estado = "ok"

    assert [i.id for i in pendentes(m, "audio")] == ["b002"]
    assert [i.id for i in pendentes(m, "imagem")] == ["i001"]
    assert [i.id for i in pendentes(m)] == ["b002", "i001"]


def test_gravar_e_atomico(tmp_path):
    """O manifesto é reescrito depois de cada item; um corte no meio da escrita
    não pode deixar um JSON truncado no lugar do progresso."""
    m = criar_ou_carregar(tmp_path, _plano())
    gravar(tmp_path, m)

    assert not list(caminho(tmp_path).parent.glob("*.tmp"))
    json.loads(caminho(tmp_path).read_text(encoding="utf-8"))
    assert carregar(tmp_path) == m
