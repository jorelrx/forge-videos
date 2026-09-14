from fastapi import APIRouter, Request
from forge.services.saude import StudioHealthService

import asyncio

system_router = APIRouter()

REQUIRED_SERVICES = frozenset({
    "research",
    "lm_studio",
    "comfyui",
    "tts",
    "ffmpeg",
    "gpu",
})


@system_router.get("/services")
async def list_services(request: Request) -> dict:
    services = request.app.state.services
    health = services.health
    checks = await asyncio.to_thread(health.check_all)
    items = []
    for name in sorted(checks.keys()):
        item = checks[name]
        items.append({
            "name": item.name,
            "state": item.state,
            "message": item.message,
        })
    return {
        "items": items,
        "required": list(REQUIRED_SERVICES),
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
        "services": {
            "research_url": settings.acervo_url,
            "lm_studio_url": settings.lm_studio_base_url,
            "comfyui_url": settings.comfy_url,
        },
    }
