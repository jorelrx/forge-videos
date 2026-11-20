import base64
import json

import httpx
import pytest


def jwt(exp=4_000_000_000, **auth):
    payload = {"exp": exp, "https://api.openai.com/auth": auth}
    return (
        "header."
        + base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        + ".signature"
    )


def save(path, access=None, refresh="refresh-secret", **extra):
    path.write_text(
        json.dumps(
            {
                "tokens": {"access_token": access or jwt(), "refresh_token": refresh},
                **extra,
            }
        ),
        encoding="utf-8",
    )


def test_fresh_oauth_store_needs_no_cli_or_network(tmp_path):
    from forge.services.codex_auth import OAuthCredentials

    path = tmp_path / "auth.json"
    token = jwt(chatgpt_account_id="workspace", chatgpt_data_residency="us")
    save(path, access=token)

    def forbidden(request):
        raise AssertionError("fresh token must not use network")

    auth = OAuthCredentials(
        path, client=httpx.Client(transport=httpx.MockTransport(forbidden))
    )
    assert auth.access_token() == token
    assert "refresh-secret" not in repr(auth)


@pytest.mark.parametrize(
    "contents",
    ["not json", "[]", '{"OPENAI_API_KEY":"paid"}', '{"tokens":{"access_token":0}}'],
)
def test_invalid_store_fails_closed(tmp_path, contents):
    from forge.services.codex_auth import CodexAuthError, OAuthCredentials

    path = tmp_path / "auth.json"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(CodexAuthError, match="forge auth codex login"):
        OAuthCredentials(path).access_token()


def test_expired_token_rotates_atomically_and_preserves_store(tmp_path):
    from forge.services.codex_auth import OAuthCredentials

    path = tmp_path / "auth.json"
    save(path, access=jwt(exp=1), auth_mode="chatgpt", extra={"keep": True})
    calls = []

    def refresh(request):
        calls.append(request)
        assert str(request.url) == "https://auth.openai.com/oauth/token"
        assert json.loads(request.content)["refresh_token"] == "refresh-secret"
        return httpx.Response(
            200,
            json={"access_token": jwt(), "refresh_token": "rotated", "id_token": "id"},
        )

    auth = OAuthCredentials(
        path, client=httpx.Client(transport=httpx.MockTransport(refresh))
    )
    assert auth.access_token() == jwt()
    assert auth.access_token() == jwt()
    assert len(calls) == 1
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["tokens"]["refresh_token"] == "rotated"
    assert stored["extra"] == {"keep": True}
    assert stored["auth_mode"] == "chatgpt"
    assert isinstance(stored["last_refresh"], str), (
        "Codex CLI requer timestamp ISO-8601, não float"
    )


def test_expired_unrefreshable_store_requires_login(tmp_path):
    from forge.services.codex_auth import CodexAuthError, OAuthCredentials

    path = tmp_path / "auth.json"
    save(path, access=jwt(exp=1), refresh=None)
    with pytest.raises(CodexAuthError, match="login"):
        OAuthCredentials(path).access_token()


def test_refresh_failure_does_not_leak_or_replace_credentials(tmp_path):
    from forge.services.codex_auth import CodexAuthError, OAuthCredentials

    path = tmp_path / "auth.json"
    save(path, access=jwt(exp=1))
    before = path.read_bytes()
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(401, json={"error": "refresh-secret"})
        )
    )
    with pytest.raises(CodexAuthError) as error:
        OAuthCredentials(path, client=client).access_token()
    assert "refresh-secret" not in str(error.value)
    assert path.read_bytes() == before


def test_headers_use_forge_identity_and_account_residency():
    from forge.services.codex_auth import request_headers

    token = jwt(chatgpt_account_id="workspace", chatgpt_compute_residency="eu")
    headers = request_headers(token)
    assert headers["originator"] == "forge-videos"
    assert headers["User-Agent"].startswith("ForgeVideos/")
    assert headers["Authorization"] == f"Bearer {token}"
    assert headers["ChatGPT-Account-ID"] == "workspace"
    assert headers["x-openai-internal-codex-residency"] == "eu"


def test_pkce_callback_state_is_required():
    from forge.services.codex_auth import CodexAuthError, validate_callback

    assert (
        validate_callback("/auth/callback?code=good&state=expected", "expected")
        == "good"
    )
    for query in (
        "/auth/callback?code=bad&state=wrong",
        "/auth/callback?code=bad",
        "/auth/callback?state=expected&error=denied",
        "/auth/callback?code=bad&state=%C3%A1",
    ):
        with pytest.raises(CodexAuthError):
            validate_callback(query, "expected")


def test_login_has_pkce_and_saves_only_valid_exchanged_tokens(tmp_path):
    import threading
    from urllib.parse import parse_qs, urlsplit

    from forge.services.codex_auth import OAuthCredentials

    opened = []
    callbacks = []

    def browser(url):
        params = parse_qs(urlsplit(url).query)
        opened.append(params)
        assert params["code_challenge_method"] == ["S256"]
        assert params["scope"] == ["openid profile email offline_access"]

        def callback():
            response = httpx.get(
                params["redirect_uri"][0]
                + "?code=authorization-code&state="
                + params["state"][0],
                timeout=5,
            )
            assert response.status_code == 200

        thread = threading.Thread(target=callback)
        callbacks.append(thread)
        thread.start()
        return True

    def exchange(request):
        form = parse_qs(request.content.decode())
        assert form["grant_type"] == ["authorization_code"]
        assert form["code"] == ["authorization-code"]
        assert len(form["code_verifier"][0]) >= 43
        return httpx.Response(
            200,
            json={
                "access_token": jwt(),
                "refresh_token": "new-refresh",
                "id_token": "id",
            },
        )

    path = tmp_path / "new/auth.json"
    auth = OAuthCredentials(
        path, client=httpx.Client(transport=httpx.MockTransport(exchange))
    )
    auth.login(timeout=5, open_browser=browser)
    for thread in callbacks:
        thread.join(timeout=5)
    assert auth.access_token() == jwt()
    assert len(opened) == 1
    assert json.loads(path.read_text())["tokens"]["refresh_token"] == "new-refresh"
