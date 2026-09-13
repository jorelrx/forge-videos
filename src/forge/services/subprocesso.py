"""Executor adapter for trusted JSONL subprocesses.

The child process communicates structured progress on stdout.  stderr is
diagnostic only and is never parsed as an event.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from threading import Thread
from typing import Any, Protocol

from forge.domain.operacao import StageResult


class EventSink(Protocol):
    def __call__(self, *, kind: str, level: str, message: str, payload: dict) -> None: ...


class _BoundedText:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._chunks: list[str] = []
        self._size = 0

    def append(self, chunk: str) -> None:
        if self._size >= self.limit:
            return
        kept = chunk[: self.limit - self._size]
        self._chunks.append(kept)
        self._size += len(kept)

    def value(self) -> str:
        return "".join(self._chunks)


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
        stderr = _BoundedText(self.stderr_limit)
        invalid = False
        reader_errors: list[Exception] = []

        def remember_error(error: Exception) -> None:
            if not reader_errors:
                reader_errors.append(error)

        def read_stdout() -> None:
            nonlocal invalid
            assert process.stdout is not None
            try:
                for raw_line in process.stdout:
                    try:
                        line = raw_line.rstrip("\r\n")
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
                    except Exception as error:  # noqa: BLE001 - keep draining stdout
                        remember_error(error)
            except Exception as error:  # noqa: BLE001 - propagate after draining pipes
                remember_error(error)
            finally:
                process.stdout.close()

        def read_stderr() -> None:
            assert process.stderr is not None
            try:
                for chunk in iter(lambda: process.stderr.read(8192), ""):
                    stderr.append(chunk)
            except Exception as error:  # noqa: BLE001 - propagate after draining pipes
                reader_errors.append(error)
            finally:
                process.stderr.close()

        stdout_thread = Thread(target=read_stdout, daemon=True)
        stderr_thread = Thread(target=read_stderr, daemon=True)
        stdout_thread.start()
        stderr_thread.start()
        process.wait()
        stdout_thread.join()
        stderr_thread.join()
        if reader_errors:
            raise reader_errors[0]

        if process.returncode != 0:
            emit(
                kind="subprocess_failed",
                level="error",
                message="Subprocesso terminou com erro",
                payload={
                    "exit_code": process.returncode,
                    "stderr": stderr.value(),
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
