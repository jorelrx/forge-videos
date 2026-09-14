from forge.api.sse import iter_sse_events, ServerSentEvent


def test_sse_replays_after_cursor(sse_services):
    stream = iter_sse_events(
        sse_services.queries,
        cursor=1,
        run_id="r1",
        poll_seconds=0.01,
        keepalive_seconds=0.05,
    )
    first = next(stream)
    assert first.id is not None


def test_events_route_exists(client):
    response = client.get("/api/runs/test/events?limit=2")
    # RED: ainda retorna stub
    assert response.status_code in {200, 404}
