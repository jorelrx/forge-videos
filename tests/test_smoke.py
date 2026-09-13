def test_import_forge():
    import forge
    assert isinstance(forge.__version__, str)


def test_stage_executors_registered():
    from forge.services.studio import build_stage_executors
    from forge.infrastructure.config import Settings
    from forge.domain.operacao import ETAPAS
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        settings = Settings(
            _env_file=None,
            studio_db_path=Path(td) / "forge.db",
            studio_runs_dir=Path(td) / "runs",
        )
        executors = build_stage_executors(settings)
        assert tuple(executors.keys()) == ETAPAS
        assert len(executors) == 8
