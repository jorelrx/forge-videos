import pytest

from forge.agents.midia import propor_beats
from forge.domain.midia import BeatProposto, BeatsDaSecao, BlocoNarracao


def _blocos():
    return [
        BlocoNarracao(id="b001", secao="Hook", texto="Primeira frase do gancho."),
        BlocoNarracao(id="b002", secao="Hook", texto="Segunda frase do gancho."),
    ]


def test_beats_apontam_para_blocos_da_secao(scripted):
    model = scripted(structured=[BeatsDaSecao(beats=[
        BeatProposto(bloco_id="b001", prompt="a hand on a steering wheel"),
        BeatProposto(bloco_id="b002", prompt="a road stretching to the horizon"),
    ])])

    beats = propor_beats(model, "Hook", "Cena: um carro", _blocos(), alvo_segundos=15)

    assert [b.bloco_id for b in beats] == ["b001", "b002"]
    assert beats[0].prompt == "a hand on a steering wheel"


def test_beat_para_bloco_de_fora_da_secao_e_descartado(scripted):
    """O modelo só recebeu os blocos desta seção; citar outro é invenção."""
    model = scripted(structured=[BeatsDaSecao(beats=[
        BeatProposto(bloco_id="b001", prompt="ok"),
        BeatProposto(bloco_id="b999", prompt="inventado"),
    ])])

    beats = propor_beats(model, "Hook", "", _blocos(), alvo_segundos=15)

    assert [b.bloco_id for b in beats] == ["b001"]


def test_secao_sem_beat_proposto_ganha_um_de_fallback(scripted):
    """Uma seção sem imagem deixaria a tela congelada por minutos."""
    model = scripted(structured=[BeatsDaSecao(beats=[])])

    beats = propor_beats(model, "Hook", "Cena: um carro na estrada", _blocos(),
                         alvo_segundos=15)

    assert len(beats) == 1
    assert beats[0].bloco_id == "b001"
    assert "carro" in beats[0].prompt


def test_fallback_sem_rubrica_usa_o_nome_da_secao(scripted):
    model = scripted(structured=[BeatsDaSecao(beats=[])])

    beats = propor_beats(model, "Problema", "", _blocos(), alvo_segundos=15)

    assert len(beats) == 1
    assert "Problema" in beats[0].prompt


def test_prompt_vazio_nao_vira_beat(scripted):
    model = scripted(structured=[BeatsDaSecao(beats=[
        BeatProposto(bloco_id="b001", prompt="   "),
        BeatProposto(bloco_id="b002", prompt="uma estrada"),
    ])])

    beats = propor_beats(model, "Hook", "", _blocos(), alvo_segundos=15)

    assert [b.prompt for b in beats] == ["uma estrada"]
