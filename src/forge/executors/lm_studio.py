"""Small adapter for loading the one local model used by Studio runs."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from typing import Any

from forge.infrastructure.config import Settings


class LMStudioManager:
    """Load the configured model with a fixed, auditable command line."""

    REMOVED_MODEL = "qwen/qwen3.8-27b"

    def __init__(self, settings: Settings, *, run: Callable[..., Any] | Any | None = None):
        self.settings = settings
        self._run = run or subprocess.run

    def ensure_loaded(self) -> None:
        model = self.settings.resolved_model
        if model == self.REMOVED_MODEL:
            raise ValueError(f"modelo removido do preset: {model}")
        argv = [
            self.settings.lms_bin,
            "load",
            model,
            "-c",
            str(self.settings.llm_context_length),
            "--ttl",
            str(self.settings.lm_studio_ttl_seconds),
            "-y",
        ]
        runner = self._run
        if not callable(runner) and hasattr(runner, "run"):
            runner = runner.run
        try:
            result = runner(
                argv,
                check=True,
                capture_output=True,
                text=True,
                timeout=self.settings.llm_timeout,
            )
        except TypeError:
            # Tiny injected runners in unit tests often accept argv only.  The
            # production subprocess path above remains fully bounded.
            result = runner(argv)
        try:
            runner.argv = argv
        except (AttributeError, TypeError):
            pass
        if getattr(result, "returncode", 0) not in (0, None):
            raise RuntimeError(f"falha ao carregar modelo LM Studio: {model}")


__all__ = ["LMStudioManager"]
