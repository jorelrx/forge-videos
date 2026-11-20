import asyncio
import base64
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from forge.infrastructure.config import Settings


def auth_file(tmp_path):
    path = tmp_path / "auth.json"
    token = (
        "head."
        + base64.urlsafe_b64encode(json.dumps({"exp": 4_000_000_000}).encode())
        .decode()
        .rstrip("=")
        + ".sig"
    )
    path.write_text(
        json.dumps(
            {"tokens": {"access_token": token, "refresh_token": "refresh-secret"}}
        )
    )
    return path


def test_native_preflight_does_not_execute_cli_or_probe_replaced_services(
    tmp_path, monkeypatch
):
    from forge.services.preflight import PreflightCheck, check_preflight

    checked, commands = [], []

    def service(name, *args):
        checked.append(name)
        return PreflightCheck(name, "passed", "OK", "")

    def runner(argv, **kwargs):
        commands.append(argv)
        assert argv[0] != "codex"
        return MagicMock(returncode=0, stdout="version", stderr="")

    monkeypatch.setattr("forge.services.preflight._check_service", service)
    settings = Settings(
        _env_file=None,
        provider="codex",
        image_provider="codex",
        codex_auth_file=auth_file(tmp_path),
    )
    report = check_preflight(
        settings, runner=runner, which=lambda _: None, path_exists=lambda _: True
    )
    assert checked == ["research"]
    assert next(c for c in report.checks if c.name == "codex").state == "passed"


def test_native_health_checks_credentials_without_cli(tmp_path, monkeypatch):
    from forge.services.saude import _default_probes

    monkeypatch.setattr(
        "forge.services.codex.CodexCLI.check_auth",
        lambda _: (_ for _ in ()).throw(AssertionError("CLI proibido")),
    )
    settings = Settings(
        _env_file=None, provider="codex", codex_auth_file=auth_file(tmp_path)
    )
    monkeypatch.setattr("forge.services.saude.get_settings", lambda: settings)
    assert _default_probes().codex() is True


def test_effective_config_reports_transport_and_image_settings_only():
    from forge.api.routes.system import effective_config

    settings = Settings(_env_file=None, provider="codex", image_provider="codex")
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(services=SimpleNamespace(settings=settings))
        )
    )
    generation = asyncio.run(effective_config(request))["generation"]
    assert generation["codex_transport"] == "native"
    assert generation["codex_image_model"] == "gpt-image-2"
    assert generation["codex_image_quality"] == "medium"
    assert "token" not in json.dumps(generation)


def test_auth_status_command_is_standalone_and_redacted(tmp_path, monkeypatch, capsys):
    from forge.cli import main

    settings = Settings(_env_file=None, codex_auth_file=auth_file(tmp_path))
    monkeypatch.setattr("forge.cli.get_settings", lambda: settings)
    assert main(["auth", "codex", "status"]) == 0
    output = capsys.readouterr().out
    assert "ChatGPT" in output
    assert "refresh-secret" not in output and ".sig" not in output


def test_auth_status_missing_store_fails_without_opening_browser(
    tmp_path, monkeypatch, capsys
):
    from forge.cli import main

    monkeypatch.setattr(
        "forge.cli.get_settings",
        lambda: Settings(_env_file=None, codex_auth_file=tmp_path / "absent"),
    )
    assert main(["auth", "codex", "status"]) == 1
    assert "forge auth codex login" in capsys.readouterr().err
