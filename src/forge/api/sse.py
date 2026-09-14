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


_EVENT_FIELDS = (
    "id",
    "run_id",
    "stage_run_id",
    "work_item_id",
    "kind",
    "level",
    "message",
    "payload",
    "created_at",
)


def event_payload(event: Any) -> dict[str, Any]:
    """Payload JSON-serializável do evento de domínio para a linha ``data:``.

    O frontend faz ``JSON.parse(message.data)`` e lê ``id``/``created_at``/
    ``kind``/``level``/``message``; por isso o dicionário precisa cobrir o
    contrato ``StudioEvent`` inteiro. ``model_dump(mode="json")`` converte o
    ``created_at`` (datetime consciente de UTC) em string ISO.
    """
    model_dump = getattr(event, "model_dump", None)
    if callable(model_dump):
        return dict(model_dump(mode="json"))
    payload = {field: getattr(event, field, None) for field in _EVENT_FIELDS}
    payload["created_at"] = str(payload["created_at"]) if payload["created_at"] else None
    return payload


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
                    data=event_payload(event),
                )
            idle_for = 0.0
            continue
        sleep(poll_seconds)
        idle_for += poll_seconds
        if idle_for >= keepalive_seconds:
            idle_for = 0.0
            yield ServerSentEvent(comment="keep-alive")
