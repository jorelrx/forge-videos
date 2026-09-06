import pytest

from forge.narracao.tags import (
    TAGS_INLINE,
    TAGS_SENTENCA,
    TagInvalida,
    sanear_texto,
    validar_texto,
)


def test_catalogo_tem_as_43_tags():
    total = sum(len(v) for v in TAGS_SENTENCA.values())
    total += sum(len(v) for v in TAGS_INLINE.values())
    assert total == 43


def test_texto_valido_passa():
    validar_texto("<|emotion:contemplation|><|prosody:speed_slow|>Olá.<|prosody:long_pause|>")


def test_texto_sem_tag_passa():
    validar_texto("Uma frase comum, sem nenhuma tag.")


def test_categoria_desconhecida_estoura():
    with pytest.raises(TagInvalida) as exc:
        validar_texto("<|mood:happy|>Olá.")
    assert "mood" in str(exc.value)


def test_nome_desconhecido_estoura_com_sugestao():
    with pytest.raises(TagInvalida) as exc:
        validar_texto("<|emotion:contemplacion|>Olá.")
    assert "contemplation" in str(exc.value)


def test_sanear_remove_a_tag_invalida_e_preserva_a_valida():
    texto, removidas = sanear_texto("<|emotion:contemplation|><|mood:happy|>Olá.")

    assert texto == "<|emotion:contemplation|>Olá."
    assert removidas == ["<|mood:happy|>"]
    validar_texto(texto)


def test_sanear_texto_limpo_nao_muda_nada():
    texto, removidas = sanear_texto("<|emotion:awe|>Olá.")

    assert removidas == []
    assert texto == "<|emotion:awe|>Olá."
