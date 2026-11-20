"""Gates determinísticos da embalagem do vídeo.

Título, thumbnail e descrição decidem o clique; os limites aqui são os do
YouTube (capítulos, tamanho da descrição, tags) e os do canal (sem grito, sem
título que não cabe na tela do celular).
"""
import pytest

from forge.domain.embalagem import (
    Capitulo, Embalagem, ThumbnailProposta, TituloProposto,
)
from forge.services.qualidade_embalagem import conferir_embalagem

TITULO_1 = "Por que o aplauso não prova que você está certo"


def _titulos(*textos):
    return [TituloProposto(texto=texto, angulo="pergunta") for texto in textos]


def _capitulos(*inicios):
    return [
        Capitulo(secao=f"S{i}", titulo=f"Parte {i}", inicio_segundos=inicio)
        for i, inicio in enumerate(inicios)
    ]


def _valida(**mudancas) -> Embalagem:
    base = Embalagem(
        titulos=_titulos(
            TITULO_1,
            "O erro de quem sempre segue a regra",
            "Como saber se uma regra merece obediência",
        ),
        thumbnail=ThumbnailProposta(texto="O aplauso mente", prompt="a lone figure on a stage"),
        descricao="Todos aprovam. E se ainda assim estiver errado?\n\nResumo do vídeo.",
        capitulos=_capitulos(0, 30, 95),
        tags=["filosofia", "ética", "nietzsche"],
        hashtags=["#filosofia"],
        comentario_fixado="Você elogiaria igualmente os dois?",
        fontes=["Nietzsche — Beyond Good and Evil"],
    )
    return base.model_copy(update=mudancas)


def test_embalagem_valida_passa():
    report = conferir_embalagem(_valida())

    assert report.approved, report.findings
    assert report.findings == []


@pytest.mark.parametrize("mudanca, codigo", [
    (dict(titulos=_titulos(TITULO_1, "Outro título")), "titulos_quantidade"),
    (dict(titulos=_titulos(TITULO_1, TITULO_1.upper().capitalize(), "Terceiro")), "titulos_repetidos"),
    (dict(titulos=_titulos(TITULO_1, "Segundo", "x" * 71)), "titulo_longo"),
    (dict(titulos=_titulos(TITULO_1, "Segundo", "O SEGREDO QUE NINGUÉM conta")), "titulo_gritado"),
    (dict(titulos=_titulos(TITULO_1, "Segundo", "  ")), "titulo_vazio"),
    (dict(thumbnail=ThumbnailProposta(texto="cinco palavras são demais aqui", prompt="p")), "thumbnail_texto"),
    (dict(thumbnail=ThumbnailProposta(texto="", prompt="p")), "thumbnail_texto"),
    (dict(thumbnail=ThumbnailProposta(texto=TITULO_1.upper(), prompt="p")), "thumbnail_repete_titulo"),
    (dict(thumbnail=ThumbnailProposta(texto="O aplauso mente", prompt="  ")), "thumbnail_sem_prompt"),
    (dict(capitulos=_capitulos(0, 30)), "capitulos_insuficientes"),
    (dict(capitulos=_capitulos(5, 30, 95)), "capitulo_inicial"),
    (dict(capitulos=_capitulos(0, 30, 38)), "capitulo_curto"),
    (dict(capitulos=_capitulos(0, 95, 30)), "capitulo_curto"),
    (dict(descricao="x" * 5001), "descricao_longa"),
    (dict(descricao="y" * 151 + "\nresto"), "descricao_abertura_longa"),
    (dict(descricao=" "), "descricao_vazia"),
    (dict(fontes=[]), "descricao_sem_fontes"),
    (dict(tags=["t" * 60] * 9), "tags_longas"),
    (dict(hashtags=["#a", "#b", "#c", "#d"]), "hashtags_excesso"),
])
def test_gate_reprova(mudanca, codigo):
    report = conferir_embalagem(_valida(**mudanca))

    assert not report.approved
    assert codigo in report.codes


def test_titulo_entre_61_e_70_caracteres_e_so_aviso():
    report = conferir_embalagem(_valida(titulos=_titulos(TITULO_1, "Segundo", "X" + "x" * 64)))

    assert report.approved
    assert [f.code for f in report.findings] == ["titulo_longo_aviso"]


def test_uma_palavra_em_caixa_alta_nao_e_grito():
    report = conferir_embalagem(_valida(titulos=_titulos(TITULO_1, "Segundo", "O que a IA não decide por você")))

    assert report.approved


def test_tags_no_limite_de_500_caracteres_passam():
    # 9 tags de 54 caracteres + 8 separadores = 494.
    assert conferir_embalagem(_valida(tags=["t" * 54] * 9)).approved


def test_comentario_sem_pergunta_e_aviso():
    report = conferir_embalagem(_valida(comentario_fixado="Pense nisso."))

    assert report.approved
    assert [f.code for f in report.findings] == ["comentario_sem_pergunta"]


def test_titulo_todo_em_minusculas_reprova():
    """Na run real o modelo leu "sem caixa alta" como "tudo em minúsculas"."""
    report = conferir_embalagem(_valida(titulos=_titulos(
        TITULO_1, "Segundo", "por que continuo conferindo o que já fiz?",
    )))

    assert "titulo_minusculo" in report.codes


def test_titulo_que_abre_com_aspas_ou_numero_nao_e_minusculo():
    report = conferir_embalagem(_valida(titulos=_titulos(
        TITULO_1, "“Conhece-te”: o que a frase esconde", "3 perguntas antes de obedecer",
    )))

    assert report.approved
