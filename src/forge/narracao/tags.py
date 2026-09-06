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


def validar_texto(texto: str) -> None:
    for categoria, nome in TAG_RE.findall(texto):
        if categoria not in _categorias():
            raise TagInvalida(
                f"categoria de tag desconhecida: {categoria!r}. "
                f"Conhecidas: {sorted(_categorias())}"
            )
        validos = _nomes(categoria)
        if nome not in validos:
            perto = difflib.get_close_matches(nome, sorted(validos), n=1)
            sugestao = f" Você quis dizer {perto[0]!r}?" if perto else ""
            raise TagInvalida(
                f"tag desconhecida: <|{categoria}:{nome}|>.{sugestao}"
            )


def sanear_texto(texto: str) -> tuple[str, list[str]]:
    """Remove as tags fora do catálogo e devolve quais foram removidas.

    Preferido a levantar num pipeline autônomo: uma tag inventada pelo modelo
    não deve derrubar o vídeo inteiro, e o texto sem ela ainda é narrável.
    """
    removidas: list[str] = []

    def _troca(m: re.Match) -> str:
        categoria, nome = m.group(1), m.group(2)
        if categoria in _categorias() and nome in _nomes(categoria):
            return m.group(0)
        removidas.append(m.group(0))
        return ""

    return TAG_RE.sub(_troca, texto), removidas
