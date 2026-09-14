"""Exercita as funções PowerShell de estado via powershell.exe.

O Windows PowerShell 5.1 desta máquina não tem Pester, então a cobertura das
mesmas funções de `scripts/studio-common.ps1` roda daqui. Os JSONs de estado
são exatamente os do teste Pester.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE = REPO_ROOT / "tests" / "scripts" / "probe_state.ps1"

POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")

pytestmark = pytest.mark.skipif(
    POWERSHELL is None,
    reason="powershell/pwsh não disponível para exercitar studio-common.ps1",
)


def run_probe(root: Path, mode: str, **kwargs: object) -> str:
    argv = [
        POWERSHELL,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(PROBE),
        "-Root",
        str(root),
        "-Mode",
        mode,
    ]
    for key, value in kwargs.items():
        argv.extend([f"-{key}", str(value)])
    completed = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def write_state(root: Path, payload: object) -> Path:
    state_dir = root / "data" / "studio"
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "processes.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def valid_state() -> dict:
    return {
        "version": 1,
        "startedAt": "2026-09-14T00:00:00Z",
        "processes": {
            "api": {
                "pid": 1001,
                "command": "forge-api",
                "log": "data/studio/logs/api.log",
            },
            "worker": {
                "pid": 1002,
                "command": "forge-worker",
                "log": "data/studio/logs/worker.log",
            },
            "web": {
                "pid": 1003,
                "command": "next",
                "log": "data/studio/logs/web.log",
            },
        },
    }


def test_save_then_read_round_trips_the_three_pids(tmp_path: Path) -> None:
    assert run_probe(tmp_path, "save", Pid_=1001) == "SAVED"

    raw = run_probe(tmp_path, "read")
    assert raw != "NULL"

    state = json.loads(raw)
    assert state["version"] == 1
    assert state["processes"]["api"]["pid"] == 1001
    assert state["processes"]["worker"]["pid"] == 1002
    assert state["processes"]["web"]["pid"] == 1003


def test_read_without_state_file_returns_null(tmp_path: Path) -> None:
    assert run_probe(tmp_path, "read") == "NULL"


def test_read_accepts_a_well_formed_state(tmp_path: Path) -> None:
    write_state(tmp_path, valid_state())
    assert run_probe(tmp_path, "read") != "NULL"


def test_unknown_version_is_treated_as_stale_and_renamed(tmp_path: Path) -> None:
    state_path = write_state(
        tmp_path, {"version": 99, "processes": {}}
    )

    assert run_probe(tmp_path, "stale") == "NULL"
    assert not state_path.exists()
    renamed = list((tmp_path / "data" / "studio").glob("processes.invalid-*.json"))
    assert len(renamed) == 1


def test_missing_slot_is_treated_as_stale(tmp_path: Path) -> None:
    payload = valid_state()
    del payload["processes"]["worker"]
    state_path = write_state(tmp_path, payload)

    assert run_probe(tmp_path, "stale") == "NULL"
    assert not state_path.exists()


def test_non_integer_pid_is_treated_as_stale(tmp_path: Path) -> None:
    payload = valid_state()
    payload["processes"]["api"]["pid"] = "nao-e-inteiro"
    state_path = write_state(tmp_path, payload)

    assert run_probe(tmp_path, "stale") == "NULL"
    assert not state_path.exists()


def test_negative_pid_is_treated_as_stale(tmp_path: Path) -> None:
    payload = valid_state()
    payload["processes"]["api"]["pid"] = -7
    state_path = write_state(tmp_path, payload)

    assert run_probe(tmp_path, "stale") == "NULL"
    assert not state_path.exists()


def test_log_outside_data_studio_logs_is_treated_as_stale(tmp_path: Path) -> None:
    payload = valid_state()
    payload["processes"]["web"]["log"] = "C:/Windows/System32/evil.log"
    state_path = write_state(tmp_path, payload)

    assert run_probe(tmp_path, "stale") == "NULL"
    assert not state_path.exists()


def test_stop_refuses_a_command_that_is_not_from_the_studio(tmp_path: Path) -> None:
    output = run_probe(tmp_path, "stop", Pid_=4242, Command="powershell")

    assert output.startswith("THREW:")
    assert "não pertence ao Forge Studio" in output
