from __future__ import annotations

from collections.abc import Iterator, Callable
from typing import Any


class ServerSentEvent:
    def __init__(self, *, id: str | None = None, retry: int | None = None,
                 data: dict | None = None, comment: str | None = None) -> None:
        self.id = id
        self.retry = retry
        self.data = data
        self.comment = comment


def iter_sse_events(
    queries,
    *,
    cursor: int,
    run_id: str | None,
    poll_seconds: float,
    keepalive_seconds: float,
    sleep: Callable[[float], None] = __import__("time").sleep,
) -> Iterator[ServerSentEvent]:
    last_id = cursor
    idle_for = 0.0
    while True:
        events = queries.events_after(last_id, run_id=run_id, limit=200)
        if events:
            for event in events:
                if event.id <= last_id:
                    continue
                last_id = event.id
                yield ServerSentEvent(
                    id=str(event.id),
                    retry=1500,
                    data={"kind": event.kind, "message": event.message},
                )
            idle_for = 0.0
            continue
        sleep(poll_seconds)
        idle_for += poll_seconds
        if idle_for >= keepalive_seconds:
            idle_for = 0.0
            yield ServerSentEvent(comment="keep-alive")
