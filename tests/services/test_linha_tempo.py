"""Linha do tempo da narração: onde cada bloco começa e termina no vídeo."""
import pytest

from forge.domain.midia import BlocoNarracao
from forge.services.linha_tempo import inicio_das_secoes, linha_do_tempo


def _bloco(id_, secao):
    return BlocoNarracao(id=id_, secao=secao, texto="Texto.")


BLOCOS = [_bloco("b1", "Gancho"), _bloco("b2", "Gancho"), _bloco("b3", "Estake")]


def test_blocos_se_acumulam_na_ordem_recebida():
    tempos = linha_do_tempo(BLOCOS, {"b1": 2.0, "b2": 3.5, "b3": 1.25})

    assert [(t.bloco_id, t.inicio, t.fim) for t in tempos] == [
        ("b1", 0.0, 2.0), ("b2", 2.0, 5.5), ("b3", 5.5, 6.75),
    ]
    assert [t.secao for t in tempos] == ["Gancho", "Gancho", "Estake"]


def test_bloco_sem_duracao_levanta():
    with pytest.raises(KeyError):
        linha_do_tempo(BLOCOS, {"b1": 2.0})


def test_inicio_de_cada_secao_e_o_do_primeiro_bloco():
    tempos = linha_do_tempo(BLOCOS, {"b1": 2.0, "b2": 3.5, "b3": 1.25})

    assert inicio_das_secoes(tempos) == {"Gancho": 0.0, "Estake": 5.5}


def test_sem_blocos_nao_ha_linha():
    assert linha_do_tempo([], {}) == []
    assert inicio_das_secoes([]) == {}
