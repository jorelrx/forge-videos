from __future__ import annotations

from fastapi import APIRouter, Request
from forge.api.contracts import CreateVideoRequest

runs_router = APIRouter()


@runs_router.post("/videos")
async def create_video(request: Request):
    return {"video": {}, "run": {}}


@runs_router.get("/queue")
async def get_queue():
    return []


@runs_router.get("/runs")
async def list_runs():
    return {"items": [], "total": 0, "limit": 50, "offset": 0}


@runs_router.get("/runs/{run_id}")
async def get_run(run_id: str):
    return {}


@runs_router.post("/runs/{run_id}/pause")
async def pause_run(run_id: str, request: Request):
    return {"id": "cmd-1"}


@runs_router.post("/runs/{run_id}/resume")
async def resume_run(run_id: str, request: Request):
    return {"id": "cmd-2"}


@runs_router.post("/runs/{run_id}/stages/{stage}/retry")
async def retry_stage(run_id: str, stage: str, request: Request):
    return {"id": "cmd-3"}
