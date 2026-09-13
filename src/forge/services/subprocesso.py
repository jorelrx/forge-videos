"""Executor adapter for trusted JSONL subprocesses.

The child process communicates structured progress on stdout. stderr is
diagnostic only and is never parsed as an event.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from collections.abc import Iterator, Sequence
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


def _bounded_lines(
    stream, limit: int
) -> Iterator[tuple[str, bool]]:
    """Yield lines while retaining at most ``limit`` characters per line."""

    while True:
        parts: list[str] = []
        size = 0
        truncated = False
        while True:
            # A bounded readline returns as soon as a child flushes a short
            # line, while still preventing an unterminated line from growing
            # our retained buffer without limit.
            chunk = stream.readline(limit + 1)
            if chunk == "":
                if parts or truncated:
                    yield "".join(parts), truncated
                return
            has_newline = chunk.endswith("\n")
            body = chunk[:-1] if has_newline else chunk
            if has_newline and body.endswith("\r"):
                body = body[:-1]
            remaining = limit - size
            if remaining > 0:
                parts.append(body[:remaining])
                size += min(len(body), remaining)
            if len(body) > max(remaining, 0):
                truncated = True
            if has_newline:
                yield "".join(parts), truncated
                break


class SubprocessExecutor:
    """Run an argv without a shell and translate its bounded JSONL output."""

    def __init__(
        self,
        argv: Sequence[str],
        *,
        stderr_limit: int = 4096,
        timeout_seconds: float = 300.0,
        stdout_line_limit: int = 64 * 1024,
        terminate_grace_seconds: float = 0.5,
    ) -> None:
        if isinstance(argv, (str, bytes)) or not argv:
            raise ValueError("argv must not be empty")
        if any(not isinstance(part, str) or not part for part in argv):
            raise ValueError("argv entries must be non-empty strings")
        if stderr_limit < 0:
            raise ValueError("stderr_limit must be non-negative")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if stdout_line_limit <= 0:
            raise ValueError("stdout_line_limit must be positive")
        if terminate_grace_seconds <= 0:
            raise ValueError("terminate_grace_seconds must be positive")
        self.argv = tuple(argv)
        self.stderr_limit = stderr_limit
        self.timeout_seconds = timeout_seconds
        self.stdout_line_limit = stdout_line_limit
        self.terminate_grace_seconds = terminate_grace_seconds

    def execute(self, context: Any, emit: EventSink) -> StageResult:
        process = subprocess.Popen(
            self.argv,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **self._popen_kwargs(),
        )
        stderr = _BoundedText(self.stderr_limit)
        invalid = False
        reader_errors: list[Exception] = []
        cancel_event = getattr(context, "cancel_event", None)

        def remember_error(error: Exception) -> None:
            if not reader_errors:
                reader_errors.append(error)

        def safe_emit(event: dict[str, Any]) -> None:
            try:
                emit(**event)
            except Exception as error:  # noqa: BLE001 - propagate after draining pipes
                remember_error(error)

        def invalid_event(line: str, truncated: bool) -> None:
            payload: dict[str, object] = {"line": line}
            if truncated:
                payload["truncated"] = True
            safe_emit(
                {
                    "kind": "worker.invalid_event",
                    "level": "error",
                    "message": "Evento JSONL inválido",
                    "payload": payload,
                }
            )

        def read_stdout() -> None:
            nonlocal invalid
            assert process.stdout is not None
            try:
                for line, truncated in _bounded_lines(
                    process.stdout, self.stdout_line_limit
                ):
                    if truncated:
                        invalid = True
                        invalid_event(line, True)
                        continue
                    event = self._parse_event(line)
                    if event is None:
                        invalid = True
                        invalid_event(line, False)
                    else:
                        safe_emit(event)
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
                remember_error(error)
            finally:
                process.stderr.close()

        stdout_thread = Thread(target=read_stdout, daemon=True)
        stderr_thread = Thread(target=read_stderr, daemon=True)
        stdout_thread.start()
        stderr_thread.start()

        timed_out = False
        cancelled = False
        deadline = time.monotonic() + self.timeout_seconds
        while process.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            try:
                process.wait(timeout=min(0.05, remaining))
            except subprocess.TimeoutExpired:
                continue

        if timed_out or cancelled:
            self._terminate(process)
            join_deadline = time.monotonic() + max(
                1.0, self.terminate_grace_seconds
            )
            for reader in (stdout_thread, stderr_thread):
                reader.join(timeout=max(0.0, join_deadline - time.monotonic()))
            if stdout_thread.is_alive() or stderr_thread.is_alive():
                self._close_pipes(process)
                join_deadline = time.monotonic() + self.terminate_grace_seconds
                for reader in (stdout_thread, stderr_thread):
                    reader.join(timeout=max(0.0, join_deadline - time.monotonic()))
            if stdout_thread.is_alive() or stderr_thread.is_alive():
                reader_errors.append(
                    RuntimeError(
                        "Subprocesso não drenou stdout/stderr após término"
                    )
                )
        else:
            process.wait()
            # A normally exited process has closed both pipes. Waiting without
            # a timeout guarantees that every buffered event reaches ``emit``
            # before execute returns.
            stdout_thread.join()
            stderr_thread.join()
        if reader_errors:
            raise reader_errors[0]

        if timed_out:
            emit(
                kind="subprocess_timeout",
                level="error",
                message="Subprocesso excedeu o prazo",
                payload={"timeout_seconds": self.timeout_seconds},
            )
            return StageResult(
                failure_code="subprocess_timeout",
                failure_message="Subprocesso excedeu o prazo",
            )
        if cancelled:
            emit(
                kind="subprocess_cancelled",
                level="warning",
                message="Subprocesso cancelado após perda de lease",
                payload={},
            )
            return StageResult(
                failure_code="subprocess_cancelled",
                failure_message="Subprocesso cancelado",
            )
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
    def _popen_kwargs() -> dict[str, Any]:
        if os.name == "nt":
            creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            return {"creationflags": creation_flags} if creation_flags else {}
        return {"start_new_session": True}

    @staticmethod
    def _close_pipes(process: subprocess.Popen) -> None:
        for stream in (process.stdout, process.stderr):
            if stream is None:
                continue
            try:
                stream.close()
            except Exception:  # noqa: BLE001 - best effort unblock during teardown
                pass

    @staticmethod
    def _taskkill(process: subprocess.Popen, *, force: bool) -> bool:
        command = ["taskkill", "/PID", str(process.pid), "/T"]
        if force:
            command.append("/F")
        try:
            completed = subprocess.run(
                command,
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except OSError:
            return False
        return completed.returncode == 0

    @classmethod
    def _signal_tree(cls, process: subprocess.Popen, *, force: bool) -> None:
        if os.name == "nt":
            if cls._taskkill(process, force=force):
                return
            (process.kill if force else process.terminate)()
            return
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL if force else signal.SIGTERM)
        except (OSError, ProcessLookupError):
            (process.kill if force else process.terminate)()

    def _terminate(self, process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            # Windows has no portable process-group signal equivalent. A
            # forced taskkill with /T is the reliable tree teardown path.
            self._signal_tree(process, force=True)
            try:
                process.wait(timeout=self.terminate_grace_seconds)
            except subprocess.TimeoutExpired:
                pass
            return
        self._signal_tree(process, force=False)
        try:
            process.wait(timeout=self.terminate_grace_seconds)
        except subprocess.TimeoutExpired:
            self._signal_tree(process, force=True)
            try:
                process.wait(timeout=self.terminate_grace_seconds)
            except subprocess.TimeoutExpired:
                # The kill was issued; keep the stable timeout result even if
                # the platform does not report the final return code promptly.
                pass

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
