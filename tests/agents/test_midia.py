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
    # Ids são atribuídos depois, pelo caller, que sabe a contagem corrida no
    # roteiro inteiro. Um id preenchido aqui corromperia essa renumeração.
    assert all(b.id == "" for b in beats)


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
    assert beats[0].id == ""


def test_fallback_dispara_quando_todos_os_beats_propostos_sao_invalidos(scripted):
    """O fallback é decidido pela lista pós-filtro, não pela lista crua do
    modelo: um beat fora da seção e outro sem prompt somem no filtro, e a
    seção fica tão sem imagem quanto se o modelo não tivesse proposto nada.
    """
    model = scripted(structured=[BeatsDaSecao(beats=[
        BeatProposto(bloco_id="b999", prompt="fora da seção"),
        BeatProposto(bloco_id="b001", prompt="   "),
    ])])

    beats = propor_beats(model, "Hook", "Cena: um carro na estrada", _blocos(),
                         alvo_segundos=15)

    assert len(beats) == 1
    assert beats[0].bloco_id == "b001"


def test_beat_duplicado_no_mesmo_bloco_e_descartado(scripted):
    """Dois beats no mesmo bloco não têm como ser distinguidos no tempo — um
    Beat só ancora em um bloco, então dois nele competem pelo mesmo instante
    enquanto outro bloco fica sem imagem nenhuma.
    """
    model = scripted(structured=[BeatsDaSecao(beats=[
        BeatProposto(bloco_id="b001", prompt="primeira proposta"),
        BeatProposto(bloco_id="b001", prompt="segunda proposta, mesmo bloco"),
    ])])

    beats = propor_beats(model, "Hook", "", _blocos(), alvo_segundos=15)

    assert len(beats) == 1
    assert beats[0].prompt == "primeira proposta"


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
