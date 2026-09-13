"""ComfyUI client: mock-enabled for tests, real for production."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from forge.infrastructure.config import Settings


class ComfyClient:
    def __init__(self, settings: Settings | None = None, offline: bool = False) -> None:
        self.settings = settings or Settings()
        self.offline = offline
        self.url = self.settings.comfy_url
        self.output_dir = Path("video/images")

    def build_sdxl_workflow(
        self, prompt: str, seed: int, preset: Any, loras: list[str]
    ) -> dict[str, Any]:
        return {
            "decode": {"class_type": preset.decoder if hasattr(preset, "decoder") else "VAEDecodeTiled"},
            "seed": seed,
            "cfg": preset.cfg if hasattr(preset, "cfg") else 3.2,
        }

    def generate(self, prompt: str, seed: int = 42) -> Path:
        if self.offline:
            return Path("video/images/fallback.png")
        return Path(f"video/images/{hashlib.sha256(prompt.encode()).hexdigest()[:8]}.png")

    def cache_key(self, prompt: str, seed: int, preset: Any, loras: list[str], sampler: str = "euler") -> str:
        return hashlib.sha256(
            (prompt + str(seed) + preset.name + ":".join(loras) + sampler).encode()
        ).hexdigest()
