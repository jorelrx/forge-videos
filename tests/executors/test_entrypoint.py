from __future__ import annotations

import subprocess
import sys

from forge.domain.execucao import RunSnapshot
from forge.domain.operacao import StageName
import forge.executors.entrypoint as entrypoint


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


def test_entrypoint_rejects_stage_flag_mismatch_before_importing_executor(
    tmp_path, monkeypatch, capsys
):
    output_root = tmp_path / "runs"
    snapshot = RunSnapshot(
        run_id="run-1",
        video_id="video-1",
        tema="Tema",
        tese="Tese",
        stage=StageName.AUDIO,
        attempt=1,
        output_root=output_root,
        run_dir=output_root / "run-1",
        config_snapshot={},
        artifacts=[],
        work_items=[],
    )
    context = tmp_path / "context.json"
    context.write_text(snapshot.model_dump_json(), encoding="utf-8")
    imported: list[StageName] = []

    def fail_if_imported(stage):
        imported.append(stage)
        raise AssertionError("executor import must not happen")

    monkeypatch.setattr(entrypoint, "_implementation", fail_if_imported)

    result = entrypoint.main(
        [
            "--context",
            str(context.resolve()),
            "--stage",
            StageName.IMAGENS.value,
        ]
    )

    assert result == 1
    assert imported == []
    assert "does not match" in capsys.readouterr().err
