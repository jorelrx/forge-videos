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
from forge.domain.fluxo_geracao import FluxoGeracao, NovoFluxoGeracao
from forge.domain.operacao import Run, StageName
from forge.domain.editorial import DecisaoAbertura, EscolhaEditorial
from forge.services.control_plane import ControlPlaneService, TransicaoInvalida, HistoricoSomenteLeitura
from forge.services.studio_query import StudioQueryService
from forge.repositories.connection import Database
from forge.repositories.fluxos_geracao import FluxosGeracaoRepository

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
# Fluxos de geração e criação de vídeos
# ---------------------------------------------------------------------------


@runs_router.get("/fluxos-geracao")
def list_generation_flows(request: Request) -> list[FluxoGeracao]:
    return FluxosGeracaoRepository(_control(request).db).listar()


@runs_router.post("/fluxos-geracao", status_code=201)
def create_generation_flow(payload: NovoFluxoGeracao, request: Request) -> FluxoGeracao:
    return FluxosGeracaoRepository(_control(request).db).criar(payload)


@runs_router.post("/videos", status_code=201)
def create_video(payload: CreateVideoRequest, request: Request) -> CreateVideoResponse:
    commands = _control(request)
    snapshot = {"preset": payload.preset}
    if payload.revisao_editorial:
        snapshot["revisao_editorial"] = True
        if payload.referencias_editoriais and payload.referencias_editoriais.strip():
            snapshot["referencias_editoriais"] = payload.referencias_editoriais.strip()
    if payload.fluxo_geracao is not None:
        fluxo = FluxosGeracaoRepository(commands.db).obter(payload.fluxo_geracao)
        if fluxo is None:
            validation_error(f"Fluxo de geração desconhecido: {payload.fluxo_geracao}")
        snapshot["fluxo_geracao"] = fluxo.model_dump(mode="json")
    video, run = commands.enqueue_video(
        tema=payload.tema,
        tese=payload.tese,
        priority=payload.priority,
        config_snapshot=snapshot,
        workflow_version=request.app.state.services.workflow_version,
        git_commit=request.app.state.services.git_commit,
    )
    return CreateVideoResponse(
        video=video,
        run=run,
    )


@runs_router.post("/runs/{run_id}/proposta-editorial")
def select_editorial_proposal(run_id: str, payload: EscolhaEditorial, request: Request) -> Run:
    try:
        return _control(request).escolher_proposta(run_id, payload)
    except KeyError:
        not_found("run", run_id)
    except HistoricoSomenteLeitura as exc:
        read_only_error(str(exc))
    except TransicaoInvalida as exc:
        transition_error(str(exc))


@runs_router.post("/runs/{run_id}/previa-abertura")
def review_opening(run_id: str, payload: DecisaoAbertura, request: Request) -> Run:
    try:
        return _control(request).decidir_abertura(run_id, payload)
    except KeyError:
        not_found("run", run_id)
    except HistoricoSomenteLeitura as exc:
        read_only_error(str(exc))
    except TransicaoInvalida as exc:
        transition_error(str(exc))


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
