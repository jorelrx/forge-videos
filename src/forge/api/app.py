from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from forge.api.errors import ApiError
from forge.api.routes import runs


@dataclass(frozen=True)
class ApiServices:
    settings: Any
    commands: Any
    queries: Any
    git_commit: str
    workflow_version: int = 1


def build_api_services(settings: Any) -> ApiServices:
    return ApiServices(
        settings=settings,
        commands=None,
        queries=None,
        git_commit="scaffold",
    )


def create_app(services: ApiServices | None = None) -> FastAPI:
    from forge.infrastructure.config import get_settings
    resolved = services or build_api_services(get_settings())
    app = FastAPI(title="Forge Video Studio", version="1")
    app.state.services = resolved
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:3100", "http://localhost:3100"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=[
            "Content-Type", "Idempotency-Key", "Last-Event-ID", "Range"
        ],
    )
    app.include_router(runs.runs_router, prefix="/api")
    return app
