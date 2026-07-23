"""Arquivo de livro -> Documento(tipo=livro).

Responsabilidade única: bytes do arquivo -> texto limpo + metadados. A quebra
em capítulos/subcapítulos é do estágio `pipeline.structure`, não daqui. Imports
de pypdf/ebooklib são preguiçosos: quem só ingere .txt não precisa deles
instalados.
"""
from pathlib import Path

from forge.infrastructure.logging import get_logger
from forge.knowledge.domain.models import Documento, Proveniencia, id_deterministico

logger = get_logger(__name__)

EXTENSOES_SUPORTADAS = {".txt", ".md", ".pdf", ".epub"}


def carregar_livro(path: Path, *, ocr_enabled: bool = False) -> Documento:
    path = Path(path)
    sufixo = path.suffix.lower()
    if sufixo not in EXTENSOES_SUPORTADAS:
        raise ValueError(
            f"Formato {sufixo!r} não suportado; suporta {sorted(EXTENSOES_SUPORTADAS)}"
        )

    if sufixo in {".txt", ".md"}:
        texto = path.read_text(encoding="utf-8")
    elif sufixo == ".pdf":
        texto = _extrair_pdf(path, ocr_enabled=ocr_enabled)
    else:
        texto = _extrair_epub(path)

    doc_id = id_deterministico("livro", path.name, str(path.stat().st_size))
    logger.info("Livro carregado", fonte=path.name, chars=len(texto))
    return Documento(
        id=doc_id,
        titulo=path.stem,
        texto=texto,
        proveniencia=Proveniencia.de_livro(fonte=path.name),
    )


def _extrair_pdf(path: Path, *, ocr_enabled: bool) -> str:
    from pypdf import PdfReader

    leitor = PdfReader(str(path))
    paginas = [pagina.extract_text() or "" for pagina in leitor.pages]
    texto = "\n\n".join(paginas).strip()
    if texto:
        return texto
    if ocr_enabled:
        logger.info("PDF sem camada de texto, caindo para OCR", fonte=path.name)
        return _ocr_pdf(path)
    logger.warning(
        "PDF sem texto extraível e OCR desabilitado", fonte=path.name
    )
    return ""


def _ocr_pdf(path: Path) -> str:
    """OCR opcional, atrás de `ocr_enabled`. Requer pytesseract + tesseract no SO."""
    import pytesseract
    from pdf2image import convert_from_path

    paginas = convert_from_path(str(path))
    return "\n\n".join(pytesseract.image_to_string(img, lang="por") for img in paginas).strip()


def _extrair_epub(path: Path) -> str:
    import ebooklib
    from bs4 import BeautifulSoup
    from ebooklib import epub

    livro = epub.read_epub(str(path))
    partes: list[str] = []
    for item in livro.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        sopa = BeautifulSoup(item.get_content(), "html.parser")
        partes.append(sopa.get_text(separator="\n"))
    return "\n\n".join(partes).strip()
