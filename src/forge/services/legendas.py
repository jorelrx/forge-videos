"""Legenda do vídeo: o texto falado, repartido em deixas com tempo.

A legenda sai dos mesmos blocos que o TTS lê e da mesma linha do tempo que os
cartões de fonte e os capítulos usam (`linha_tempo`), para que nunca discordem
do áudio. Nada aqui chama modelo nem ffmpeg: é conta sobre texto e segundos.

Os tempos dentro de um bloco são uma estimativa — o bloco é repartido entre as
deixas pela contagem de caracteres, porque só existe a duração do WAV inteiro,
não o instante de cada palavra. O erro fica confinado ao bloco: a primeira deixa
começa e a última termina exatamente onde o bloco começa e termina, então ele
não se acumula ao longo do vídeo.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from forge.domain.midia import BlocoNarracao
from forge.narracao.fatiar import dividir_frases, texto_narravel
from forge.narracao.tags import TAG_SOLTA_RE
from forge.services.linha_tempo import TrechoTempo

LINHA_MAXIMO = 42
LINHAS_MAXIMO = 2
DEIXA_MINIMO_SEGUNDOS = 1.0

# Cabe numa deixa o que cabe em LINHAS_MAXIMO linhas cheias.
_DEIXA_MAXIMO = LINHA_MAXIMO * LINHAS_MAXIMO

# Caracteres que um player de SRT interpreta como marcação (`<i>`, `{\an8}`) ou
# que a nossa própria sintaxe reserva (`-->`, barra invertida). Viram espaço,
# não somem: a palavra colada ao lado continua sendo palavra.
_MARCACAO_RE = re.compile(r"[{}<>\\]")


class Deixa(BaseModel):
    inicio: float
    fim: float
    texto: str  # até duas linhas, separadas por "\n"


def _compactar(texto: str) -> str:
    return " ".join(texto.split())


def _falado(texto: str) -> str:
    """O que o narrador diz: sem tag de TTS, rubrica, ênfase nem marcação.

    As tags saem primeiro porque `<|emotion:awe|>` é instrução para o modelo de
    voz, não fala — legendá-la mostraria código na tela do espectador.
    """
    sem_tags = TAG_SOLTA_RE.sub(" ", texto)
    return _compactar(_MARCACAO_RE.sub(" ", texto_narravel(sem_tags)))


def _quebrar_linhas(texto: str) -> list[str] | None:
    """Parte o texto em até `LINHAS_MAXIMO` linhas de `LINHA_MAXIMO`, ou None.

    Escolhe o corte que mais equilibra as duas linhas: legenda com uma linha
    cheia e outra com uma palavra só é difícil de ler. Palavra única maior que
    a linha é a exceção aceita — não há onde cortá-la sem inventar hifenização,
    e esconder letras seria pior do que estourar a margem.
    """
    palavras = texto.split()
    if not palavras:
        return []
    if len(palavras) == 1:
        return [palavras[0]]
    if len(texto) <= LINHA_MAXIMO:
        return [texto]
    melhor: tuple[int, list[str]] | None = None
    for i in range(1, len(palavras)):
        a, b = " ".join(palavras[:i]), " ".join(palavras[i:])
        if len(a) > LINHA_MAXIMO or len(b) > LINHA_MAXIMO:
            continue
        pior = max(len(a), len(b))
        if melhor is None or pior < melhor[0]:
            melhor = (pior, [a, b])
    return melhor[1] if melhor else None


def _cabe(texto: str) -> bool:
    return _quebrar_linhas(texto) is not None


def _cortar(texto: str) -> list[str]:
    """Divide até cada pedaço caber numa deixa, preferindo vírgula a espaço.

    Corta perto do meio para os pedaços saírem parecidos; vírgula vence porque
    é onde o narrador respira e onde a frase se parte sem perder o sentido.
    """
    if _cabe(texto):
        return [texto]
    meio = len(texto) / 2
    virgulas = [
        m.end() for m in re.finditer(r",\s+", texto)
        if 0 < m.end() < len(texto)
    ]
    posicoes = virgulas or [m.end() for m in re.finditer(r"\s+", texto)]
    if not posicoes:
        return [texto]  # palavra única maior que a linha: exceção aceita
    corte = min(posicoes, key=lambda p: abs(p - meio))
    esquerda, direita = texto[:corte].strip(), texto[corte:].strip()
    return _cortar(esquerda) + _cortar(direita)


def _fundir_curtas(unidades: list[str], duracao: float) -> list[str]:
    """Junta vizinhas até cada deixa durar `DEIXA_MINIMO_SEGUNDOS`.

    Legenda que pisca por menos de um segundo não dá para ler. A fusão só
    acontece quando o texto junto ainda cabe em `LINHAS_MAXIMO` linhas: entre
    estourar o limite de linhas e deixar uma deixa curta, fica a curta — o
    limite de linhas é o que garante que o texto não cubra a imagem.
    """
    unidades = list(unidades)
    while len(unidades) > 1:
        total = sum(len(u) for u in unidades)
        curtas = [
            i for i, u in enumerate(unidades)
            if duracao * len(u) / total < DEIXA_MINIMO_SEGUNDOS
        ]
        candidatos: list[tuple[int, int]] = []  # (comprimento da fusão, índice esquerdo)
        for i in curtas:
            for esq in (i - 1, i):
                if 0 <= esq < len(unidades) - 1:
                    junto = f"{unidades[esq]} {unidades[esq + 1]}"
                    if _cabe(junto):
                        candidatos.append((len(junto), esq))
        if not candidatos:
            break
        _, esq = min(candidatos)
        unidades[esq:esq + 2] = [f"{unidades[esq]} {unidades[esq + 1]}"]
    return unidades


def _deixas_do_bloco(texto: str, inicio: float, fim: float) -> list[Deixa]:
    unidades: list[str] = []
    for frase in dividir_frases(texto):
        unidades.extend(_cortar(frase))
    if not unidades or fim <= inicio:
        return []
    duracao = fim - inicio
    unidades = _fundir_curtas(unidades, duracao)

    total = sum(len(u) for u in unidades)
    deixas: list[Deixa] = []
    acumulado = 0
    cursor = inicio
    for i, unidade in enumerate(unidades):
        acumulado += len(unidade)
        # A última termina no fim exato do bloco; as outras, onde a proporção
        # de caracteres manda. Arredondar em ms mantém o SRT sem resto de ponto
        # flutuante, e usar o fim anterior como início garante que não haja
        # sobreposição nem buraco dentro do bloco.
        proximo = fim if i == len(unidades) - 1 else round(
            inicio + duracao * acumulado / total, 3
        )
        linhas = _quebrar_linhas(unidade) or [unidade]
        deixas.append(Deixa(inicio=cursor, fim=proximo, texto="\n".join(linhas)))
        cursor = proximo
    return deixas


def gerar_deixas(
    blocos: list[BlocoNarracao], tempos: list[TrechoTempo],
) -> list[Deixa]:
    """Deixas de todos os blocos, na ordem da narração.

    Bloco sem trecho na linha do tempo é pulado: sem tempo não há onde pôr a
    legenda, e inventar um deslocaria as seguintes.
    """
    por_id = {t.bloco_id: t for t in tempos}
    deixas: list[Deixa] = []
    for bloco in blocos:
        trecho = por_id.get(bloco.id)
        if trecho is None:
            continue
        deixas.extend(_deixas_do_bloco(_falado(bloco.texto), trecho.inicio, trecho.fim))
    return deixas


def _timestamp(segundos: float) -> str:
    total_ms = max(0, round(segundos * 1000))
    horas, resto = divmod(total_ms, 3_600_000)
    minutos, resto = divmod(resto, 60_000)
    segs, ms = divmod(resto, 1000)
    return f"{horas:02d}:{minutos:02d}:{segs:02d},{ms:03d}"


def _linhas_seguras(texto: str) -> list[str]:
    """Linhas não vazias e sem marcação.

    Linha em branco encerra a deixa no SRT; `<`/`{` viram formatação no player;
    `-->` dentro do texto confundiria quem lê o arquivo de volta. Por isso o
    formatador se defende mesmo de uma `Deixa` montada fora de `gerar_deixas`.
    """
    linhas = (_compactar(_MARCACAO_RE.sub(" ", linha)) for linha in texto.splitlines())
    return [linha for linha in linhas if linha]


def formatar_srt(deixas: list[Deixa]) -> str:
    """SRT: numeração a partir de 1, tempos `HH:MM:SS,mmm`, linha em branco entre deixas."""
    cortes = []
    for n, deixa in enumerate(deixas, start=1):
        linhas = _linhas_seguras(deixa.texto)
        corpo = "\n".join(linha.replace("-->", "->") for linha in linhas)
        cortes.append(
            f"{n}\n{_timestamp(deixa.inicio)} --> {_timestamp(deixa.fim)}\n{corpo}\n"
        )
    return "\n".join(cortes)


def conferir_deixas(deixas: list[Deixa]) -> list[str]:
    """Problemas que fariam o player errar a legenda; lista vazia = ok."""
    problemas: list[str] = []
    for i, d in enumerate(deixas, start=1):
        linhas = [linha for linha in d.texto.splitlines() if linha.strip()]
        if not linhas:
            problemas.append(f"deixa {i} vazia")
        if d.fim <= d.inicio:
            problemas.append(
                f"deixa {i} com duração não positiva ({d.inicio:.3f} -> {d.fim:.3f})"
            )
        if len(linhas) > LINHAS_MAXIMO:
            problemas.append(f"deixa {i} com {len(linhas)} linhas (máximo {LINHAS_MAXIMO})")
        for linha in linhas:
            # Palavra única maior que a linha é a exceção documentada.
            if len(linha) > LINHA_MAXIMO and len(linha.split()) > 1:
                problemas.append(
                    f"deixa {i} com linha de {len(linha)} caracteres (máximo {LINHA_MAXIMO})"
                )
        if i > 1:
            anterior = deixas[i - 2]
            if d.inicio < anterior.inicio:
                problemas.append(f"deixa {i} fora de ordem: começa antes da deixa {i - 1}")
            elif d.inicio < anterior.fim:
                problemas.append(f"deixa {i} se sobrepõe à deixa {i - 1}")
    return problemas


__all__ = [
    "DEIXA_MINIMO_SEGUNDOS", "Deixa", "LINHAS_MAXIMO", "LINHA_MAXIMO",
    "conferir_deixas", "formatar_srt", "gerar_deixas",
]
