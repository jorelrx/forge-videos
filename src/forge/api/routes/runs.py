from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Header
from pydantic import ValidationError

from forge.api.contracts import (
    CreateVideoRequest,
    CreateVideoResponse,
    RunPage,
    RunSummary,
    RunView,
    CommandResponse,
)
from forge.api.errors import transition_error, not_found, validation_error, read_only_error
from forge.api.sse import ServerSentEvent, iter_sse_events
from forge.api.ranges import parse_range, RangeNotSatisfiable, iter_file_range
from forge.domain.operacao import StageName
from forge.services.control_plane import ControlPlaneService, TransicaoInvalida, HistoricoSomenteLeitura
from forge.services.studio_query import StudioQueryService
from forge.repositories.connection import Database

runs_router = APIRouter()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _queries(request: Request) -> StudioQueryService:
    return request.app.state.services.queries


def _control(request: Request) -> ControlPlaneService:
    return request.app.state.services.commands


def _settings(request: Request):
    return request.app.state.services.settings


# ---------------------------------------------------------------------------
# POST /api/videos
# ---------------------------------------------------------------------------


@runs_router.post("/videos", status_code=201)
async def create_video(payload: CreateVideoRequest, request: Request) -> CreateVideoResponse:
    commands = _control(request)
    video, run = commands.enqueue_video(
        tema=payload.tema,
        tese=payload.tese,
        priority=payload.priority,
        config_snapshot={"preset": payload.preset},
        workflow_version=request.app.state.services.workflow_version,
        git_commit=request.app.state.services.git_commit,
    )
    return CreateVideoResponse(
        video=video,
        run=run,
    )


# ---------------------------------------------------------------------------
# GET /api/queue
# ---------------------------------------------------------------------------


@runs_router.get("/queue")
async def get_queue(request: Request) -> list[RunSummary]:
    return [
        RunSummary(**item.model_dump())
        for item in _queries(request).list_queue()
    ]


# ---------------------------------------------------------------------------
# GET /api/runs
# ---------------------------------------------------------------------------


@runs_router.get("/runs")
async def list_runs(
    request: Request,
    limit: int = 50,
    offset: int = 0,
) -> RunPage:
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    page = _queries(request).list_runs(limit=limit, offset=offset)
    return RunPage(
        items=[RunSummary(**item.model_dump()) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


# ---------------------------------------------------------------------------
# GET /api/runs/{run_id}
# ---------------------------------------------------------------------------


@runs_router.get("/runs/{run_id}")
async def get_run(run_id: str, request: Request) -> RunView:
    try:
        view = _queries(request).get_run(run_id)
    except KeyError:
        not_found("run", run_id)
    return RunView(**view.model_dump())


# ---------------------------------------------------------------------------
# POST /api/runs/{run_id}/pause
# ---------------------------------------------------------------------------


@runs_router.post("/runs/{run_id}/pause")
async def pause_run(
    run_id: str,
    request: Request,
    idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
) -> CommandResponse:
    if not idempotency_key:
        validation_error("Idempotency-Key header is required")
    try:
        command = _control(request).request_pause(run_id, idempotency_key=idempotency_key)
    except KeyError:
        not_found("run", run_id)
    except HistoricoSomenteLeitura as exc:
        read_only_error(str(exc))
    except TransicaoInvalida as exc:
        transition_error(str(exc))
    return CommandResponse(**command.model_dump())


# ---------------------------------------------------------------------------
# POST /api/runs/{run_id}/resume
# ---------------------------------------------------------------------------


@runs_router.post("/runs/{run_id}/resume")
async def resume_run(
    run_id: str,
    request: Request,
    idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
) -> CommandResponse:
    if not idempotency_key:
        validation_error("Idempotency-Key header is required")
    try:
        command = _control(request).request_resume(run_id, idempotency_key=idempotency_key)
    except KeyError:
        not_found("run", run_id)
    except HistoricoSomenteLeitura as exc:
        read_only_error(str(exc))
    except TransicaoInvalida as exc:
        transition_error(str(exc))
    return CommandResponse(**command.model_dump())


# ---------------------------------------------------------------------------
# POST /api/runs/{run_id}/stages/{stage}/retry
# ---------------------------------------------------------------------------


@runs_router.post("/runs/{run_id}/stages/{stage}/retry")
async def retry_stage(
    run_id: str,
    stage: str,
    request: Request,
    idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
) -> CommandResponse:
    if not idempotency_key:
        validation_error("Idempotency-Key header is required")
    try:
        stage_name = StageName(stage)
    except ValueError:
        validation_error(f"invalid stage name: {stage!r}")
    try:
        command = _control(request).request_retry_stage(
            run_id, stage_name, idempotency_key=idempotency_key
        )
    except KeyError:
        not_found("run", run_id)
    except HistoricoSomenteLeitura as exc:
        read_only_error(str(exc))
    except TransicaoInvalida as exc:
        transition_error(str(exc))
    return CommandResponse(**command.model_dump())
