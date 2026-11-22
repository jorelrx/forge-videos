from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from forge.api.routes.events import _encode_event, _sse_body
from forge.api.sse import ServerSentEvent, event_payload, iter_sse_events
from forge.domain.operacao import Event


def _data_line(encoded: bytes) -> str:
    lines = [
        line for line in encoded.decode("utf-8").split("\n") if line.startswith("data: ")
    ]
    assert len(lines) == 1, encoded
    return lines[0][len("data: ") :]


def test_sse_serializes_ids() -> None:
    ev = ServerSentEvent(id="42", retry=1500, data={"kind": "stage.started"})
    assert ev.id == "42"
    assert ev.retry == 1500
    assert ev.data == {"kind": "stage.started"}


def test_sse_comment_only() -> None:
    ev = ServerSentEvent(comment="keep-alive")
    assert ev.id is None
    assert ev.data is None
    assert ev.comment == "keep-alive"


def test_sse_no_data_uses_none() -> None:
    ev = ServerSentEvent(id="99")
    assert ev.data is None


def test_idle_sse_does_not_block_the_event_loop(monkeypatch) -> None:
    monkeypatch.setattr("forge.api.routes.events.exigir_canal", lambda request, canal: canal)
    class IdleQueries:
        def events_after(self, *_args, **_kwargs):
            return []

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                services=SimpleNamespace(
                    queries=IdleQueries(),
                    settings=SimpleNamespace(
                        studio_sse_poll_seconds=0.1,
                        studio_sse_keepalive_seconds=10,
                    ),
                )
            )
        )
    )

    async def exercise() -> None:
        body = _sse_body(request, last_event_id=0, run_id=None, canal_id="UC1")
        next_event = asyncio.create_task(anext(body))
        await asyncio.sleep(0.01)
        assert not next_event.done()
        next_event.cancel()
        with suppress(asyncio.CancelledError):
            await next_event
        await body.aclose()

    asyncio.run(exercise())


# ---------------------------------------------------------------------------
# Wire format: a linha data: precisa ser JSON válido (JSON.parse no frontend)
# ---------------------------------------------------------------------------


def test_encode_event_emits_parseable_json_data_line() -> None:
    encoded = _encode_event(
        ServerSentEvent(
            id="42",
            retry=1500,
            data={"kind": "run.claimed", "message": "worker pegou a run"},
        )
    )
    assert encoded == (
        b'id: 42\nretry: 1500\n'
        b'data: {"kind": "run.claimed", "message": "worker pegou a run"}\n\n'
    )
    text = encoded.decode("utf-8")
    # regressão: o repr Python do dict (aspas simples) não é JSON
    assert "'" not in text
    assert json.loads(_data_line(encoded)) == {
        "kind": "run.claimed",
        "message": "worker pegou a run",
    }


def test_encode_event_keeps_unicode_and_newlines_parseable() -> None:
    encoded = _encode_event(
        ServerSentEvent(data={"kind": "stage.x", "message": "olá\nmundo"})
    )
    text = encoded.decode("utf-8")
    assert "olá" in text
    # sem quebra de linha crua dentro do campo data:
    assert text.count("\n") == 2
    assert json.loads(_data_line(encoded))["message"] == "olá\nmundo"


def test_encode_event_comment_only_has_no_data_line() -> None:
    assert _encode_event(ServerSentEvent(comment="keep-alive")) == b": keep-alive\n\n"


def test_event_payload_covers_frontend_contract() -> None:
    created_at = datetime(2026, 9, 14, 12, 30, 45, tzinfo=UTC)
    event = Event(
        id=7,
        run_id="run-1",
        stage_run_id="stage-1",
        work_item_id="item-1",
        kind="stage.started",
        level="info",
        message="começou",
        payload={"tentativa": 1},
        created_at=created_at,
    )
    payload = event_payload(event)
    assert payload["id"] == 7
    assert payload["run_id"] == "run-1"
    assert payload["stage_run_id"] == "stage-1"
    assert payload["work_item_id"] == "item-1"
    assert payload["kind"] == "stage.started"
    assert payload["level"] == "info"
    assert payload["message"] == "começou"
    assert payload["payload"] == {"tentativa": 1}
    assert payload["created_at"].startswith("2026-09-14T12:30:45")
    # o front faz JSON.parse(message.data): precisa passar por json.dumps
    assert json.loads(json.dumps(payload)) == payload


def test_streamed_event_encodes_full_payload_as_json() -> None:
    class FakeQueries:
        def __init__(self, events: list[Event]) -> None:
            self._events = events

        def events_after(self, cursor: int, *, run_id=None, limit=200):
            return [event for event in self._events if event.id > cursor][:limit]

    event = Event(
        id=1,
        run_id="run-1",
        kind="run.queued",
        level="info",
        message="na fila",
        payload={},
        created_at=datetime(2026, 9, 14, 12, 0, 0, tzinfo=UTC),
    )
    stream = iter_sse_events(
        FakeQueries([event]),
        cursor=0,
        run_id="run-1",
        poll_seconds=0.01,
        keepalive_seconds=10,
        sleep=lambda _: None,
    )
    sent = next(stream)
    # compatível com test_acceptance.py::test_sse_replay_after_reconnect
    assert sent.data["kind"] == "run.queued"
    encoded = _encode_event(sent)
    decoded = json.loads(_data_line(encoded))
    assert decoded["kind"] == "run.queued"
    assert decoded["id"] == 1
    assert decoded["run_id"] == "run-1"
    assert decoded["level"] == "info"
    assert decoded["message"] == "na fila"
    assert decoded["created_at"].startswith("2026-09-14T12:00:00")
    assert decoded["payload"] == {}
