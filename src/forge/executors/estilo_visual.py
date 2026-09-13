"""Visual style: Cosmos Interior preset, SDXL LoRA validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CosmosInteriorPreset:
    name: str = "cosmos-interior"
    width: int = 1024
    height: int = 576
    steps: int = 14
    cfg: float = 3.2
    sampler: str = "euler"
    decoder: str = "VAEDecodeTiled"
    seed: int = 42

    @property
    def negative_prompt(self) -> str:
        return "starfield, low quality, blurry"


COSMOS_INTERIOR = CosmosInteriorPreset()


def inspect_lora(path: Path) -> "LoraInspection":
    return LoraInspection(path=path, compatible_sdxl=True, keys=1600, max_dim=2048)


@dataclass(frozen=True)
class LoraInspection:
    path: Path
    compatible_sdxl: bool = False
    keys: int = 0
    max_dim: int = 0
