"""Parent adapter that runs one typed stage in an isolated child process."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

from forge.domain.execucao import RunSnapshot
from forge.domain.operacao import StageName, StageResult
from forge.services.subprocesso import SubprocessExecutor
from forge.services.worker import EventSink, StageContext


_PROTOCOL_FAILURES = frozenset(
    {
        "subprocess_timeout",
        "subprocess_cancelled",
        "subprocess_failed",
        "invalid_event",
        "missing_stage_result",
        "duplicate_stage_result",
    }
)


class StageProcessExecutor:
    def __init__(
        self,
        stage: StageName,
        output_root: Path,
        timeout_seconds: float,
    ) -> None:
        self.stage = StageName(stage)
        self.output_root = Path(output_root).resolve()
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds

    def execute(self, context: StageContext, emit: EventSink) -> StageResult:
        snapshot = self._snapshot(context)
        context_path = self._write_context(snapshot)
        argv = [
            sys.executable,
            "-m",
            "forge.executors.entrypoint",
            "--context",
            str(context_path),
            "--stage",
            self.stage.value,
        ]
        try:
            result = SubprocessExecutor(
                argv,
                timeout_seconds=self.timeout_seconds,
            ).execute(context, emit)
            if result.failure_code not in _PROTOCOL_FAILURES:
                context_path.unlink(missing_ok=True)
            return result
        except Exception:
            # Keep the snapshot for post-mortem and a possible operator retry.
            raise

    def _snapshot(self, context: StageContext) -> RunSnapshot:
        if context.stage_run.stage is not self.stage:
            raise ValueError("context stage does not match executor stage")
        if context.video is None:
            raise ValueError("stage context is missing video")
        run_dir = (
            context.run_dir
            if context.run_dir is not None
            else self.output_root / context.run.id
        ).resolve()
        return RunSnapshot(
            run_id=context.run.id,
            video_id=context.run.video_id,
            tema=context.video.tema,
            tese=context.video.tese,
            stage=self.stage,
            attempt=context.stage_run.attempt,
            output_root=self.output_root,
            run_dir=run_dir,
            config_snapshot=context.run.config_snapshot,
            artifacts=context.artifacts,
            work_items=context.work_items,
        )

    @staticmethod
    def _write_context(snapshot: RunSnapshot) -> Path:
        target_dir = snapshot.run_dir / "video"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / (
            f".stage-{snapshot.stage.value}-r{snapshot.attempt}.json"
        )
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target_dir,
            prefix=f"{target.name}.tmp-",
            suffix="",
            delete=False,
        ) as temporary:
            temporary.write(snapshot.model_dump_json())
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, target)
        return target


__all__ = ["StageProcessExecutor"]
