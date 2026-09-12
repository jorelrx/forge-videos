from forge.infrastructure.config import Settings
from forge.services.control_plane import ControlPlaneService
from forge.services.studio import build_control_plane


def enqueue(control_plane: ControlPlaneService):
    return control_plane.enqueue_video(
        tema="Bootstrap local",
        tese="O bootstrap deve preservar runs persistidas.",
        priority=50,
        config_snapshot={"locale": "pt-BR"},
        workflow_version=1,
        git_commit="abc123",
    )


def test_build_control_plane_inicializa_schema_local_e_enfileira_run(tmp_path):
    studio_db_path = tmp_path / "studio" / "forge.db"
    settings = Settings(_env_file=None, studio_db_path=studio_db_path)

    assert not studio_db_path.exists()

    control_plane = build_control_plane(settings)

    assert isinstance(control_plane, ControlPlaneService)
    assert studio_db_path.exists()
    _, run = enqueue(control_plane)
    assert control_plane.get_run(run.id).run == run


def test_build_control_plane_duas_vezes_preserva_run_existente(tmp_path):
    settings = Settings(_env_file=None, studio_db_path=tmp_path / "forge.db")
    first_control_plane = build_control_plane(settings)
    _, run = enqueue(first_control_plane)

    second_control_plane = build_control_plane(settings)

    assert second_control_plane.get_run(run.id).run == run
