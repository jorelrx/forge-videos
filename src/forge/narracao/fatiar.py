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
RUBRICA_RE = re.compile(r"^\s*\((.+?)\)\s*$", re.MULTILINE | re.DOTALL)

# Ênfase markdown. O asterisco não pode chegar ao TTS; a palavra sim.
_ENFASE_RE = re.compile(r"(\*\*|\*|_)(.+?)\1", re.DOTALL)

# Abreviações que terminam em ponto sem terminar a frase. Cortar depois delas
# partiria a narração no meio de uma oração.
_ABREVIACOES = ("Sr.", "Sra.", "Srta.", "Dr.", "Dra.", "Prof.", "St.", "etc.")
_MARCA = "\x00"

# Fim de frase: pontuação final (com reticências tratadas como uma só) seguida
# de espaço e de algo que começa frase nova.
_FIM_FRASE_RE = re.compile(r"(?<=[.!?…])(?<!\.\.)\s+(?=[^\s])")


def extrair_rubrica(conteudo: str) -> str:
    """A rubrica de cena da seção, sem os parênteses. Vazio se não houver.

    Não é narração, mas é uma descrição visual escrita pelo autor — serve de
    semente para os prompts de imagem daquela seção.
    """
    achado = RUBRICA_RE.search(conteudo)
    return achado.group(1).strip() if achado else ""


def texto_narravel(conteudo: str) -> str:
    """O que a voz de fato diz: sem rubrica, sem ênfase markdown."""
    sem_rubrica = RUBRICA_RE.sub("", conteudo)
    sem_enfase = _ENFASE_RE.sub(r"\2", sem_rubrica)
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
