from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from forge.api.errors import ApiError, ApiErrorDetail, transition_error, not_found, validation_error
from forge.api.routes import runs
from forge.api.routes import events
from forge.api.routes import artifacts
from forge.api.routes import system
from forge.services.maquina_estados import TransicaoInvalida
from forge.repositories.comandos import IdempotencyConflict
from forge.repositories.connection import Database
from forge.repositories.schema import init_db
from forge.services.studio import ControlPlaneService
from forge.services.studio_query import StudioQueryService
from forge.services.saude import StudioHealthService, _default_probes

@dataclass(frozen=True)
class ApiServices:
    settings: Any
    commands: Any
    queries: Any
    health: Any
    git_commit: str
    workflow_version: int = 1


def build_api_services(settings: Any) -> ApiServices:
    from forge.infrastructure.config import get_settings
    s = settings if settings is not None else get_settings()
    db = Database(s.studio_db_path)
    init_db(db)
    return ApiServices(
        settings=s,
        commands=ControlPlaneService(db),
        queries=StudioQueryService(db),
        health=StudioHealthService(probes=_default_probes()),
        git_commit="scaffold",
    )


def create_app(services: ApiServices | None = None) -> FastAPI:
    from forge.infrastructure.config import get_settings

    resolved = services or build_api_services(None)
    app = FastAPI(title="Forge Video Studio", version="1")
    app.state.services = resolved

    @app.exception_handler(KeyError)
    async def key_error(request, exc):
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "not_found", "message": str(exc)}},
        )

    @app.exception_handler(TransicaoInvalida)
    async def transition_invalid(request, exc):
        return JSONResponse(
            status_code=409,
            content={"error": {"code": "invalid_transition", "message": str(exc)}},
        )

    @app.exception_handler(IdempotencyConflict)
    async def idempotency_conflict(request, exc):
        return JSONResponse(
            status_code=409,
            content={"error": {"code": "idempotency_conflict", "message": str(exc)}},
        )

    @app.exception_handler(Exception)
    async def catch_all(request, exc):
        status = getattr(exc, "status_code", 500)
        detail = getattr(exc, "detail", None)
        if detail is None:
            detail = str(exc)
        if isinstance(detail, dict):
            return JSONResponse(status_code=status, content=detail)
        return JSONResponse(
            status_code=status,
            content={"error": {"code": "error", "message": detail}},
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:3100", "http://localhost:3100"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=[
            "Content-Type",
            "Idempotency-Key",
            "Last-Event-ID",
            "Range",
        ],
    )

    app.include_router(runs.runs_router, prefix="/api")
    app.include_router(events.events_router, prefix="/api")
    app.include_router(artifacts.artifacts_router, prefix="/api")
    app.include_router(system.system_router, prefix="/api")
    return app