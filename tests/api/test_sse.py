from forge.api.sse import ServerSentEvent


def test_sse_serializes_ids():
    ev = ServerSentEvent(id="42", retry=1500, data={"kind": "stage.started"})
    assert ev.id == "42"
