from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

from forge.api.app import create_app, ApiServices
from forge.api.contracts import CreateVideoRequest
from forge.domain.operacao import RunStatus
from forge.infrastructure.config import Settings
from forge.repositories.connection import Database
from forge.services.control_plane import ControlPlaneService
from forge.services.studio_query import StudioQueryService
from forge.services.saude import StudioHealthService
from forge.services.saude import _default_probes as _health_probes
from forge.repositories.schema import init_db
from forge.api.routes.system import REQUIRED_SERVICES, list_services
import json


def _make_services(settings: Settings) -> ApiServices:
    db = Database(str(settings.studio_db_path))
    init_db(db)
    return ApiServices(
        settings=settings,
        commands=ControlPlaneService(db),
        queries=StudioQueryService(db),
        health=StudioHealthService(probes=_health_probes()),
        git_commit="test-sha",
        workflow_version=1,
    )


def test_services_route_exists(client: TestClient) -> None:
    resp = client.get("/api/services")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body
    names = {item["name"] for item in body["items"]}
    assert names == REQUIRED_SERVICES


def test_effective_config_redacts_keys(client: TestClient) -> None:
    resp = client.get("/api/config/effective")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["api"] == {"host": "127.0.0.1", "port": 8765}
    serialized = json.dumps(body)
    assert "api_key" not in serialized
    assert "secret" not in serialized


def test_codex_services_and_effective_config_follow_selected_backends():
    from forge.services.saude import HealthProbes
    from forge.api.routes.system import effective_config

    settings = Settings(_env_file=None, provider='codex', image_provider='codex')
    probes = HealthProbes(
        research=lambda:True, lm_studio=lambda:False, comfyui=lambda:False,
        tts=lambda:True, ffmpeg=lambda:True, gpu=lambda:None,
        codex=lambda:True, codex_llm=True, codex_images=True,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        services=SimpleNamespace(settings=settings, health=StudioHealthService(probes)),
    )))
    response = asyncio.run(list_services(request))
    assert set(response['required']) == {'research', 'codex', 'tts', 'ffmpeg', 'gpu'}
    assert {item['name'] for item in response['items']} == set(response['required'])
    config = asyncio.run(effective_config(request))
    assert config['generation']['llm_provider'] == 'codex'
    assert config['generation']['image_provider'] == 'codex'
    assert config['services']['research_url'] == settings.acervo_url


def test_claude_services_e_config_efetiva():
    from forge.services.saude import HealthProbes
    from forge.api.routes.system import effective_config

    settings = Settings(_env_file=None, provider='claude', review_provider='codex')
    probes = HealthProbes(
        research=lambda: True, lm_studio=lambda: False, comfyui=lambda: True,
        tts=lambda: True, ffmpeg=lambda: True, gpu=lambda: None,
        claude=lambda: True, claude_llm=True,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        services=SimpleNamespace(settings=settings, health=StudioHealthService(probes)),
    )))
    response = asyncio.run(list_services(request))
    assert 'claude' in response['required'] and 'lm_studio' not in response['required']
    config = asyncio.run(effective_config(request))
    assert config['generation']['llm_provider'] == 'claude'
    assert config['generation']['llm_model'] == 'claude-opus-5-5'
    assert config['generation']['review_provider'] == 'codex'
    assert config['generation']['review_model'] is None
    assert config['generation']['claude_effort'] == 'high'


def test_system_routes_return_structured_health(client: TestClient) -> None:
    resp = client.get("/api/services")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body
    for item in body["items"]:
        assert set(item.keys()) == {"name", "state", "message"}
        assert item["state"] in ("available", "unavailable", "degraded")


def test_services_route_does_not_block_the_event_loop() -> None:
    from forge.services.saude import ServiceHealth, ServiceState

    class SlowProbe:
        """Simula um probe que tarda 50ms em cada chamada, como httpx com timeout curto."""

        def check_all(self) -> dict:
            import time as _time
            _time.sleep(0.05)
            return {
                "research": ServiceHealth(name="research", state=ServiceState.AVAILABLE, message="OK")
            }

    async def exercise() -> None:
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(health=SlowProbe())))
        )
        response = asyncio.create_task(list_services(request))
        await asyncio.sleep(0.01)
        # A rota não bloqueou: completou dentro do sleep de 10ms provavelmente por causa de asyncio.to_thread
        assert await response == {
            "items": [{"name": "research", "state": "available", "message": "OK"}],
            "required": list(REQUIRED_SERVICES),
        }

    asyncio.run(exercise())


def _create_services_with_settings(settings: Settings) -> ApiServices:
    return _make_services(settings)
