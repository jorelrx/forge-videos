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


def _roteiro_de_duas_secoes():
    from forge.domain.models import Roteiro, Secao

    return Roteiro(
        tema="livre-arbítrio",
        tese="a vontade é sentida, não observada",
        secoes=[
            Secao(nome="Hook", conteudo=(
                "(Cena: um carro na estrada.)\n\n"
                "Primeira frase do gancho. Segunda frase do gancho."
            )),
            Secao(nome="Problema", conteudo="O problema não é físico. É linguístico."),
        ],
    )


def test_plano_cobre_todas_as_secoes(scripted):
    from forge.agents.midia import planejar_midia

    model = scripted(structured=[
        BeatsDaSecao(beats=[BeatProposto(bloco_id="b001", prompt="a car")]),
        BeatsDaSecao(beats=[BeatProposto(bloco_id="b002", prompt="a scale")]),
    ])

    plano = planejar_midia(model, _roteiro_de_duas_secoes())

    assert {b.secao for b in plano.blocos} == {"Hook", "Problema"}
    assert [b.id for b in plano.blocos] == ["b001", "b002"]
    assert [i.id for i in plano.beats] == ["i001", "i002"]


def test_nenhuma_palavra_do_roteiro_se_perde_no_plano(scripted):
    """A trava do plano inteiro: o que a voz diz tem de ser o roteiro inteiro."""
    from forge.agents.midia import planejar_midia
    from forge.narracao.fatiar import texto_narravel

    roteiro = _roteiro_de_duas_secoes()
    model = scripted(structured=[
        BeatsDaSecao(beats=[BeatProposto(bloco_id="b001", prompt="a car")]),
        BeatsDaSecao(beats=[BeatProposto(bloco_id="b002", prompt="a scale")]),
    ])

    plano = planejar_midia(model, roteiro)

    esperado = " ".join(texto_narravel(s.conteudo) for s in roteiro.secoes).split()
    assert " ".join(b.texto for b in plano.blocos).split() == esperado


def test_rubrica_nunca_entra_na_narracao(scripted):
    from forge.agents.midia import planejar_midia

    model = scripted(structured=[
        BeatsDaSecao(beats=[BeatProposto(bloco_id="b001", prompt="a car")]),
        BeatsDaSecao(beats=[BeatProposto(bloco_id="b002", prompt="a scale")]),
    ])

    plano = planejar_midia(model, _roteiro_de_duas_secoes())

    assert all("Cena:" not in b.texto for b in plano.blocos)


def test_cobertura_insuficiente_estoura(scripted, monkeypatch):
    """Se um dia o fatiador regredir, o plano falha alto em vez de narrar 8%.

    É a lição do plano gerado por LLM: 85 palavras de 1079, todos os itens do
    manifesto marcados `ok`, e ninguém percebendo.
    """
    import forge.agents.midia as midia_mod
    from forge.agents.midia import CoberturaInsuficiente, planejar_midia

    monkeypatch.setattr(midia_mod, "fatiar", lambda conteudo, **kw: ["só isto"])
    model = scripted(structured=[
        BeatsDaSecao(beats=[BeatProposto(bloco_id="b001", prompt="a car")]),
        BeatsDaSecao(beats=[BeatProposto(bloco_id="b002", prompt="a scale")]),
    ])

    with pytest.raises(CoberturaInsuficiente):
        planejar_midia(model, _roteiro_de_duas_secoes())


def test_secao_so_com_rubrica_nao_gera_bloco_nem_chamada(scripted):
    from forge.agents.midia import planejar_midia
    from forge.domain.models import Roteiro, Secao

    roteiro = Roteiro(tema="t", tese="t", secoes=[
        Secao(nome="Hook", conteudo="(Cena: nada é dito.)"),
        Secao(nome="Problema", conteudo="Uma frase."),
    ])
    # Uma única resposta na fila: se o agente chamar o modelo para a seção sem
    # texto, o modelo falso estoura.
    model = scripted(structured=[
        BeatsDaSecao(beats=[BeatProposto(bloco_id="b001", prompt="a scale")]),
    ])

    plano = planejar_midia(model, roteiro)

    assert [b.secao for b in plano.blocos] == ["Problema"]
