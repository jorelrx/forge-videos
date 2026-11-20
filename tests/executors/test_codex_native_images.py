import base64
import io
import json
from pathlib import Path

import httpx
import pytest
from PIL import Image

from forge.infrastructure.config import Settings


class Auth:
    def access_token(self):
        return "image-oauth-secret"


def image_payload():
    data = io.BytesIO()
    Image.new("RGB", (160, 90), "navy").save(data, format="PNG")
    return {
        "data": [{"b64_json": base64.b64encode(data.getvalue()).decode()}],
        "quality": "medium",
        "size": "160x90",
    }


def test_direct_image_without_agent_preserves_original_and_normalizes(tmp_path):
    from forge.executors.codex_native_images import NativeCodexImageClient

    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json=image_payload(),
            headers={"x-codex-imagegen-request-id": "image-request-id"},
        )

    client = NativeCodexImageClient(
        Settings(_env_file=None),
        auth=Auth(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    dest = tmp_path / "i001.png"
    assert client.generate("viajante entre estrelas", seed=42, dest=dest) == dest
    assert len(requests) == 1
    assert (
        str(requests[0].url)
        == "https://chatgpt.com/backend-api/codex/images/generations"
    )
    sent = json.loads(requests[0].content)
    assert sent["model"] == "gpt-image-2"
    assert sent["quality"] == "medium"
    assert sent["n"] == 1
    assert "seed" not in sent
    assert "tools" not in sent and "agent" not in sent
    with Image.open(dest) as image:
        assert image.size == (1024, 576)
    meta = client.artifact_metadata(dest)
    assert meta["codex_transport"] == "native"
    assert meta["requested_model"] == "gpt-image-2"
    assert meta["image_model"] is None  # o backend não atestou o modelo
    assert meta["reported_size"] == "160x90"
    assert meta["seed_applied"] is False
    assert meta["imagegen_request_id"] == "image-request-id"
    assert Path(meta["original_path"]).is_file()
    assert "image-oauth-secret" not in dest.with_suffix(".codex.json").read_text()


def test_cache_reused_without_auth_or_spending_and_corruption_regenerates(tmp_path):
    from forge.executors.codex_native_images import NativeCodexImageClient

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=image_payload())

    settings = Settings(_env_file=None)
    http = httpx.Client(transport=httpx.MockTransport(handler))
    dest = tmp_path / "final.png"
    first = NativeCodexImageClient(settings, auth=Auth(), client=http)
    first.generate("paisagem", dest=dest)

    class NoAuth:
        def access_token(self):
            raise AssertionError("cache válido não autentica nem gasta")

    cached = NativeCodexImageClient(settings, auth=NoAuth(), client=http)
    cached.generate("paisagem", dest=dest)
    assert cached.artifact_metadata(dest) == first.artifact_metadata(dest)
    assert len(calls) == 1
    dest.write_bytes(b"corrupt")
    first.generate("paisagem", dest=dest)
    assert len(calls) == 2
    first.generate("prompt novo", dest=dest)
    assert len(calls) == 3


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"data": [None]},
        {},
        {"data": []},
        {"data": [{"url": "https://untrusted.test/image.png"}]},
        {"data": [{"b64_json": "not-base64"}]},
        {"data": [{"b64_json": base64.b64encode(b"not an image").decode()}]},
    ],
)
def test_invalid_payload_preserves_previous_image_without_receipt(tmp_path, payload):
    from forge.executors.codex_native_images import NativeCodexImageClient
    from forge.services.codex import CodexError

    dest = tmp_path / "previous.png"
    dest.write_bytes(b"prior image")
    client = NativeCodexImageClient(
        Settings(_env_file=None),
        auth=Auth(),
        client=httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
        ),
    )
    with pytest.raises(CodexError):
        client.generate("prompt", dest=dest)
    assert dest.read_bytes() == b"prior image"
    assert not dest.with_suffix(".codex.json").exists()


def test_quota_failure_typed_and_no_retry(tmp_path):
    from forge.executors.codex_native_images import NativeCodexImageClient
    from forge.services.codex import CodexUsageLimitError

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            429, json={"error": {"message": "usage limit image-oauth-secret"}}
        )

    client = NativeCodexImageClient(
        Settings(_env_file=None),
        auth=Auth(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(CodexUsageLimitError) as error:
        client.generate("prompt", dest=tmp_path / "final.png")
    assert "image-oauth-secret" not in str(error.value)
    assert len(calls) == 1


def test_image_identity_depends_on_quality_not_host_llm():
    from forge.executors.codex_native_images import NativeCodexImageClient

    a = NativeCodexImageClient(Settings(_env_file=None))
    b = NativeCodexImageClient(Settings(_env_file=None, codex_image_quality="high"))
    c = NativeCodexImageClient(
        Settings(
            _env_file=None,
            model="different-text-model",
            codex_model="different-cli-agent",
        )
    )
    assert a.cache_key("prompt", 42) != b.cache_key("prompt", 42)
    assert a.cache_key("prompt", 42) == c.cache_key("prompt", 42)


def test_image_executor_selects_native_transport_without_cli():
    from forge.executors.codex_native_images import NativeCodexImageClient
    from forge.executors.imagens import ImageExecutor

    executor = ImageExecutor(settings=Settings(_env_file=None, image_provider="codex"))
    assert isinstance(executor.client, NativeCodexImageClient)
    assert executor.broker is None
