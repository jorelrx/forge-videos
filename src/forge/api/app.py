from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from forge.api.errors import ApiError, ApiErrorDetail, transition_error, not_found, validation_error
from forge.api.routes import insights
from forge.api.routes import runs
from forge.api.routes import events
from forge.api.routes import artifacts
from forge.api.routes import system
from forge.api.routes import publication
from forge.api.routes import youtube
from forge.api.routes import sessao
from forge.services.sessao_studio import SessaoStudio, GoogleOIDC
from forge.services.maquina_estados import TransicaoInvalida
from forge.repositories.comandos import IdempotencyConflict
from forge.repositories.connection import Database
from forge.repositories.schema import init_db
from forge.repositories.migracao_producao_canal import vincular_publicacoes_legadas
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
    # Publicação no YouTube; `None` cria o padrão a partir de `settings`.
    publicador: Any = None
    # Canais do YouTube e login pelo painel; `None` cria o padrão.
    youtube: Any = None
    oidc: Any = None


def build_api_services(settings: Any) -> ApiServices:
    from forge.infrastructure.config import get_settings
    s = settings if settings is not None else get_settings()
    db = Database(s.studio_db_path)
    init_db(db)
    vincular_publicacoes_legadas(db, s.studio_runs_dir)
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
    app.state.tentativas_youtube = {}
    app.state.sessoes = SessaoStudio(resolved.commands.db)
    app.state.oidc = resolved.oidc or GoogleOIDC(resolved.settings)

    @app.exception_handler(KeyError)
    async def key_error(request, exc):
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "not_found", "message": str(exc)}},
        )

    @app.exception_handler(TransicaoInvalida)
    async def transition_invalid(request, exc):
        # Mesmo código de `errors.transition_error`: a rota e o handler de
        # aplicação sinalizam a MESMA condição, e o painel decide pela chave.
        return JSONResponse(
            status_code=409,
            content={"error": {"code": "transition_invalid", "message": str(exc)}},
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

    @app.middleware("http")
    async def seguranca_studio(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and path not in {"/api/sessao/google", sessao.CALLBACK}:
            chave = request.cookies.get(sessao.COOKIE)
            if not chave or not app.state.sessoes.pessoa(chave):
                return JSONResponse({"error": {"code": "unauthorized", "message": "Entre no Studio"}},
                                    status_code=401, headers={"Cache-Control": "no-store"})
            if (request.method not in {"GET", "HEAD", "OPTIONS"}
                    and request.headers.get("origin") != resolved.settings.studio_public_origin):
                return JSONResponse({"error": {"code": "origin", "message": "Origem inválida"}},
                                    status_code=403, headers={"Cache-Control": "no-store"})
        response = await call_next(request)
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "private, no-store, no-transform"
            response.headers["Referrer-Policy"] = "no-referrer"
        return response

    app.include_router(insights.insights_router, prefix="/api")
    app.include_router(runs.runs_router, prefix="/api")
    app.include_router(events.events_router, prefix="/api")
    app.include_router(artifacts.artifacts_router, prefix="/api")
    app.include_router(system.system_router, prefix="/api")
    app.include_router(publication.publication_router, prefix="/api")
    app.include_router(youtube.youtube_router, prefix="/api")
    app.include_router(sessao.sessao_router, prefix="/api")
    return app
