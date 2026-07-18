import re
import unicodedata
from datetime import datetime
from pathlib import Path

from forge.config import Settings
from forge.writer.models import Roteiro


def gravar_roteiro(
    roteiro: Roteiro,
    settings: Settings,
    rounds: int | None = None,
    aprovado: bool | None = None,
) -> Path:
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = settings.output_dir / f"{_slug(roteiro.tema)}-{ts}.md"
    path.write_text(_render(roteiro, settings, rounds, aprovado, ts), encoding="utf-8")
    return path


def _render(
    roteiro: Roteiro,
    settings: Settings,
    rounds: int | None,
    aprovado: bool | None,
    ts: str,
) -> str:
    linhas = [
        "---",
        f"tema: {roteiro.tema}",
        f"tese: {roteiro.tese}",
        f"modelo: {settings.model}",
        f"timestamp: {ts}",
        f"rounds: {rounds if rounds is not None else 0}",
        f"aprovado: {aprovado}",
        "---",
        "",
    ]
    for s in roteiro.secoes:
        linhas.append(f"## {s.nome}")
        linhas.append("")
        linhas.append(s.conteudo)
        linhas.append("")
    if roteiro.fontes:
        linhas.append("## Fontes")
        linhas.append("")
        for f in roteiro.fontes:
            autor = f" — {f.autor}" if f.autor else ""
            linhas.append(f"- {f.titulo}{autor}")
    return "\n".join(linhas) + "\n"


def _slug(texto: str) -> str:
    norm = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    norm = re.sub(r"[^a-zA-Z0-9]+", "-", norm).strip("-").lower()
    return (norm or "roteiro")[:60]
