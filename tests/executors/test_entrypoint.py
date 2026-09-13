from __future__ import annotations

import subprocess
import sys


def test_entrypoint_rejects_non_allowlisted_stage(tmp_path):
    context = tmp_path / "context.json"
    context.write_text("{}", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "forge.executors.entrypoint",
            "--context",
            str(context.resolve()),
            "--stage",
            "shell:whoami",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "invalid choice" in completed.stderr
