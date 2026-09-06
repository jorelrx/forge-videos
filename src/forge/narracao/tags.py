"""As 43 tags de controle do higgs-tts-3-4b.

Espelho de `C:\\dev\\audio-generate\\src\\audio_generate\\tags.py`. É cópia, não
import: aquele pacote expõe `synthesize` no `__init__`, então importar qualquer
coisa dele arrasta torch e transformers — que o caminho GPU (subprocess para o
audiocpp_cli) não usa. O catálogo é dado, não lógica; ao mudar lá, mudar aqui.

Sintaxe do modelo: `<|categoria:nome|>`. Emoção, estilo e prosódia de frase vão
no começo da sentença; pausa e efeito sonoro são inline.
"""

from __future__ import annotations

import difflib
import re

TAG_RE = re.compile(r"<\|([a-z_]+):([a-z_]+)\|>")
# Qualquer coisa com FORMA de tag, mesmo malformada. Validar só pelo TAG_RE
# deixava passar `<|Emotion:Awe|>`, `<|prosody:speed-slow|>` e `<| emotion:awe |>`
# intactos, sem sequer um aviso — e lixo com cara de tag chega ao TTS horas
# depois, custando minutos de GPU por bloco.
TAG_SOLTA_RE = re.compile(r"<\|[^|>]*\|>")

TAGS_SENTENCA: dict[str, frozenset[str]] = {
    "emotion": frozenset({
        "elation", "amusement", "enthusiasm", "determination", "pride",
        "contentment", "affection", "relief", "contemplation", "confusion",
        "surprise", "awe", "longing", "arousal", "anger", "fear", "disgust",
        "bitterness", "sadness", "shame", "helplessness",
    }),
    "style": frozenset({"singing", "shouting", "whispering"}),
    "prosody": frozenset({
        "speed_very_slow", "speed_slow", "speed_fast", "speed_very_fast",
        "pitch_low", "pitch_high", "expressive_high", "expressive_low",
    }),
}

TAGS_INLINE: dict[str, frozenset[str]] = {
    "prosody": frozenset({"pause", "long_pause"}),
    "sfx": frozenset({
        "cough", "laughter", "crying", "screaming", "burping", "humming",
        "sigh", "sniff", "sneeze",
    }),
}


class TagInvalida(ValueError):
    """Tag fora do catálogo. Descobrir isso na GPU custaria minutos por trecho."""


def _nomes(categoria: str) -> frozenset[str]:
    return TAGS_SENTENCA.get(categoria, frozenset()) | TAGS_INLINE.get(
        categoria, frozenset()
    )


def _categorias() -> set[str]:
    return set(TAGS_SENTENCA) | set(TAGS_INLINE)


def _problema(tag: str) -> str | None:
    """Por que `tag` não vale, ou None se ela vale.

    Um único lugar decide o que é uma tag válida. `validar_texto` e
    `sanear_texto` reagem diferente à mesma resposta — uma levanta, a outra
    remove — mas não podem discordar sobre o que é válido: divergir aqui é
    exatamente como tag malformada atravessava a validação e chegava ao TTS.
    """
    m = TAG_RE.fullmatch(tag)
    if m is None:
        return (
            f"tag malformada: {tag}. A sintaxe é <|categoria:nome|>, tudo em "
            f"minúsculas, sem espaços, com _ separando palavras."
        )
    categoria, nome = m.group(1), m.group(2)
    if categoria not in _categorias():
        return (
            f"categoria de tag desconhecida: {categoria!r}. "
            f"Conhecidas: {sorted(_categorias())}"
        )
    validos = _nomes(categoria)
    if nome not in validos:
        perto = difflib.get_close_matches(nome, sorted(validos), n=1)
        sugestao = f" Você quis dizer {perto[0]!r}?" if perto else ""
        return f"tag desconhecida: <|{categoria}:{nome}|>.{sugestao}"
    return None


def validar_texto(texto: str) -> None:
    for tag in TAG_SOLTA_RE.findall(texto):
        problema = _problema(tag)
        if problema is not None:
            raise TagInvalida(problema)


def sanear_texto(texto: str) -> tuple[str, list[str]]:
    """Remove as tags fora do catálogo e devolve quais foram removidas.

    Preferido a levantar num pipeline autônomo: uma tag inventada pelo modelo
    não deve derrubar o vídeo inteiro, e o texto sem ela ainda é narrável.
    """
    removidas: list[str] = []

    def _troca(m: re.Match) -> str:
        tag = m.group(0)
        if _problema(tag) is None:
            return tag
        removidas.append(tag)
        return ""

    return TAG_SOLTA_RE.sub(_troca, texto), removidas
