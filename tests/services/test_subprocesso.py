from __future__ import annotations

import json
import sys

import pytest

from forge.services.subprocesso import SubprocessExecutor


def child(*lines: str, exit_code: int = 0, stderr: str = "") -> list[str]:
    script = "import sys"
    if lines:
        script += "; " + "; ".join(f"print({line!r})" for line in lines)
    if stderr:
        script += f"; print({stderr!r}, file=sys.stderr)"
    script += f"; raise SystemExit({exit_code})"
    return [sys.executable, "-c", script]


def test_valid_jsonl_line_is_emitted_as_event():
    events: list[dict] = []
    executor = SubprocessExecutor(
        child(json.dumps({"kind": "progress", "level": "info", "message": "ok", "payload": {"n": 1}}))
    )

    result = executor.execute(None, lambda **event: events.append(event))

    assert events == [
        {"kind": "progress", "level": "info", "message": "ok", "payload": {"n": 1}}
    ]
    assert result.failed is False


def test_malformed_stdout_emits_invalid_event_and_fails():
    events: list[dict] = []
    executor = SubprocessExecutor(child("not-json"))

    result = executor.execute(None, lambda **event: events.append(event))

    assert events[0]["kind"] == "worker.invalid_event"
    assert events[0]["level"] == "error"
    assert events[0]["payload"]["line"] == "not-json"
    assert result.failure_code == "invalid_event"


def test_nonzero_exit_emits_bounded_stderr_and_fails():
    events: list[dict] = []
    executor = SubprocessExecutor(child(exit_code=3, stderr="x" * 100), stderr_limit=16)

    result = executor.execute(None, lambda **event: events.append(event))

    assert events[0]["kind"] == "subprocess_failed"
    assert events[0]["payload"] == {"exit_code": 3, "stderr": "x" * 16}
    assert result.failure_code == "subprocess_failed"


def test_empty_argv_is_rejected():
    with pytest.raises(ValueError, match="argv"):
        SubprocessExecutor([])
