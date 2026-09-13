"""Executor adapter for trusted JSONL subprocesses.

The child process communicates structured progress on stdout.  stderr is
diagnostic only and is never parsed as an event.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from typing import Any, Protocol

from forge.domain.operacao import StageResult


class EventSink(Protocol):
    def __call__(self, *, kind: str, level: str, message: str, payload: dict) -> None: ...


class SubprocessExecutor:
    """Run an argv without a shell and translate its JSONL output to events."""

    def __init__(self, argv: Sequence[str], *, stderr_limit: int = 4096) -> None:
        if isinstance(argv, (str, bytes)) or not argv:
            raise ValueError("argv must not be empty")
        if any(not isinstance(part, str) or not part for part in argv):
            raise ValueError("argv entries must be non-empty strings")
        if stderr_limit < 0:
            raise ValueError("stderr_limit must be non-negative")
        self.argv = tuple(argv)
        self.stderr_limit = stderr_limit

    def execute(self, context: Any, emit: EventSink) -> StageResult:
        del context
        process = subprocess.Popen(
            self.argv,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        stdout, stderr = process.communicate()
        invalid = False
        for line in stdout.splitlines():
            event = self._parse_event(line)
            if event is None:
                invalid = True
                emit(
                    kind="worker.invalid_event",
                    level="error",
                    message="Evento JSONL inválido",
                    payload={"line": line},
                )
            else:
                emit(**event)

        if process.returncode != 0:
            invalid = True
            emit(
                kind="subprocess_failed",
                level="error",
                message="Subprocesso terminou com erro",
                payload={
                    "exit_code": process.returncode,
                    "stderr": stderr[: self.stderr_limit],
                },
            )
            return StageResult(
                failure_code="subprocess_failed",
                failure_message=f"exit code {process.returncode}",
            )
        if invalid:
            return StageResult(
                failure_code="invalid_event",
                failure_message="Subprocesso emitiu evento JSONL inválido",
            )
        return StageResult(gate_status="approved")

    @staticmethod
    def _parse_event(line: str) -> dict[str, Any] | None:
        try:
            value = json.loads(line)
        except (TypeError, ValueError):
            return None
        if not isinstance(value, dict):
            return None
        for field in ("kind", "level", "message"):
            if not isinstance(value.get(field), str) or not value[field].strip():
                return None
        if not isinstance(value.get("payload"), dict):
            return None
        return {
            "kind": value["kind"],
            "level": value["level"],
            "message": value["message"],
            "payload": value["payload"],
        }


__all__ = ["SubprocessExecutor"]
