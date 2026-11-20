"""Thumbnail 1280x720: imagem-base com o texto de chamada por cima.

O texto é curto (até 4 palavras) e precisa ser lido em tamanho de celular, então
ocupa o maior corpo que couber em ~55% da largura, em até duas linhas, branco
com contorno escuro. Um gradiente escuro à esquerda garante contraste sem
escurecer a imagem toda — o tom do canal é calmo, não gritante.

Texto é opcional: sem fonte utilizável ou sem texto, a imagem sai limpa. A
thumbnail nunca derruba a run.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps
from pydantic import BaseModel

from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)

LARGURA, ALTURA = 1280, 720
BYTES_MAXIMO = 2_000_000  # limite do YouTube para thumbnail

_MARGEM_X = 64
_FRACAO_TEXTO = 0.55          # largura máxima do bloco de texto
_FRACAO_ALTURA_TEXTO = 0.55   # altura máxima do bloco de texto
_CORPO_MAXIMO = 190
_CORPO_MINIMO = 44
_ENTRELINHA = 1.08
_QUALIDADE_INICIAL = 92
_QUALIDADE_MINIMA = 30


class ThumbnailInfo(BaseModel):
    largura: int
    altura: int
    bytes: int
    com_texto: bool


def _cobrir_e_cortar(base: Image.Image) -> Image.Image:
    """Redimensiona cobrindo o quadro e corta ao centro, sem distorcer."""
    return ImageOps.fit(
        base.convert("RGB"), (LARGURA, ALTURA), Image.LANCZOS, centering=(0.5, 0.5),
    )


def _gradiente_esquerdo(imagem: Image.Image) -> Image.Image:
    """Escurece a esquerda (opacidade ~0,78 na borda, 0 em ~70% da largura).

    A máscara é construída como uma faixa de 1 px de altura e esticada: custa
    uma linha de pixels, não a imagem inteira.
    """
    fim = int(LARGURA * 0.70)
    faixa = Image.new("L", (LARGURA, 1), 0)
    faixa.putdata([
        int(200 * max(0.0, 1.0 - x / fim) ** 1.3) for x in range(LARGURA)
    ])
    mascara = faixa.resize((LARGURA, ALTURA))
    escuro = Image.new("RGB", (LARGURA, ALTURA), (8, 10, 18))
    return Image.composite(escuro, imagem, mascara)


def _quebrar(
    palavras: list[str], fonte: ImageFont.FreeTypeFont, largura_max: int, contorno: int,
) -> list[str] | None:
    """Menor número de linhas (até 2) que cabe em `largura_max`, ou None.

    Entre as quebras de duas linhas escolhe a mais equilibrada: linhas de
    tamanho parecido ficam melhores e permitem corpo maior.
    """
    def largura(texto: str) -> float:
        return fonte.getlength(texto) + 2 * contorno

    inteiro = " ".join(palavras)
    if largura(inteiro) <= largura_max:
        return [inteiro]
    melhor: tuple[float, list[str]] | None = None
    for i in range(1, len(palavras)):
        linhas = [" ".join(palavras[:i]), " ".join(palavras[i:])]
        maior = max(largura(linha) for linha in linhas)
        if maior <= largura_max and (melhor is None or maior < melhor[0]):
            melhor = (maior, linhas)
    return melhor[1] if melhor else None


def _desenhar_texto(imagem: Image.Image, texto: str, caminho_fonte: Path) -> bool:
    """Desenha o texto no maior corpo que caiba; False se não foi possível."""
    palavras = texto.split()
    if not palavras:
        return False
    largura_max = int(LARGURA * _FRACAO_TEXTO) - _MARGEM_X
    altura_max = int(ALTURA * _FRACAO_ALTURA_TEXTO)

    escolha = None
    for corpo in range(_CORPO_MAXIMO, _CORPO_MINIMO - 1, -4):
        fonte = ImageFont.truetype(str(caminho_fonte), corpo)
        contorno = max(3, corpo // 14)
        linhas = _quebrar(palavras, fonte, largura_max, contorno)
        if linhas is None:
            continue
        passo = int(corpo * _ENTRELINHA)
        if passo * (len(linhas) - 1) + corpo + 2 * contorno > altura_max:
            continue
        escolha = (fonte, contorno, linhas, passo, corpo)
        break
    if escolha is None:
        return False

    fonte, contorno, linhas, passo, corpo = escolha
    desenho = ImageDraw.Draw(imagem)
    altura_bloco = passo * (len(linhas) - 1) + corpo
    topo = (ALTURA - altura_bloco) // 2
    for i, linha in enumerate(linhas):
        desenho.text(
            (_MARGEM_X, topo + i * passo), linha, font=fonte, fill=(255, 255, 255),
            stroke_width=contorno, stroke_fill=(10, 10, 16), anchor="la",
        )
    return True


def _salvar_ate_caber(imagem: Image.Image, saida: Path) -> int:
    """Grava JPEG baixando a qualidade de 92 até caber em `BYTES_MAXIMO`.

    Imagem com muito ruído comprime mal; a qualidade desce de 4 em 4 e, no
    pior caso, fica na mínima (o arquivo sai o menor possível, nunca falha).
    """
    saida.parent.mkdir(parents=True, exist_ok=True)
    qualidade = _QUALIDADE_INICIAL
    while True:
        imagem.save(saida, "JPEG", quality=qualidade, optimize=True)
        tamanho = saida.stat().st_size
        if tamanho <= BYTES_MAXIMO or qualidade <= _QUALIDADE_MINIMA:
            return tamanho
        qualidade -= 4


def compor_thumbnail(
    base: Path, texto: str, saida: Path, *, fonte: Path | None,
) -> ThumbnailInfo:
    """Compõe a thumbnail a partir de `base`; ver docstring do módulo."""
    with Image.open(base) as aberta:
        imagem = _cobrir_e_cortar(aberta)

    com_texto = False
    texto = (texto or "").strip()
    if texto and fonte is not None:
        try:
            # Gradiente só vale se o texto entrou: sem texto, imagem limpa.
            escurecida = _gradiente_esquerdo(imagem)
            com_texto = _desenhar_texto(escurecida, texto, fonte)
            if com_texto:
                imagem = escurecida
        except (OSError, ValueError) as exc:
            # Fonte inexistente/corrompida: segue sem texto em vez de falhar.
            logger.warning("thumbnail_sem_texto", fonte=str(fonte), erro=str(exc))
            com_texto = False
    if texto and not com_texto:
        logger.warning("thumbnail_texto_descartado", fonte=str(fonte) if fonte else None)

    tamanho = _salvar_ate_caber(imagem, saida)
    logger.info("thumbnail_gerada", bytes=tamanho, com_texto=com_texto)
    return ThumbnailInfo(
        largura=LARGURA, altura=ALTURA, bytes=tamanho, com_texto=com_texto,
    )


__all__ = ["ALTURA", "BYTES_MAXIMO", "LARGURA", "ThumbnailInfo", "compor_thumbnail"]
