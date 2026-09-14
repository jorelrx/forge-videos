from __future__ import annotations

from fastapi import APIRouter

from forge.api.sse import iter_sse_events, ServerSentEvent
from forge.api.contracts import EventPage

events_router = APIRouter()


@events_router.get("/runs/{run_id}/events")
async def event_history(run_id: str, limit: int = 100, before_id: int | None = None) -> EventPage:
    return EventPage(items=[], next_before_id=None)


@events_router.get("/events/stream")
async def events_stream(last_event_id: int = 0, run_id: str | None = None):
    # SSE stream stub — real stream uses iter_sse_events with EventSourceResponse
    return {"cursor": last_event_id}
