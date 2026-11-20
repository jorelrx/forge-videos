from pathlib import Path
from typing import TypedDict

from forge.domain.models import Fonte, ReviewResult, Roteiro
from forge.agents.research import PassageEvidence


class RoteiroState(TypedDict, total=False):
    # --- conteúdo: espelhado nos artefatos, reconstruível do disco ---
    tema: str | None
    research_notes: str
    fontes: list[Fonte]
    research_passages: list[PassageEvidence]
    tese: str
    esboco: str
    eixo: str | None
    roteiro: Roteiro | None
    review: ReviewResult | None
    # --- controle: orquestração, nunca vai para artefato ---
    rounds: int
    passos: int
    pedido: str | None
    run_dir: Path
    skills_dominio: list[str]
