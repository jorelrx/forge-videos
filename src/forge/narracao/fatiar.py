"""Corta o roteiro em blocos de narração — sem LLM, por construção.

Fatiar é operação determinística: nenhuma palavra pode ser perdida ou reescrita.
Um modelo faz isso com risco de truncar, pular ou reescrever, e foi exatamente o
que aconteceu na primeira versão: pediu-se a um 9B que fatiasse 1079 palavras e
ele devolveu 85, todas do Hook, mais beats apontando para blocos que nunca
escreveu. Aqui a cobertura é garantida porque o código só corta.
"""

from __future__ import annotations

import re

# Linha inteiramente entre parênteses: a rubrica de cena que o escritor põe no
# começo de cada seção. Descreve a imagem, não o que a voz diz.
#
# `[^)\n]*` — não DOTALL, não `.+?` — de propósito: a versão antiga usava
# `.+?` com DOTALL, e o não-guloso então cruzava linhas em branco caçando o
# primeiro `)` que fechasse QUALQUER linha seguinte, apagando toda a narração
# no meio do caminho. Consequência aceita: uma rubrica que se quebra em duas
# linhas deixa de ser reconhecida e vira narração — errado, mas visível e
# óbvio de corrigir no roteiro. O erro anterior era o oposto: silencioso e
# irrecuperável (apagava frases inteiras sem sinal nenhum). Toda rubrica do
# corpus real cabe numa linha só.
#
# `\r?$` e `\r` na classe negada: `$` sob MULTILINE não trata `\r\n` como uma
# unidade — sem isso, o `\r` de um CRLF sobra antes do `$` e a rubrica inteira
# deixa de casar. Isso não é hipotético: o texto de uma seção chega aqui
# direto do output estruturado do modelo, nunca por `Path.read_text()` — nada
# no caminho real normaliza a quebra de linha antes deste ponto.
RUBRICA_RE = re.compile(r"^[ \t]*\(([^)\n\r]*)\)[ \t]*\r?$", re.MULTILINE)

# Ênfase markdown, em dois padrões — não um só compartilhado por `_` e `*`.
# `(.+?)\1` original casava o primeiro delimitador com o PRÓXIMO IGUAL EM
# QUALQUER LUGAR do texto: em "livre_arbitrio ou o determinismo_estrito" ele
# fundia os dois underscores de palavras diferentes e colava
# "livrearbitrio"+"determinismoestrito" — reescrita silenciosa, invisível pra
# contagem de palavras. `[^*\n]` / `[^_\n]` impedem cruzar linha, e os
# lookarounds de fronteira de palavra em `_..._` garantem que só um underscore
# ladeado por espaço/pontuação (ênfase real) é tocado — `livre_arbitrio`, com
# `_` colado a letras dos dois lados, nunca casa.
_ASTERISCO_RE = re.compile(r"(\*\*|\*)([^*\n]+?)\1")
_SUBLINHADO_RE = re.compile(r"(?<!\w)_([^_\n]+?)_(?!\w)")
REFERENCIA_LEGADA_RE = re.compile(
    r"\[([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+|[0-9]+(?:\.[0-9]+)*(?:\.f[0-9]+)?)\]"
)

# Abreviações que terminam em ponto sem terminar a frase. Cortar depois delas
# partiria a narração no meio de uma oração.
_ABREVIACOES = ("Sr.", "Sra.", "Srta.", "Dr.", "Dra.", "Prof.", "St.", "etc.")
_MARCA = "\x00"

# Fim de frase: pontuação final (com reticências tratadas como uma só) seguida
# de espaço e de algo que começa frase nova.
_FIM_FRASE_RE = re.compile(r"(?<=[.!?…])(?<!\.\.)\s+(?=[^\s])")

# ~2,5 palavras por segundo é a cadência medida do higgs nesta voz. Mora aqui,
# e não em quem pede beats, porque é propriedade da NARRAÇÃO: é o que converte
# um alvo em segundos para um alvo em palavras, que é a única unidade que o
# fatiador entende. Serve para dimensionar blocos e estimar quantas imagens uma
# seção comporta, não para cronometrar nada: a duração real sai das métricas do
# TTS, no manifesto.
PALAVRAS_POR_SEGUNDO = 2.5


def extrair_rubrica(conteudo: str) -> str:
    """A rubrica de cena da seção, sem os parênteses. Vazio se não houver.

    Não é narração, mas é uma descrição visual escrita pelo autor — serve de
    semente para os prompts de imagem daquela seção.
    """
    achado = RUBRICA_RE.search(conteudo)
    return achado.group(1).strip() if achado else ""


def texto_narravel(conteudo: str) -> str:
    """Texto falado limpo; marcadores antigos não verificados são removidos."""
    sem_rubrica = RUBRICA_RE.sub("", conteudo)
    sem_caminhos = REFERENCIA_LEGADA_RE.sub("", sem_rubrica)
    sem_asterisco = _ASTERISCO_RE.sub(r"\2", sem_caminhos)
    sem_enfase = _SUBLINHADO_RE.sub(r"\1", sem_asterisco)
    return " ".join(sem_enfase.split())


def dividir_frases(texto: str) -> list[str]:
    protegido = texto
    for i, abrev in enumerate(_ABREVIACOES):
        protegido = protegido.replace(abrev, f"{_MARCA}{i}{_MARCA}")

    frases = [f.strip() for f in _FIM_FRASE_RE.split(protegido) if f.strip()]

    restauradas = []
    for frase in frases:
        for i, abrev in enumerate(_ABREVIACOES):
            frase = frase.replace(f"{_MARCA}{i}{_MARCA}", abrev)
        restauradas.append(frase)
    return restauradas


def fatiar(
    conteudo: str, *, max_frases: int = 3, alvo_palavras: int = 35
) -> list[str]:
    """Blocos de 1 a `max_frases` frases, mirando `alvo_palavras` por bloco.

    O alvo é teto flexível, não corte: uma frase que sozinha já o excede vira um
    bloco só dela, porque quebrar no meio de uma frase é o único jeito de o TTS
    soar errado sem que ninguém perceba no texto.
    """
    frases = dividir_frases(texto_narravel(conteudo))
    blocos: list[str] = []
    atual: list[str] = []
    palavras = 0

    for frase in frases:
        n = len(frase.split())
        cheio = len(atual) >= max_frases or (atual and palavras + n > alvo_palavras)
        if cheio:
            blocos.append(" ".join(atual))
            atual, palavras = [], 0
        atual.append(frase)
        palavras += n

    if atual:
        blocos.append(" ".join(atual))
    return blocos
