"""PDF -> texto + offsets de página.

Nós concatenamos as páginas e registramos o offset acumulado de cada uma: o
offset é controle nosso, não do extrator. `pypdf` não garante nada sobre
posição, então derivar página a partir dele depois seria chute.
"""
from pathlib import Path

from forge.infrastructure.logging import get_logger
from forge.knowledge.sources.extract.texto import marcas_de_texto
from forge.knowledge.sources.extract.tipos import TextoExtraido

logger = get_logger(__name__)

_SEPARADOR = "\n\n"


def montar_paginas(paginas: list[str]) -> tuple[str, list[int]]:
    """Concatena as páginas e devolve (texto, offset inicial de cada página)."""
    if not paginas:
        return "", []
    offsets: list[int] = []
    partes: list[str] = []
    posicao = 0
    for indice, pagina in enumerate(paginas):
        if indice:
            partes.append(_SEPARADOR)
            posicao += len(_SEPARADOR)
        offsets.append(posicao)
        partes.append(pagina)
        posicao += len(pagina)
    return "".join(partes), offsets


def extrair_pdf(path: Path, *, ocr_enabled: bool = False) -> TextoExtraido:
    from pypdf import PdfReader

    leitor = PdfReader(str(path))
    brutas = [pagina.extract_text() or "" for pagina in leitor.pages]
    texto, offsets = montar_paginas(brutas)

    if not texto.strip() and ocr_enabled:
        logger.info("PDF sem camada de texto, caindo para OCR", fonte=path.name)
        brutas = _ocr_paginas(path)
        texto, offsets = montar_paginas(brutas)
        if not texto.strip():
            logger.warning("OCR habilitado mas não extraiu texto", fonte=path.name)
    elif not texto.strip():
        logger.warning("PDF sem texto extraível e OCR desabilitado", fonte=path.name)

    if texto.strip():
        logger.info("PDF extraído", fonte=path.name, paginas=len(offsets), chars=len(texto))
    return TextoExtraido(texto=texto, marcas=marcas_de_texto(texto), paginas=offsets)


def _ocr_paginas(path: Path) -> list[str]:
    """OCR opcional, atrás de `ocr_enabled`. Requer pytesseract + tesseract no SO."""
    import pytesseract
    from pdf2image import convert_from_path

    return [pytesseract.image_to_string(img, lang="por") for img in convert_from_path(str(path))]
