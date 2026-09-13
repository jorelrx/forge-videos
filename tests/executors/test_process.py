from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

from forge.domain.operacao import Run, RunStatus, StageName, StageResult, StageRun, StageStatus, Video
from forge.executors.process import StageProcessExecutor
from forge.services.worker import StageContext


class SeenSubprocess:
    def __init__(self, argv, **kwargs):
        self.argv = list(argv)
        self.kwargs = kwargs

    def execute(self, context, emit):
        return StageResult(gate_status="approved")


def stage_context(tmp_path: Path) -> StageContext:
    now = datetime(2026, 9, 13, tzinfo=UTC)
    run = Run(
        id="run-1",
        video_id="video-1",
        status=RunStatus.RUNNING,
        priority=50,
        queue_position=1,
        config_snapshot={},
        workflow_version=1,
        git_commit="abc",
        created_at=now,
    )
    stage = StageRun(
        id="stage-1",
        run_id=run.id,
        stage=StageName.AUDIO,
        attempt=2,
        status=StageStatus.RUNNING,
        created_at=now,
    )
    video = Video(
        id=run.video_id,
        tema="Tema",
        tese="Tese",
        created_at=now,
        updated_at=now,
    )
    output_root = tmp_path / "runs"
    return StageContext(
        run=run,
        stage_run=stage,
        video=video,
        run_dir=output_root / run.id,
    )


def test_process_executor_uses_argv_and_absolute_context_file(tmp_path, monkeypatch):
    seen: dict[str, SeenSubprocess] = {}

    def capture(argv, **kwargs):
        child = SeenSubprocess(argv, **kwargs)
        seen["child"] = child
        return child

    monkeypatch.setattr("forge.executors.process.SubprocessExecutor", capture)
    executor = StageProcessExecutor(
        StageName.AUDIO, output_root=tmp_path / "runs", timeout_seconds=90
    )

    result = executor.execute(stage_context(tmp_path), lambda **event: None)

    child = seen["child"]
    assert result.gate_status == "approved"
    assert child.argv[:3] == [sys.executable, "-m", "forge.executors.entrypoint"]
    context_path = Path(child.argv[child.argv.index("--context") + 1])
    assert context_path.is_absolute()
