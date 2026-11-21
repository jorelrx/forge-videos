import json
from pathlib import Path

import httpx
import pytest

from forge.infrastructure.config import Settings


class Auth:
    def access_token(self):
        return "oauth-test-secret"


def completed(text="OK", **extra):
    return {
        "type": "response.completed",
        "response": {
            "id": "resp-test",
            "model": "gpt-6.1-sol",
            "status": "completed",
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": text}]}
            ],
            "usage": {"input_tokens": 5, "output_tokens": 1},
            **extra,
        },
    }


def sse(events):
    return "".join("data: " + json.dumps(event) + "\n\n" for event in events).encode()


def test_native_default_and_forge_owned_auth_store():
    settings = Settings(_env_file=None, provider="codex")
    assert settings.codex_transport == "native"
    assert settings.resolved_model == "gpt-6.1-sol"
    assert settings.codex_auth_file == Path.home() / ".forge/codex/auth.json"
    assert settings.codex_image_model == "gpt-image-2"
    assert settings.codex_image_quality == "medium"


def test_native_text_preserves_roles_exact_model_and_safe_logs(tmp_path):
    from forge.services.codex_native import CodexNative

    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(200, content=sse([completed()]))

    settings = Settings(_env_file=None, codex_runs_dir=tmp_path)
    native = CodexNative(
        settings,
        auth=Auth(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    response = native.chat(
        [
            {"role": "system", "content": "Regra."},
            {"role": "user", "content": "Olá"},
            {"role": "assistant", "content": "Oi"},
            {"role": "user", "content": "OK?"},
        ],
        model="gpt-6.1-sol",
        timeout=10,
    )
    assert response.text == "OK"
    assert response.model == "gpt-6.1-sol"
    body = json.loads(sent[0].content)
    assert body["model"] == "gpt-6.1-sol"
    assert body["instructions"] == "Regra."
    assert [m["role"] for m in body["input"]] == ["user", "assistant", "user"]
    assert body["store"] is False and body["stream"] is True and body["tools"] == []
    assert "temperature" not in body and "max_output_tokens" not in body
    assert sent[0].headers["originator"] == "forge-videos"
    logs = "\n".join(
        p.read_text(encoding="utf-8")
        for p in response.work_dir.iterdir()
        if p.is_file()
    )
    assert "oauth-test-secret" not in logs
    assert response.usage["output_tokens"] == 1


def make_native(tmp_path, handler):
    from forge.services.codex_native import CodexNative

    return CodexNative(
        Settings(_env_file=None, codex_runs_dir=tmp_path),
        auth=Auth(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_schema_is_enforced_by_remote_and_validated_locally(tmp_path):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, content=sse([completed('{"answer":"sim"}')]))

    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string", "default": "x"}},
    }
    result = make_native(tmp_path, handler).chat(
        [{"role": "user", "content": "sim"}],
        model="gpt-6.1-sol",
        timeout=5,
        schema=schema,
    )
    assert result.text == '{"answer":"sim"}'
    format = sent[0]["text"]["format"]
    assert format["type"] == "json_schema" and format["strict"] is True
    assert format["schema"]["additionalProperties"] is False
    assert format["schema"]["required"] == ["answer"]
    assert "default" not in format["schema"]["properties"]["answer"]


@pytest.mark.parametrize(
    "events",
    [
        [],
        [{"type": "response.output_text.delta", "delta": "incomplete"}],
        [completed(status="incomplete")],
        [completed(model="other-model")],
        [
            completed(
                output=[
                    {
                        "type": "message",
                        "content": [{"type": "refusal", "refusal": "no"}],
                    }
                ]
            )
        ],
        [{"type": "response.failed", "response": {"error": {"message": "failure"}}}],
        [{"type": "error", "message": "failure"}],
        [completed("")],
    ],
)
def test_incomplete_failed_refused_and_wrong_model_fail_closed(tmp_path, events):
    from forge.services.codex import CodexError

    native = make_native(tmp_path, lambda r: httpx.Response(200, content=sse(events)))
    with pytest.raises(CodexError):
        native.chat(
            [{"role": "user", "content": "prompt"}], model="gpt-6.1-sol", timeout=5
        )
    assert not list(tmp_path.rglob("response.txt"))


@pytest.mark.parametrize(
    "status,error_type",
    [
        (400, "CodexError"),
        (401, "CodexAuthError"),
        (403, "CodexAuthError"),
        (429, "CodexUsageLimitError"),
    ],
)
def test_http_errors_are_typed_without_token_leak_or_retry(
    tmp_path, status, error_type
):
    from forge.services.codex import CodexError

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status, json={"error": {"message": "upstream oauth-test-secret"}}
        )

    with pytest.raises(CodexError) as error:
        make_native(tmp_path, handler).chat(
            [{"role": "user", "content": "prompt"}], model="gpt-6.1-sol", timeout=5
        )
    assert type(error.value).__name__ == error_type
    assert "oauth-test-secret" not in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "event",
    [
        {
            "type": "response.failed",
            "response": {
                "error": {"code": "usage_limit_reached", "message": "Quota exhausted"}
            },
        },
        {
            "type": "error",
            "error": {"code": "usage_limit_reached", "message": "Quota exhausted"},
        },
    ],
)
def test_stream_quota_is_typed_even_without_usage_limit_words(tmp_path, event):
    from forge.services.codex import CodexUsageLimitError

    native = make_native(tmp_path, lambda r: httpx.Response(200, content=sse([event])))
    with pytest.raises(CodexUsageLimitError):
        native.chat(
            [{"role": "user", "content": "prompt"}], model="gpt-6.1-sol", timeout=5
        )


@pytest.mark.parametrize("recover", [True, False])
def test_stream_overload_retries_only_the_current_request(tmp_path, monkeypatch, recover):
    from forge.services import codex_native
    from forge.services.codex import CodexError

    calls = []
    delays = []
    monkeypatch.setattr(codex_native.time, "sleep", delays.append)

    def handler(request):
        calls.append(json.loads(request.content))
        event = {"type": "error", "message": "Our servers are currently overloaded. Please try again later."}
        if recover and len(calls) == 2:
            event = completed()
        return httpx.Response(200, content=sse([event]))

    native = make_native(tmp_path, handler)
    kwargs = {"model": "gpt-6.1-sol", "timeout": 15}
    messages = [{"role": "user", "content": "roteiro"}]
    if recover:
        assert native.chat(messages, **kwargs).text == "OK"
        assert delays == [2.0]
    else:
        with pytest.raises(CodexError) as error:
            native.chat(messages, **kwargs)
        assert type(error.value).__name__ == "CodexUnavailableError"
        assert delays == [2.0, 4.0]
    assert len(calls) == len(delays) + 1
    assert all(body == calls[0] for body in calls)


def test_stream_disconnect_is_explicit_and_not_retried(tmp_path):
    from forge.services.codex import CodexError

    def handler(request):
        raise httpx.ReadTimeout("connection interrupted oauth-test-secret")

    with pytest.raises(CodexError) as error:
        make_native(tmp_path, handler).chat(
            [{"role": "user", "content": "prompt"}], model="gpt-6.1-sol", timeout=5
        )
    assert "oauth-test-secret" not in str(error.value)


def test_sse_multiline_data_and_malformed_frames(tmp_path):
    from forge.services.codex import CodexError

    raw = json.dumps(completed(), indent=2)
    frame = (
        "event: response.completed\n"
        + "\n".join("data: " + line for line in raw.splitlines())
        + "\n\n"
    )
    response = make_native(
        tmp_path, lambda r: httpx.Response(200, content=frame.encode())
    ).chat([{"role": "user", "content": "prompt"}], model="gpt-6.1-sol", timeout=5)
    assert response.text == "OK"
    with pytest.raises(CodexError):
        make_native(
            tmp_path, lambda r: httpx.Response(200, content=b"data: not-json\n\n")
        ).chat([{"role": "user", "content": "prompt"}], model="gpt-6.1-sol", timeout=5)
