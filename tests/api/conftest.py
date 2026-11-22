from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from forge.api.app import ApiServices, create_app
from forge.domain.operacao import Artifact
from forge.infrastructure.config import Settings
from forge.repositories.connection import Database
from forge.repositories.operacao import OperacaoRepository
from forge.repositories.schema import init_db
from forge.services.control_plane import ControlPlaneService
from forge.services.saude import HealthProbes, StudioHealthService
from forge.services.studio_query import StudioQueryService


def _fake_probes() -> HealthProbes:
    def research() -> bool:
        return False

    def lm_studio() -> bool:
        return False

    def comfyui() -> bool:
        return False

    def tts() -> bool:
        return False

    def ffmpeg() -> bool:
        return False

    def gpu() -> str | None:
        return None

    return HealthProbes(
        research=research,
        lm_studio=lm_studio,
        comfyui=comfyui,
        tts=tts,
        ffmpeg=ffmpeg,
        gpu=gpu,
    )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        studio_db_path=tmp_path / "forge.db",
        studio_runs_dir=tmp_path / "runs",
    )


@pytest.fixture
def services(settings: Settings) -> ApiServices:
    db = Database(settings.studio_db_path)
    init_db(db)
    return ApiServices(
        settings=settings,
        commands=ControlPlaneService(db),
        queries=StudioQueryService(db),
        health=StudioHealthService(probes=_fake_probes()),
        git_commit="test-sha",
        workflow_version=1,
    )


@pytest.fixture
def api_factory() -> Callable[[ApiServices | None], Any]:
    return create_app


@pytest.fixture
def client(api_factory: Callable[[ApiServices | None], Any], services: ApiServices) -> TestClient:
    return autenticar(TestClient(api_factory(services)), services)


def autenticar(cliente, services, *, conta="pessoa", canais=("UC1",)):
    from forge.services.sessao_studio import SessaoStudio

    token = SessaoStudio(services.commands.db).criar(conta, conta)
    cliente.cookies.set("forge_sessao", token)
    cliente.headers["Origin"] = services.settings.studio_public_origin
    with services.commands.db.transaction() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO acesso_canais(conta_id, canal_id, titulo) VALUES (?, ?, ?)",
            [(conta, canal, canal) for canal in canais],
        )
    return cliente


@pytest.fixture
def create_video(client: TestClient) -> Callable[..., dict]:
    def _create(*, tema: str = "Tema", priority: int = 50) -> dict:
        response = client.post(
            "/api/videos",
            json={"tema": tema, "priority": priority, "preset": "local-recomendado-v1"},
        )
        assert response.status_code == 201, response.text
        return response.json()

    return _create


@pytest.fixture
def register_artifact(
    settings: Settings, services: ApiServices
) -> Callable[..., Artifact]:
    import hashlib
    import uuid
    from datetime import UTC, datetime

    def _register(
        run_id: str,
        *,
        content: bytes,
        mime_type: str,
        relative_path: str = "preview.bin",
    ) -> Artifact:
        path = settings.studio_runs_dir / run_id / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        with services.commands.db.transaction(immediate=True) as conn:
            repo = OperacaoRepository(conn)
            stage = repo.current_stages(run_id)[0]
            return repo.register_artifact(
                Artifact(
                    id=str(uuid.uuid4()),
                    run_id=run_id,
                    stage_run_id=stage.id,
                    kind="test.preview",
                    relative_path=relative_path,
                    sha256=hashlib.sha256(content).hexdigest(),
                    size_bytes=len(content),
                    mime_type=mime_type,
                    metadata={},
                    is_current=True,
                    created_at=datetime.now(UTC),
                )
            )

    return _register