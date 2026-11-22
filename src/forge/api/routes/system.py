from forge.api.acesso import autorizar_producao
from fastapi import Depends, APIRouter, Request
from forge.services.saude import StudioHealthService

import asyncio

system_router = APIRouter(dependencies=[Depends(autorizar_producao)])

@system_router.get("/services")
async def list_services(request: Request) -> dict:
    """Todos os serviços que o Forge conhece, habilitados ou não.

    `enabled`/`usos` dizem se a configuração atual usa o serviço e em que
    etapa; `state` diz se ele responde. `required` são os habilitados.
    """
    health = request.app.state.services.health
    checks = await asyncio.to_thread(health.check_all)
    items = [
        {
            "name": item.name,
            "state": item.state,
            "message": item.message,
            "latency_ms": item.latency_ms,
            "enabled": item.enabled,
            "usos": item.usos,
        }
        for item in checks.values()
    ]
    return {
        "items": items,
        "required": sorted(item.name for item in checks.values() if item.enabled),
    }


@system_router.get("/config/effective")
async def effective_config(request: Request) -> dict:
    settings = request.app.state.services.settings
    return {
        "api": {
            "host": "127.0.0.1",
            "port": settings.studio_api_port,
        },
        "worker": {
            "lease_seconds": settings.worker_lease_seconds,
            "heartbeat_seconds": settings.worker_heartbeat_seconds,
        },
        "generation": {
            "llm_provider": settings.provider,
            "llm_model": settings.resolved_model,
            "review_provider": settings.review_provider,
            "review_model": settings.review_model,
            "claude_effort": settings.claude_effort,
            "image_provider": settings.image_provider,
            "codex_model": settings.codex_model,
            "codex_transport": settings.codex_transport,
            "codex_image_model": settings.codex_image_model,
            "codex_image_quality": settings.codex_image_quality,
        },

    }
