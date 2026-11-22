from __future__ import annotations

import asyncio
import json

from forge.api.acesso import autorizar_producao, canal_da_consulta, canal_da_run
from forge.api.routes.sessao import exigir_canal
from fastapi import Depends, APIRouter, HTTPException, Request, Header
from fastapi.responses import StreamingResponse

from forge.api.contracts import EventPage
from forge.api.errors import not_found
from forge.api.sse import ServerSentEvent, event_payload
from forge.services.studio_query import StudioQueryService

events_router = APIRouter(dependencies=[Depends(autorizar_producao)])


def _queries(request: Request) -> StudioQueryService:
    return request.app.state.services.queries


# ---------------------------------------------------------------------------
# GET /api/runs/{run_id}/events
# ---------------------------------------------------------------------------


@events_router.get("/runs/{run_id}/events")
async def event_history(
    run_id: str,
    request: Request,
    limit: int = 100,
    before_id: int | None = None,
) -> EventPage:
    try:
        page = _queries(request).list_events(run_id, before_id=before_id, limit=limit)
    except KeyError:
        not_found("run", run_id)
    return EventPage(items=page.items, next_before_id=page.next_before_id)


# ---------------------------------------------------------------------------
# GET /api/events/stream  (SSE)
# ---------------------------------------------------------------------------


_ENCODE = "utf-8"


def _encode_event(event: ServerSentEvent) -> bytes:
    parts: list[str] = []
    if event.id is not None:
        parts.append(f"id: {event.id}")
    if event.retry is not None:
        parts.append(f"retry: {event.retry}")
    if event.data is not None:
        parts.append(f"data: {json.dumps(event.data, ensure_ascii=False)}")
    if event.comment is not None:
        parts.append(f": {event.comment}")
    body = "\n".join(parts) + "\n\n"
    return body.encode(_ENCODE)


async def _sse_body(request: Request, last_event_id: int, run_id: str | None, canal_id: str):
    services = request.app.state.services
    cursor = last_event_id
    idle_for = 0.0
    poll_seconds = services.settings.studio_sse_poll_seconds
    keepalive_seconds = services.settings.studio_sse_keepalive_seconds

    while True:
        try:
            await asyncio.to_thread(exigir_canal, request, canal_id)
        except HTTPException:
            return
        events = await asyncio.to_thread(
            services.queries.events_after,
            cursor,
            run_id=run_id,
            canal_id=canal_id,
            limit=200,
        )
        if events:
            for event in events:
                if event.id <= cursor:
                    continue
                cursor = event.id
                yield _encode_event(
                    ServerSentEvent(
                        id=str(event.id),
                        retry=1500,
                        data=event_payload(event),
                    )
                )
            idle_for = 0.0
            continue

        await asyncio.sleep(poll_seconds)
        idle_for += poll_seconds
        if idle_for >= keepalive_seconds:
            idle_for = 0.0
            yield _encode_event(ServerSentEvent(comment="keep-alive"))


@events_router.get("/events/stream")
async def events_stream(
    request: Request,
    last_event_id: int = 0,
    run_id: str | None = None,
    last_event_id_header: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    cursor = last_event_id
    if last_event_id_header is not None:
        try:
            cursor = int(last_event_id_header)
        except ValueError:
            cursor = 0
    canal = canal_da_run(request, run_id) if run_id else canal_da_consulta(request)
    return StreamingResponse(
        _sse_body(request, max(0, cursor), run_id, canal),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
