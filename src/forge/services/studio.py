from collections.abc import Mapping

from forge.domain.operacao import StageName
from forge.infrastructure.config import Settings
from forge.repositories.connection import Database
from forge.repositories.schema import init_db
from forge.services.control_plane import ControlPlaneService
from forge.services.redacao import Redactor
from forge.services.worker import StageExecutor, StudioWorker


def build_control_plane(settings: Settings) -> ControlPlaneService:
    db = Database(settings.studio_db_path)
    init_db(db)
    return ControlPlaneService(db)


def build_worker(
    settings: Settings,
    executors: Mapping[StageName, StageExecutor],
    worker_id: str,
) -> StudioWorker:
    db = Database(settings.studio_db_path)
    init_db(db)
    return StudioWorker(
        db,
        worker_id=worker_id,
        lease_seconds=settings.worker_lease_seconds,
        heartbeat_seconds=settings.worker_heartbeat_seconds,
        executors=executors,
        redactor=Redactor(settings.secret_values()),
    )
