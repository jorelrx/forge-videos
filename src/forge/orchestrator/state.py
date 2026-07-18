from typing import TypedDict

from forge.writer.models import Fonte, ReviewResult, Roteiro


class RoteiroState(TypedDict, total=False):
    tema: str | None
    research_notes: str
    fontes: list[Fonte]
    tese: str
    esboco: str
    roteiro: Roteiro | None
    review: ReviewResult | None
    rounds: int
