from __future__ import annotations

import json
import sys
import threading
import time
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from forge.domain.operacao import RunStatus, StageName, StageStatus
from forge.repositories.connection import Database
from forge.repositories.schema import init_db
from forge.services.control_plane import ControlPlaneService
from forge.services.subprocesso import SubprocessExecutor
from forge.services.worker import StudioWorker


def child(*lines: str, exit_code: int = 0, stderr: str = "") -> list[str]:
    script = "import sys"
    if lines:
        script += "; " + "; ".join(f"print({line!r})" for line in lines)
    if stderr:
        script += f"; print({stderr!r}, file=sys.stderr)"
    script += f"; raise SystemExit({exit_code})"
    return [sys.executable, "-c", script]


def slow_child(line: str, *, delay_seconds: float, exit_code: int = 0) -> list[str]:
    script = (
        "import sys, time; "
        f"print({line!r}, flush=True); "
        f"time.sleep({delay_seconds}); "
        f"raise SystemExit({exit_code})"
    )
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


@pytest.mark.parametrize(
    "line",
    [
        "[]",
        json.dumps({}),
        json.dumps({"kind": "", "level": "info", "message": "ok", "payload": {}}),
        json.dumps({"kind": "progress", "level": " ", "message": "ok", "payload": {}}),
        json.dumps({"kind": "progress", "level": "info", "message": 1, "payload": {}}),
        json.dumps({"kind": "progress", "level": "info", "message": "ok", "payload": []}),
    ],
    ids=["array", "missing-fields", "empty-kind", "blank-level", "non-string-message", "non-object-payload"],
)
def test_invalid_event_schema_is_rejected(line):
    events: list[dict] = []

    result = SubprocessExecutor(child(line)).execute(
        None, lambda **event: events.append(event)
    )

    assert result.failure_code == "invalid_event"
    assert events == [
        {
            "kind": "worker.invalid_event",
            "level": "error",
            "message": "Evento JSONL inválido",
            "payload": {"line": line},
        }
    ]


def test_stdout_event_is_emitted_before_subprocess_exits():
    line = json.dumps(
        {"kind": "progress", "level": "info", "message": "early", "payload": {}}
    )
    emitted = threading.Event()
    events: list[dict] = []

    def execute() -> None:
        result = SubprocessExecutor(
            slow_child(line, delay_seconds=1.0, exit_code=3)
        ).execute(None, lambda **event: (events.append(event), emitted.set()))
        events.append({"result": result})

    thread = threading.Thread(target=execute)
    thread.start()
    assert emitted.wait(timeout=0.25)
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert events[0]["kind"] == "progress"
    assert events[-1]["result"].failure_code == "subprocess_failed"


def test_nonzero_exit_emits_bounded_stderr_and_fails():
    events: list[dict] = []
    executor = SubprocessExecutor(child(exit_code=3, stderr="x" * 100), stderr_limit=16)

    result = executor.execute(None, lambda **event: events.append(event))

    assert events[0]["kind"] == "subprocess_failed"
    assert events[0]["payload"] == {"exit_code": 3, "stderr": "x" * 16}
    assert result.failure_code == "subprocess_failed"


def test_timeout_terminates_child_and_returns_stable_failure():
    started = time.monotonic()
    events: list[dict] = []
    result = SubprocessExecutor(
        slow_child("ready", delay_seconds=5), timeout_seconds=0.1
    ).execute(None, lambda **event: events.append(event))

    assert time.monotonic() - started < 2
    assert result.failure_code == "subprocess_timeout"
    assert events[-1]["kind"] == "subprocess_timeout"


def test_cancellation_event_terminates_child_after_lease_loss():
    cancelled = threading.Event()
    finished = threading.Event()
    result: list = []

    def run():
        result.append(
            SubprocessExecutor(slow_child("ready", delay_seconds=5), timeout_seconds=10).execute(
                SimpleNamespace(cancel_event=cancelled), lambda **event: None
            )
        )
        finished.set()

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(0.1)
    cancelled.set()
    assert finished.wait(timeout=2)
    thread.join(timeout=1)
    assert result[0].failure_code == "subprocess_cancelled"


def test_oversized_invalid_stdout_line_is_bounded_in_event_payload():
    events: list[dict] = []
    result = SubprocessExecutor(
        child("x" * 100), stdout_line_limit=16
    ).execute(None, lambda **event: events.append(event))

    assert result.failure_code == "invalid_event"
    assert len(events[0]["payload"]["line"]) <= 16
    assert events[0]["payload"]["truncated"] is True


def test_empty_argv_is_rejected():
    with pytest.raises(ValueError, match="argv"):
        SubprocessExecutor([])


def test_string_argv_is_rejected_instead_of_being_split_into_characters():
    with pytest.raises(ValueError, match="argv"):
        SubprocessExecutor("python")


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "forge.db")
    init_db(database)
    return database


def test_worker_persists_live_subprocess_event_in_database(db):
    now = datetime(2026, 9, 13, 4, 0, tzinfo=UTC)
    control_plane = ControlPlaneService(db, now=lambda: now)
    run = control_plane.enqueue_video(
        tema="Tema",
        tese="Tese",
        priority=50,
        config_snapshot={"locale": "pt-BR"},
        workflow_version=2,
        git_commit="abc123",
    )[1]
    line = json.dumps(
        {
            "kind": "subprocess.progress",
            "level": "info",
            "message": "Item emitido",
            "payload": {"current_items": 1},
        }
    )
    worker = StudioWorker(
        db,
        worker_id="worker-a",
        lease_seconds=45,
        executors={StageName.PREPARACAO: SubprocessExecutor(child(line))},
        now=lambda: now,
    )

    worker.run_once()

    detail = control_plane.get_run(run.id)
    events = control_plane.events_after(0, run_id=run.id)
    persisted = next(event for event in events if event.kind == "subprocess.progress")
    stage = next(item for item in detail.stages if item.stage is StageName.PREPARACAO)
    assert detail.run.status is RunStatus.RUNNING
    assert stage.status is StageStatus.SUCCEEDED
    assert persisted.payload == {"current_items": 1}
