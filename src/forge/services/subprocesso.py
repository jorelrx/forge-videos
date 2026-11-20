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
from threading import Lock, Thread
from typing import Any, Protocol

from forge.domain.execucao import StageChildResult
from forge.domain.operacao import StageResult


class EventSink(Protocol):
    def __call__(self, *, kind: str, level: str, message: str, payload: dict) -> None: ...


class _WindowsJobObject:
    """Best-effort Windows containment with kill-on-close semantics."""

    _KILL_ON_JOB_CLOSE = 0x00002000
    _EXTENDED_LIMIT_INFORMATION = 9

    def __init__(self, kernel32: Any, handle: Any) -> None:
        self._kernel32 = kernel32
        self._handle = handle
        self._closed = False

    @classmethod
    def try_create(cls, process: subprocess.Popen) -> _WindowsJobObject | None:
        if os.name != "nt":
            return None
        import ctypes
        from ctypes import wintypes

        try:
            return cls._create(process, ctypes, wintypes)
        except Exception:  # noqa: BLE001 - unsupported job APIs use fallback
            return None

    @classmethod
    def _create(
        cls, process: subprocess.Popen, ctypes: Any, wintypes: Any
    ) -> _WindowsJobObject | None:

        class IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimitInformation),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateJobObject.restype = wintypes.BOOL

        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return None
        try:
            limits = ExtendedLimitInformation()
            limits.BasicLimitInformation.LimitFlags = cls._KILL_ON_JOB_CLOSE
            if not kernel32.SetInformationJobObject(
                handle,
                cls._EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(limits),
                ctypes.sizeof(limits),
            ):
                kernel32.CloseHandle(handle)
                return None
            if not kernel32.AssignProcessToJobObject(
                handle, wintypes.HANDLE(process._handle)
            ):
                kernel32.CloseHandle(handle)
                return None
            return cls(kernel32, handle)
        except Exception:  # noqa: BLE001 - unsupported job APIs use fallback
            kernel32.CloseHandle(handle)
            return None

    def terminate(self) -> None:
        if not self._closed:
            self._kernel32.TerminateJobObject(self._handle, 1)

    def close(self) -> None:
        if not self._closed:
            self._kernel32.CloseHandle(self._handle)
            self._closed = True


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
        # O `stage.result` leva todos os artefatos da etapa numa linha só: 57
        # imagens com prompt e caminhos no metadata somaram ~76 KB e, com o
        # limite antigo de 64 KiB, a etapa caía depois de todo o trabalho feito.
        # 4 MiB ainda barra uma linha sem fim e folga vídeos longos.
        stdout_line_limit: int = 4 * 1024 * 1024,
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
        process, process_group_id, windows_job = self._spawn_process()
        stderr = _BoundedText(self.stderr_limit)
        invalid = False
        duplicate_result = False
        child_result: StageChildResult | None = None
        result_lock = Lock()
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
            nonlocal child_result, duplicate_result, invalid
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
                        if event["kind"] == "stage.result":
                            try:
                                parsed_result = StageChildResult.model_validate(
                                    event["payload"]
                                )
                            except Exception:  # noqa: BLE001 - protocol boundary
                                invalid = True
                                invalid_event(line, False)
                                continue
                            with result_lock:
                                if child_result is None:
                                    child_result = parsed_result
                                else:
                                    duplicate_result = True
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
            self._terminate(
                process,
                process_group_id=process_group_id,
                windows_job=windows_job,
            )
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
            # Root exit does not imply descendant exit. Tear down the
            # containment boundary before waiting for EOF on inherited pipes.
            self._terminate(
                process,
                process_group_id=process_group_id,
                windows_job=windows_job,
            )
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
        with result_lock:
            parsed_result = child_result
            has_duplicate = duplicate_result
        if has_duplicate:
            return StageResult(
                failure_code="duplicate_stage_result",
                failure_message="Subprocesso emitiu mais de um stage.result",
            )
        if parsed_result is None:
            return StageResult(
                failure_code="missing_stage_result",
                failure_message="Subprocesso não emitiu stage.result",
            )
        failure = parsed_result.failure
        gate = parsed_result.gate
        return StageResult(
            gate_status=gate.code,
            current_items=parsed_result.current_items,
            total_items=parsed_result.total_items,
            failure_code=(
                failure.code
                if failure is not None
                else None if gate.approved else gate.code
            ),
            failure_message=(
                failure.message
                if failure is not None
                else None if gate.approved else gate.findings[0].message
            ),
            outputs=parsed_result.model_dump(mode="json"),
        )

    @staticmethod
    def _popen_kwargs() -> dict[str, Any]:
        if os.name == "nt":
            creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
            return {"creationflags": creation_flags | 0x00000004}
        return {"start_new_session": True}

    def _spawn_process(
        self,
        **popen_options: Any,
    ) -> tuple[
        subprocess.Popen,
        int | None,
        _WindowsJobObject | None,
    ]:
        options = dict(
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace",
            # O pai decodifica UTF-8; o filho Python, com stdout em pipe,
            # codificaria no locale do sistema (cp1252 no Windows) e "áudio"
            # chegaria à API como "�udio". Os dois lados do canal precisam
            # concordar, então o pai fixa o encoding do filho aqui. Quem passa
            # `env` próprio em popen_options (CLIs que gravam em arquivo)
            # substitui este default.
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            **self._popen_kwargs(),
        )
        options.update(popen_options)
        process = subprocess.Popen(self.argv, shell=False, **options)
        process_group_id = self._capture_process_group(process)
        try:
            windows_job = _WindowsJobObject.try_create(process)
        except Exception as error:  # noqa: BLE001 - fail closed before resume
            self._cleanup_suspended_process(process)
            raise RuntimeError(
                "Windows Job Object indisponível; subprocesso não iniciado"
            ) from error
        if os.name == "nt" and windows_job is None:
            self._cleanup_suspended_process(process)
            raise RuntimeError(
                "Windows Job Object indisponível; subprocesso não iniciado"
            )
        if os.name == "nt":
            try:
                self._resume_windows_process(process)
            except Exception as error:  # noqa: BLE001 - clean up before surfacing
                self._cleanup_suspended_process(process, windows_job)
                raise RuntimeError(
                    "Falha ao liberar subprocesso suspenso"
                ) from error
        return process, process_group_id, windows_job

    def _cleanup_suspended_process(
        self,
        process: subprocess.Popen,
        windows_job: _WindowsJobObject | None = None,
    ) -> None:
        if windows_job is not None:
            try:
                windows_job.terminate()
            except Exception:  # noqa: BLE001 - continue cleanup
                pass
            finally:
                try:
                    windows_job.close()
                except Exception:  # noqa: BLE001 - continue cleanup
                    pass
        else:
            try:
                process.kill()
            except (OSError, ProcessLookupError):
                pass
        self._close_pipes(process)
        try:
            process.wait(timeout=self.terminate_grace_seconds)
        except (subprocess.TimeoutExpired, OSError, ProcessLookupError):
            pass

    @staticmethod
    def _resume_windows_process(process: subprocess.Popen) -> None:
        import ctypes
        from ctypes import wintypes

        class ThreadEntry32(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ThreadID", wintypes.DWORD),
                ("th32OwnerProcessID", wintypes.DWORD),
                ("tpBasePri", wintypes.LONG),
                ("tpDeltaPri", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.argtypes = [
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Thread32First.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ThreadEntry32),
        ]
        kernel32.Thread32First.restype = wintypes.BOOL
        kernel32.Thread32Next.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ThreadEntry32),
        ]
        kernel32.Thread32Next.restype = wintypes.BOOL
        kernel32.OpenThread.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        kernel32.OpenThread.restype = wintypes.HANDLE
        kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
        kernel32.ResumeThread.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000004, 0)
        snapshot_value = getattr(snapshot, "value", snapshot)
        if snapshot_value in (None, ctypes.c_void_p(-1).value):
            raise OSError(ctypes.get_last_error(), "CreateToolhelp32Snapshot failed")
        thread_handle = None
        try:
            entry = ThreadEntry32()
            entry.dwSize = ctypes.sizeof(entry)
            found = kernel32.Thread32First(snapshot, ctypes.byref(entry))
            while found:
                if entry.th32OwnerProcessID == process.pid:
                    thread_handle = kernel32.OpenThread(
                        0x0002, False, entry.th32ThreadID
                    )
                    break
                found = kernel32.Thread32Next(snapshot, ctypes.byref(entry))
            if not thread_handle:
                raise OSError(ctypes.get_last_error(), "main thread not found")
            if kernel32.ResumeThread(thread_handle) == 0xFFFFFFFF:
                raise OSError(ctypes.get_last_error(), "ResumeThread failed")
        finally:
            if thread_handle:
                kernel32.CloseHandle(thread_handle)
            kernel32.CloseHandle(snapshot)

    @staticmethod
    def _capture_process_group(process: subprocess.Popen) -> int | None:
        if os.name == "nt":
            return None
        # start_new_session makes the root PID the process-group ID. Keep that
        # fallback when the root exits before getpgid can inspect it.
        try:
            return os.getpgid(process.pid)
        except OSError:
            return process.pid

    @staticmethod
    def _close_pipes(process: subprocess.Popen) -> None:
        for stream in (process.stdout, process.stderr):
            if stream is None:
                continue
            try:
                stream.close()
            except Exception:  # noqa: BLE001 - best effort unblock during teardown
                pass

    @classmethod
    def _signal_tree(
        cls,
        process: subprocess.Popen,
        *,
        process_group_id: int | None,
        force: bool,
    ) -> None:
        if os.name == "nt":
            raise RuntimeError("Windows Job Object obrigatório para subprocesso")
        if process_group_id is not None:
            try:
                os.killpg(
                    process_group_id,
                    signal.SIGKILL if force else signal.SIGTERM,
                )
                return
            except ProcessLookupError:
                return
            except PermissionError:
                pass
        try:
            if process.poll() is None:
                (process.kill if force else process.terminate)()
        except ProcessLookupError:
            pass

    @classmethod
    def _terminate_windows_tree(
        cls,
        process: subprocess.Popen,
        windows_job: _WindowsJobObject | None,
    ) -> None:
        if windows_job is not None:
            windows_job.terminate()
            windows_job.close()
            return
        raise RuntimeError("Windows Job Object obrigatório para subprocesso")

    def _terminate(
        self,
        process: subprocess.Popen,
        *,
        process_group_id: int | None,
        windows_job: _WindowsJobObject | None,
    ) -> None:
        if os.name == "nt":
            self._terminate_windows_tree(process, windows_job)
            try:
                process.wait(timeout=self.terminate_grace_seconds)
            except subprocess.TimeoutExpired:
                pass
            return
        self._signal_tree(
            process, process_group_id=process_group_id, force=False
        )
        try:
            process.wait(timeout=self.terminate_grace_seconds)
        except subprocess.TimeoutExpired:
            pass
        # Always issue the force signal after the grace period. Root may have
        # exited while a descendant kept the process group and output pipe.
        self._signal_tree(
            process, process_group_id=process_group_id, force=True
        )
        try:
            process.wait(timeout=self.terminate_grace_seconds)
        except subprocess.TimeoutExpired:
            # The kill was issued; keep the stable timeout result even if the
            # platform does not report the final return code promptly.
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
        if value["kind"] == "stage.result":
            try:
                StageChildResult.model_validate(value["payload"])
            except Exception:  # noqa: BLE001 - malformed child protocol
                return None
        return {
            "kind": value["kind"],
            "level": value["level"],
            "message": value["message"],
            "payload": value["payload"],
        }


__all__ = ["SubprocessExecutor"]
