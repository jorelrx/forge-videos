from forge.agents.midia import carregar_plano, gravar_plano, planejar_midia
from forge.domain.midia import Beat, BlocoNarracao, PlanoMidia
from forge.domain.models import Roteiro, Secao


def _roteiro():
    return Roteiro(
        tema="livre-arbítrio",
        tese="a vontade é sentida, não observada",
        secoes=[Secao(nome="Hook", conteudo="c1"), Secao(nome="Problema", conteudo="c2")],
    )


def _plano_cru():
    """O que o modelo devolve: ids arbitrários, uma tag inventada."""
    return PlanoMidia(
        blocos=[
            BlocoNarracao(id="qualquer", secao="Hook",
                          texto="<|emotion:contemplation|>Primeira frase."),
            BlocoNarracao(id="outro", secao="Problema",
                          texto="<|mood:pensativo|>Segunda frase."),
        ],
        beats=[
            Beat(id="x", bloco_id="qualquer", prompt="uma ampulheta"),
            Beat(id="y", bloco_id="outro", prompt="uma estrada bifurcada"),
        ],
    )


def test_ids_sao_renumerados_deterministicamente(scripted):
    model = scripted(structured=[_plano_cru()])

    plano = planejar_midia(model, _roteiro())

    assert [b.id for b in plano.blocos] == ["b001", "b002"]
    assert [i.id for i in plano.beats] == ["i001", "i002"]
    assert [i.bloco_id for i in plano.beats] == ["b001", "b002"]


def test_tag_inventada_e_removida_em_vez_de_derrubar(scripted):
    model = scripted(structured=[_plano_cru()])

    plano = planejar_midia(model, _roteiro())

    assert plano.blocos[1].texto == "Segunda frase."
    assert plano.blocos[0].texto.startswith("<|emotion:contemplation|>")


def test_beat_orfao_e_descartado(scripted):
    cru = _plano_cru()
    cru.beats.append(Beat(id="z", bloco_id="nao-existe", prompt="perdido"))
    model = scripted(structured=[cru])

    plano = planejar_midia(model, _roteiro())

    assert len(plano.beats) == 2


def test_plano_faz_round_trip_no_disco(tmp_path, scripted):
    plano = planejar_midia(scripted(structured=[_plano_cru()]), _roteiro())

    caminho = gravar_plano(tmp_path, plano)

    assert caminho == tmp_path / "video" / "midia.json"
    assert carregar_plano(tmp_path) == plano
