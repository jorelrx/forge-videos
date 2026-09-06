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


def test_id_repetido_pelo_modelo_resolve_para_o_primeiro_bloco(scripted):
    """prompts/midia.md convida a repetir ids ("a forma exata não importa").

    Se dois blocos chegarem com o mesmo id original, o mapa não pode sobrescrever
    a primeira entrada: um beat destinado ao primeiro bloco iria silenciosamente
    parar no segundo.
    """
    cru = PlanoMidia(
        blocos=[
            BlocoNarracao(id="x", secao="Hook", texto="Primeira frase."),
            BlocoNarracao(id="x", secao="Problema", texto="Segunda frase."),
        ],
        beats=[Beat(id="i", bloco_id="x", prompt="uma ampulheta")],
    )
    model = scripted(structured=[cru])

    plano = planejar_midia(model, _roteiro())

    assert plano.beats[0].bloco_id == "b001"


def test_plano_faz_round_trip_no_disco(tmp_path, scripted):
    plano = planejar_midia(scripted(structured=[_plano_cru()]), _roteiro())

    caminho = gravar_plano(tmp_path, plano)

    assert caminho == tmp_path / "video" / "midia.json"
    assert carregar_plano(tmp_path) == plano


def test_gravar_plano_recusa_sobrescrever(tmp_path, scripted):
    """Ids de bloco são posicionais: um plano refeito renumera tudo, a regra de
    entrada-mudou do manifesto reseta quase todo item para pendente, e uma noite
    de áudio e imagem gerados vira lixo. Refazer tem que ser explícito."""
    import pytest

    from forge.agents.midia import PlanoJaExiste

    plano = planejar_midia(scripted(structured=[_plano_cru()]), _roteiro())
    caminho = gravar_plano(tmp_path, plano)

    outro = PlanoMidia(
        blocos=[BlocoNarracao(id="b001", secao="Hook", texto="Outro corte.")],
        beats=[],
    )
    with pytest.raises(PlanoJaExiste) as exc:
        gravar_plano(tmp_path, outro)

    assert str(caminho) in str(exc.value)
    assert "forcar" in str(exc.value)
    assert carregar_plano(tmp_path) == plano

    gravar_plano(tmp_path, outro, forcar=True)
    assert carregar_plano(tmp_path) == outro


def test_escrita_interrompida_nao_corrompe_o_plano(tmp_path, scripted):
    """midia.json é o artefato mais caro do run (uma chamada de LLM no fim de
    horas) e a entrada de tudo o que vem depois. Escrita direta o deixaria
    truncado se a máquina caísse no meio."""
    from unittest import mock

    import pytest

    plano = planejar_midia(scripted(structured=[_plano_cru()]), _roteiro())
    gravar_plano(tmp_path, plano)

    outro = PlanoMidia(blocos=[], beats=[])
    with mock.patch("forge.services.persistencia.os.replace",
                    side_effect=OSError("corte de energia")):
        with pytest.raises(OSError):
            gravar_plano(tmp_path, outro, forcar=True)

    assert carregar_plano(tmp_path) == plano
