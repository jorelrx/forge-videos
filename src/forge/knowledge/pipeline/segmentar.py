"""Parágrafos e sentenças como intervalos de offset no texto do documento.

Nada aqui devolve string nova: só (inicio, fim). É o que garante que o texto de
um chunk é sempre uma fatia exata do original — citação nunca é reconstruída.

Parágrafo curto demais (índice, número de página solto, artefato de EPUB) é
mesclado no seguinte em vez de virar chunk próprio.
"""
import re

_QUEBRA_PARAGRAFO = re.compile(r"\n[ \t]*\n")

# Fim de sentença: pontuação final, aspas/parênteses opcionais, espaço, e
# próxima frase começando em maiúscula ou aspas.
_FIM_SENTENCA = re.compile(r'(?<=[.!?])["\')\]]*\s+(?=["\'(\[]*[A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇ])')

# Abreviações que terminam em ponto sem terminar a sentença.
_ABREVIACOES = (
    "sr.", "sra.", "dr.", "dra.", "prof.", "profa.", "st.", "ed.", "org.",
    "trad.", "cf.", "op.", "cit.", "p.", "pp.", "vol.", "n.", "etc.",
)


def _aparar(texto: str, inicio: int, fim: int) -> tuple[int, int] | None:
    """Encolhe o intervalo até remover espaço nas pontas. None se sobrar vazio."""
    while inicio < fim and texto[inicio].isspace():
        inicio += 1
    while fim > inicio and texto[fim - 1].isspace():
        fim -= 1
    return (inicio, fim) if fim > inicio else None


def paragrafos(
    texto: str, inicio: int, fim: int, *, min_chars: int = 40
) -> list[tuple[int, int]]:
    janela = texto[inicio:fim]
    cortes: list[tuple[int, int]] = []
    posicao = 0
    for quebra in _QUEBRA_PARAGRAFO.finditer(janela):
        cortes.append((posicao, quebra.start()))
        posicao = quebra.end()
    cortes.append((posicao, len(janela)))

    aparados = [
        aparado
        for corte in cortes
        if (aparado := _aparar(janela, corte[0], corte[1])) is not None
    ]
    if not aparados:
        return []

    # Mescla curto no seguinte; o último, se curto, se funde no anterior.
    mesclados: list[tuple[int, int]] = []
    pendente: int | None = None
    for indice, (i, f) in enumerate(aparados):
        comeco = pendente if pendente is not None else i
        ultimo = indice == len(aparados) - 1
        if f - comeco < min_chars and not ultimo:
            pendente = comeco
            continue
        if f - comeco < min_chars and mesclados:
            anterior_i, _ = mesclados.pop()
            mesclados.append((anterior_i, f))
        else:
            mesclados.append((comeco, f))
        pendente = None

    return [(inicio + i, inicio + f) for i, f in mesclados]


def _termina_em_abreviacao(trecho: str) -> bool:
    ultima = trecho.rsplit(maxsplit=1)[-1].lower() if trecho.split() else ""
    return ultima in _ABREVIACOES


def sentencas(texto: str, inicio: int, fim: int) -> list[tuple[int, int]]:
    janela = texto[inicio:fim]
    limites: list[int] = [0]
    for corte in _FIM_SENTENCA.finditer(janela):
        if _termina_em_abreviacao(janela[limites[-1]:corte.start()]):
            continue
        limites.append(corte.end())
    limites.append(len(janela))

    resultado: list[tuple[int, int]] = []
    for i, f in zip(limites, limites[1:]):
        aparado = _aparar(janela, i, f)
        if aparado is not None:
            resultado.append((inicio + aparado[0], inicio + aparado[1]))
    return resultado
