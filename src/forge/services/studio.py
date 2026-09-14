from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from forge.domain.operacao import ETAPAS, StageName
from forge.infrastructure.config import Settings
from forge.repositories.connection import Database
from forge.repositories.schema import init_db
from forge.services.control_plane import ControlPlaneService
from forge.services.redacao import Redactor
from forge.services.worker import StageExecutor, StudioWorker
from forge.executors.process import StageProcessExecutor


def build_stage_executors(settings: Settings) -> dict[StageName, StageExecutor]:
    return {
        stage: StageProcessExecutor(
            stage=stage,
            output_root=settings.studio_runs_dir,
            timeout_seconds=settings.stage_timeout(stage),
        )
        for stage in ETAPAS
    }


def build_control_plane(settings: Settings) -> ControlPlaneService:
    db = Database(settings.studio_db_path)
    init_db(db)
    return ControlPlaneService(db)


def build_worker(
    settings: Settings,
    executors: Mapping[StageName, StageExecutor] | None = None,
    worker_id: str = "forge-worker",
) -> StudioWorker:
    db = Database(settings.studio_db_path)
    init_db(db)
    if executors is None:
        executors = build_stage_executors(settings)
    return StudioWorker(
        db,
        worker_id=worker_id,
        lease_seconds=settings.worker_lease_seconds,
        heartbeat_seconds=settings.worker_heartbeat_seconds,
        executors=executors,
        redactor=Redactor(settings.secret_values()),
        runs_root=settings.studio_runs_dir,
    )
