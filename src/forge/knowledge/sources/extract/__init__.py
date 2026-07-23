"""Extração por formato: arquivo -> TextoExtraido. Imports preguiçosos.

Quem só ingere .txt não precisa de pypdf nem ebooklib instalados.
"""
from pathlib import Path

from forge.knowledge.sources.extract.texto import extrair_texto, marcas_de_texto
from forge.knowledge.sources.extract.tipos import Marca, TextoExtraido, pagina_de_offset

EXTENSOES_SUPORTADAS = {".txt", ".md", ".pdf", ".epub"}

__all__ = [
    "EXTENSOES_SUPORTADAS",
    "Marca",
    "TextoExtraido",
    "extrair_arquivo",
    "extrair_texto",
    "marcas_de_texto",
    "pagina_de_offset",
]


def extrair_arquivo(path: Path, *, ocr_enabled: bool = False) -> TextoExtraido:
    path = Path(path)
    sufixo = path.suffix.lower()
    if sufixo not in EXTENSOES_SUPORTADAS:
        raise ValueError(
            f"Formato {sufixo!r} não suportado; suporta {sorted(EXTENSOES_SUPORTADAS)}"
        )
    if sufixo in {".txt", ".md"}:
        return extrair_texto(path.read_text(encoding="utf-8"))
    if sufixo == ".pdf":
        from forge.knowledge.sources.extract.pdf import extrair_pdf

        return extrair_pdf(path, ocr_enabled=ocr_enabled)
    from forge.knowledge.sources.extract.epub import extrair_epub

    return extrair_epub(path)
