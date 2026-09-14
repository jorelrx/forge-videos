from __future__ import annotations

import asyncio
from contextlib import suppress
from types import SimpleNamespace

import pytest
from forge.api.routes.events import _sse_body
from forge.api.sse import ServerSentEvent


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


def test_idle_sse_does_not_block_the_event_loop() -> None:
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
        body = _sse_body(request, last_event_id=0, run_id=None)
        next_event = asyncio.create_task(anext(body))
        await asyncio.sleep(0.01)
        assert not next_event.done()
        next_event.cancel()
        with suppress(asyncio.CancelledError):
            await next_event
        await body.aclose()

    asyncio.run(exercise())
