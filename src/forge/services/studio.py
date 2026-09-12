from forge.infrastructure.config import Settings
from forge.repositories.connection import Database
from forge.repositories.schema import init_db
from forge.services.control_plane import ControlPlaneService


def build_control_plane(settings: Settings) -> ControlPlaneService:
    db = Database(settings.studio_db_path)
    init_db(db)
    return ControlPlaneService(db)
