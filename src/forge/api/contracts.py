from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Literal


class CreateVideoRequest(BaseModel):
    tema: str = Field(min_length=1, max_length=500)
    tese: str | None = Field(default=None, max_length=2000)
    priority: int = Field(default=50, ge=0, le=100)
    preset: Literal["local-recomendado-v1"] = "local-recomendado-v1"


class CreateVideoResponse(BaseModel):
    video: dict
    run: dict
