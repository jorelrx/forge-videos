"""Cartões de fonte: quem está sendo citado aparece na tela, por quanto tempo.

O canal só afirma o que o acervo sustenta; o cartão é a forma visível disso.
Mas fonte na tela a cada bloco vira ruído — numa run real seriam dezoito
cartões seguidos de William James. Por isso a paráfrase só ganha faixa quando
a obra muda ou quando a seção começa, e a citação literal (que o espectador
ouve entre aspas) ganha o trecho inteiro, centralizado, pela duração do bloco.

A atribuição vem só da lista de `Citacao` (derivada de `citacoes.json`):
caminho sem entrada ali não gera cartão. Atribuir de cabeça seria exatamente a
falsa atribuição que o pipeline existe para evitar.

O ASS gerado é queimado pelo filtro `ass` do FFmpeg (libass). O texto vem do
roteiro e pode conter `{`, `}` e `\\` — escapados aqui para nunca virarem
comando do libass nem quebrarem a linha `Dialogue`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from forge.domain.midia import BlocoNarracao
from forge.services.citacoes import Citacao
from forge.services.linha_tempo import TrechoTempo

RODAPE_SEGUNDOS = 6.0
CITACAO_MAXIMO = 220

# Caracteres por linha, medidos para Georgia nos tamanhos dos estilos abaixo
# numa tela de 1920 de largura com as margens laterais. O libass quebraria
# sozinho, mas a quebra dele é imprevisível com a caixa de fundo; a nossa é
# por palavra e testável.
_LINHA_CITACAO = 42
_LINHA_RODAPE = 64

# Separa a barra do caractere seguinte sem aparecer na tela: `\N` do texto
# continua `\N` visível em vez de virar quebra. Conferido no libass do FFmpeg 8.
_ESPACO_ZERO = "​"


class Cartao(BaseModel):
    tipo: Literal["rodape", "citacao"]
    inicio: float
    fim: float
    atribuicao: str  # "Autor — Obra", ou só a obra sem autor
    texto: str = ""  # só em "citacao": o trecho falado
    traducao: bool = False


def planejar_cartoes(
    blocos: list[BlocoNarracao], tempos: list[TrechoTempo], citacoes: list[Citacao],
) -> list[Cartao]:
    """No máximo um cartão por bloco, na ordem da narração.

    A citação literal ganha da paráfrase no mesmo bloco: é a que o espectador
    ouve entre aspas e precisa ver atribuída. Bloco sem tempo na linha do tempo
    é pulado — sem saber quando ele é falado, qualquer cartão sairia fora de
    sincronia.
    """
    fontes = {c.path: c for c in citacoes}
    por_bloco = {t.bloco_id: t for t in tempos}
    cartoes: list[Cartao] = []
    ultima_obra: tuple[str, str] | None = None
    secoes_com_cartao: set[str] = set()
    cursor = 0.0  # fim do último cartão: garante que nenhum se sobreponha

    for bloco in blocos:
        tempo = por_bloco.get(bloco.id)
        if tempo is None:
            continue
        cartao, obra = _cartao_do_bloco(
            bloco, tempo, fontes,
            ultima_obra=ultima_obra,
            secao_nova=bloco.secao not in secoes_com_cartao,
        )
        if cartao is None:
            continue
        inicio = max(cartao.inicio, cursor)
        if inicio >= cartao.fim:
            continue
        cartoes.append(cartao.model_copy(update={"inicio": inicio}))
        cursor = cartao.fim
        ultima_obra = obra
        secoes_com_cartao.add(bloco.secao)
    return cartoes


def _cartao_do_bloco(
    bloco: BlocoNarracao, tempo: TrechoTempo, fontes: dict[str, Citacao], *,
    ultima_obra: tuple[str, str] | None, secao_nova: bool,
) -> tuple[Cartao | None, tuple[str, str] | None]:
    for literal in bloco.citacoes_literais:
        fonte = fontes.get(literal.path)
        if fonte is None:
            continue
        texto = literal.traducao or literal.trecho
        if len(texto) <= CITACAO_MAXIMO:
            return Cartao(
                tipo="citacao", inicio=tempo.inicio, fim=tempo.fim,
                atribuicao=_atribuicao(fonte), texto=texto,
                traducao=bool(literal.traducao),
            ), _obra(fonte)
        # Longa demais para caber na tela: ainda é uma citação entre aspas, e
        # a atribuição vai para o rodapé mesmo que a obra não tenha mudado.
        return _rodape(tempo, fonte), _obra(fonte)

    literais = {literal.path for literal in bloco.citacoes_literais}
    for caminho in bloco.referencias:
        fonte = fontes.get(caminho)
        if fonte is None or caminho in literais:
            continue
        if secao_nova or _obra(fonte) != ultima_obra:
            return _rodape(tempo, fonte), _obra(fonte)
    return None, None


def _rodape(tempo: TrechoTempo, fonte: Citacao) -> Cartao:
    return Cartao(
        tipo="rodape", inicio=tempo.inicio,
        fim=min(tempo.inicio + RODAPE_SEGUNDOS, tempo.fim),
        atribuicao=_atribuicao(fonte),
    )


def _obra(fonte: Citacao) -> tuple[str, str]:
    return (fonte.autor.strip(), fonte.obra.strip())


def _nome_legivel(autor: str) -> str:
    """ "James, William" → "William James", para UM autor.

    O acervo guarda o autor em forma de catálogo. Só inverte o caso inequívoco:
    uma vírgula e nenhum dígito (uma data pode ocupar o lugar do prenome).
    """
    partes = [parte.strip() for parte in autor.split(",")]
    if len(partes) != 2 or not all(partes) or any(c.isdigit() for c in autor):
        return autor.strip()
    return f"{partes[1]} {partes[0]}"


def _atribuicao(fonte: Citacao) -> str:
    """ "Autor — Obra". Inverte nome só quando há a lista de autores.

    A string `autor` junta os autores por vírgula: "Epictetus, Thomas Wentworth
    Higginson" são duas pessoas, e invertê-la poria na tela um nome que não
    existe. Sem a lista (citações gravadas antes dela) o texto fica como veio.
    """
    autor, obra = _obra(fonte)
    if fonte.autores:
        autor = ", ".join(_nome_legivel(nome) for nome in fonte.autores if nome.strip())
    return f"{autor} — {obra}" if autor else obra


# --- ASS ----------------------------------------------------------------------

# Cores ASS são &HAABBGGRR, com AA = transparência (00 opaco, FF invisível).
# Tudo em branco quebrado e sombra suave: o canal é contemplativo, o cartão
# informa sem chamar o olho para longe da imagem.
_FORMATO_ESTILO = (
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
    "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
    "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
    "MarginR, MarginV, Encoding"
)
_FORMATO_EVENTO = (
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
)


def gerar_ass(
    cartoes: list[Cartao], *, fonte: str, largura: int = 1920, altura: int = 1080,
) -> str:
    """Arquivo ASS completo; sem cartões, ainda válido e sem eventos.

    Lista vazia devolve o arquivo mesmo assim para que a montagem não precise
    de um caminho à parte: queimar um ASS sem eventos não muda o vídeo.
    """
    # Vírgula no nome da fonte quebraria a linha `Style`, que é separada por vírgula.
    fonte = fonte.replace(",", " ").strip() or "Georgia"
    margem = round(largura / 24)
    linhas = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {largura}",
        f"PlayResY: {altura}",
        # Sem quebra automática: a quebra é nossa, por palavra (`_quebrar`).
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        _FORMATO_ESTILO,
        # Rodapé: canto inferior esquerdo, pequeno, levemente translúcido.
        f"Style: Rodape,{fonte},{round(altura * 0.038)},&H30EDEDED,&H30EDEDED,"
        f"&HA0000000,&HB0000000,0,1,0,0,100,100,0,0,1,1,1,1,"
        f"{margem},{margem},{round(altura * 0.055)},1",
        # Citação: centro, sombra leve; o escuro vem do estilo Fundo, por baixo.
        f"Style: Citacao,{fonte},{round(altura * 0.056)},&H00F2F2F2,&H00F2F2F2,"
        f"&H80000000,&H90000000,0,0,0,0,100,100,0,0,1,1,1,5,"
        f"{margem * 3},{margem * 3},0,1",
        # Fundo: retângulo da tela inteira, preto translúcido. A caixa por linha
        # do BorderStyle 3 sai serrilhada (uma caixa de largura diferente por
        # linha); escurecer o quadro todo é uniforme e deixa a imagem visível.
        f"Style: Fundo,{fonte},10,&H60000000,&H60000000,&HFF000000,&HFF000000,"
        f"0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1",
        "",
        "[Events]",
        _FORMATO_EVENTO,
    ]
    for cartao in cartoes:
        inicio, fim = _tempo(cartao.inicio), _tempo(cartao.fim)
        if cartao.tipo == "citacao":
            linhas.append(
                f"Dialogue: 0,{inicio},{fim},Fundo,,0,0,0,,"
                f"{{\\pos(0,0)\\fad(600,600)\\p1}}"
                f"m 0 0 l {largura} 0 {largura} {altura} 0 {altura}{{\\p0}}"
            )
            linhas.append(
                f"Dialogue: 1,{inicio},{fim},Citacao,,0,0,0,,"
                f"{_texto_citacao(cartao, altura)}"
            )
        else:
            linhas.append(
                f"Dialogue: 0,{inicio},{fim},Rodape,,0,0,0,,{_texto_rodape(cartao)}"
            )
    return "\n".join(linhas) + "\n"


def _texto_citacao(cartao: Cartao, altura: int) -> str:
    corpo = _linhas_escapadas(cartao.texto, _LINHA_CITACAO)
    atribuicao = cartao.atribuicao + (" · tradução livre" if cartao.traducao else "")
    rodape = _linhas_escapadas(atribuicao, _LINHA_CITACAO + 12)
    # Atribuição em linha própria, menor e em itálico, depois de uma linha em
    # branco: lê-se primeiro a frase, depois quem a disse.
    return (
        "{\\fad(600,600)}" + corpo
        + "\\N{\\fs" + str(round(altura * 0.016)) + "} \\N"
        + "{\\fs" + str(round(altura * 0.036)) + "\\i1}" + rodape
    )


def _texto_rodape(cartao: Cartao) -> str:
    return "{\\fad(500,500)}" + _linhas_escapadas(cartao.atribuicao, _LINHA_RODAPE)


def _linhas_escapadas(texto: str, largura: int) -> str:
    """Quebra por palavra e só então escapa: o escape não conta na largura."""
    return "\\N".join(_escapar(linha) for linha in _quebrar(texto, largura))


def _quebrar(texto: str, largura: int) -> list[str]:
    """Linhas de até `largura` caracteres, cortando só entre palavras.

    Quebras de linha do texto viram espaço: dentro de `Dialogue` uma quebra
    real encerraria o evento. Palavra maior que a largura fica sozinha na linha
    em vez de ser partida.
    """
    linhas: list[str] = []
    atual = ""
    for palavra in texto.split():
        candidata = f"{atual} {palavra}" if atual else palavra
        if atual and len(candidata) > largura:
            linhas.append(atual)
            atual = palavra
        else:
            atual = candidata
    if atual:
        linhas.append(atual)
    return linhas


def _escapar(texto: str) -> str:
    """Neutraliza o que o libass leria como comando.

    A barra vem primeiro: separada do caractere seguinte por um espaço de
    largura zero, `\\N`, `\\h` e companhia ficam texto. Depois `{`/`}` viram
    `\\{`/`\\}`, que o libass desenha como chave literal em vez de abrir bloco
    de override.
    """
    texto = texto.replace("\\", "\\" + _ESPACO_ZERO)
    return texto.replace("{", "\\{").replace("}", "\\}")


def _tempo(segundos: float) -> str:
    """`H:MM:SS.cc`, em centésimos — a precisão do formato ASS."""
    centesimos = max(0, round(segundos * 100))
    horas, resto = divmod(centesimos, 360_000)
    minutos, resto = divmod(resto, 6_000)
    seg, cent = divmod(resto, 100)
    return f"{horas}:{minutos:02d}:{seg:02d}.{cent:02d}"


__all__ = [
    "CITACAO_MAXIMO", "RODAPE_SEGUNDOS", "Cartao", "gerar_ass", "planejar_cartoes",
]
