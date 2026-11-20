"""Gates determinísticos da embalagem do vídeo.

Como no gate do roteiro, o modelo não tem a palavra final: os limites abaixo são
regra do YouTube ou do canal e são conferidos em texto puro.

- Título: o YouTube corta por volta de 60 caracteres na tela do celular. Acima
  de 70 nem o desktop mostra inteiro.
- Capítulos: o YouTube só os reconhece com o primeiro em 00:00, ao menos três e
  cada um com 10 segundos ou mais.
- Descrição: 5.000 caracteres; só os ~150 primeiros aparecem antes do "mais".
- Tags: 500 caracteres somando os separadores.
- Hashtags: as três primeiras sobem para cima do título; excesso polui.
"""

from __future__ import annotations

import re

from forge.domain.embalagem import Embalagem
from forge.services.qualidade_roteiro import GateFinding, ScriptGateReport

TITULOS_ESPERADOS = 3
TITULO_MAXIMO = 70
TITULO_RECOMENDADO = 60
THUMBNAIL_PALAVRAS_MAXIMO = 4
CAPITULOS_MINIMO = 3
CAPITULO_SEGUNDOS_MINIMO = 10
DESCRICAO_MAXIMO = 5000
ABERTURA_MAXIMO = 150
TAGS_MAXIMO = 500
HASHTAGS_MAXIMO = 3

# Palavra de 4+ letras inteira em maiúsculas. Siglas curtas (IA, EUA) não contam.
_PALAVRA_GRITADA = re.compile(r"\b[A-ZÀ-Ý]{4,}\b")


def _achado(code: str, message: str, *, severity: str = "grave", **details) -> GateFinding:
    return GateFinding(code=code, message=message, severity=severity, details=details)


def _chave(texto: str) -> str:
    return " ".join(texto.casefold().split())


def conferir_embalagem(embalagem: Embalagem) -> ScriptGateReport:
    achados: list[GateFinding] = []
    titulos = [titulo.texto.strip() for titulo in embalagem.titulos]

    if len(titulos) != TITULOS_ESPERADOS:
        achados.append(_achado(
            "titulos_quantidade", "São necessárias exatamente três opções de título",
            recebidos=len(titulos),
        ))
    if len({_chave(titulo) for titulo in titulos}) != len(titulos):
        achados.append(_achado("titulos_repetidos", "Há títulos repetidos"))
    for titulo in titulos:
        if not titulo:
            achados.append(_achado("titulo_vazio", "Título vazio"))
            continue
        if len(titulo) > TITULO_MAXIMO:
            achados.append(_achado(
                "titulo_longo", "Título acima de 70 caracteres",
                titulo=titulo, caracteres=len(titulo),
            ))
        elif len(titulo) > TITULO_RECOMENDADO:
            achados.append(_achado(
                "titulo_longo_aviso", "Título acima de 60 caracteres: corta no celular",
                severity="aviso", titulo=titulo, caracteres=len(titulo),
            ))
        # Primeiro caractere que não é pontuação: título que abre com número
        # ("3 perguntas...") ou aspas seguidas de maiúscula está certo.
        inicial = next((c for c in titulo if c.isalnum()), "")
        if inicial.isalpha() and inicial.islower():
            achados.append(_achado(
                "titulo_minusculo", "Título precisa começar com letra maiúscula",
                titulo=titulo,
            ))
        if len(_PALAVRA_GRITADA.findall(titulo)) > 1:
            achados.append(_achado(
                "titulo_gritado", "Título com mais de uma palavra em caixa alta",
                titulo=titulo,
            ))

    texto_thumb = embalagem.thumbnail.texto.strip()
    palavras_thumb = len(texto_thumb.split())
    if not 1 <= palavras_thumb <= THUMBNAIL_PALAVRAS_MAXIMO:
        achados.append(_achado(
            "thumbnail_texto", "Texto da thumbnail precisa ter de 1 a 4 palavras",
            palavras=palavras_thumb,
        ))
    if texto_thumb and _chave(texto_thumb) in {_chave(titulo) for titulo in titulos}:
        achados.append(_achado(
            "thumbnail_repete_titulo", "Texto da thumbnail repete um título",
        ))
    if not embalagem.thumbnail.prompt.strip():
        achados.append(_achado("thumbnail_sem_prompt", "Thumbnail sem prompt de imagem"))

    inicios = [capitulo.inicio_segundos for capitulo in embalagem.capitulos]
    if len(inicios) < CAPITULOS_MINIMO:
        achados.append(_achado(
            "capitulos_insuficientes", "O YouTube exige ao menos três capítulos",
            recebidos=len(inicios),
        ))
    if inicios and inicios[0] != 0:
        achados.append(_achado(
            "capitulo_inicial", "O primeiro capítulo precisa começar em 00:00",
            inicio=inicios[0],
        ))
    if any(
        depois - antes < CAPITULO_SEGUNDOS_MINIMO
        for antes, depois in zip(inicios, inicios[1:])
    ):
        achados.append(_achado(
            "capitulo_curto", "Capítulo com menos de 10 segundos ou fora de ordem",
        ))

    descricao = embalagem.descricao
    if not descricao.strip():
        achados.append(_achado("descricao_vazia", "Descrição vazia"))
    else:
        if len(descricao) > DESCRICAO_MAXIMO:
            achados.append(_achado(
                "descricao_longa", "Descrição acima de 5.000 caracteres",
                caracteres=len(descricao),
            ))
        abertura = descricao.splitlines()[0]
        if len(abertura) > ABERTURA_MAXIMO:
            achados.append(_achado(
                "descricao_abertura_longa",
                "Primeira linha da descrição acima de 150 caracteres",
                caracteres=len(abertura),
            ))
    if not embalagem.fontes:
        # O diferencial do canal é a fonte visível. Descrição sem fonte indica
        # roteiro sem citação rastreável, que não deveria ter chegado aqui.
        achados.append(_achado(
            "descricao_sem_fontes", "Descrição sem nenhuma fonte do acervo",
        ))

    tamanho_tags = sum(len(tag) for tag in embalagem.tags) + max(len(embalagem.tags) - 1, 0)
    if tamanho_tags > TAGS_MAXIMO:
        achados.append(_achado(
            "tags_longas", "Tags acima de 500 caracteres", caracteres=tamanho_tags,
        ))
    if len(embalagem.hashtags) > HASHTAGS_MAXIMO:
        achados.append(_achado(
            "hashtags_excesso", "Mais de três hashtags", recebidas=len(embalagem.hashtags),
        ))
    if not embalagem.comentario_fixado.strip().endswith("?"):
        achados.append(_achado(
            "comentario_sem_pergunta",
            "Comentário fixado não é uma pergunta ao público", severity="aviso",
        ))

    graves = sum(achado.serious for achado in achados)
    return ScriptGateReport(
        approved=graves == 0,
        serious_count=graves,
        findings=achados,
        metrics={"finding_count": len(achados), "serious_count": graves},
    )


__all__ = ["conferir_embalagem"]
