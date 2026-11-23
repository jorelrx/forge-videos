"""Preflight check tests."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from forge.infrastructure.config import Settings
from forge.services.preflight import (
    PreflightCheck,
    PreflightReport,
    check_preflight,
)


def test_codex_preflight_checks_chatgpt_without_unused_local_services(tmp_path, monkeypatch):
    checked = []
    def service(name, *args, **kwargs):
        checked.append(name)
        return PreflightCheck(name=name, state='passed', message='OK', action='')
    monkeypatch.setattr('forge.services.preflight._check_service', service)
    calls = []
    def runner(argv, **kwargs):
        calls.append(argv)
        return MagicMock(returncode=0, stdout='', stderr='Logged in using ChatGPT')
    settings = _settings(tmp_path).model_copy(update={'provider':'codex', 'image_provider':'codex', 'codex_transport':'cli'})
    report = check_preflight(settings, runner=runner, which=lambda _:None, path_exists=lambda _:True)
    assert checked == ['research']
    assert next(c for c in report.checks if c.name == 'codex').state == 'passed'
    assert [settings.codex_bin, 'login', 'status'] in calls


def test_codex_preflight_rejects_api_key_login(tmp_path, monkeypatch):
    monkeypatch.setattr('forge.services.preflight._check_service', lambda name,*a,**kw:PreflightCheck(name,'passed','',''))
    settings = _settings(tmp_path).model_copy(update={'image_provider':'codex', 'codex_transport':'cli'})
    report = check_preflight(settings, runner=lambda *a,**kw:MagicMock(returncode=0,stdout='Logged in using an API key',stderr=''), which=lambda _:None, path_exists=lambda _:True)
    assert next(c for c in report.checks if c.name == 'codex').state == 'failed'


def _runner_claude(saida_sonda: dict):
    import json as _json

    def runner(argv, **kwargs):
        if argv[1:] == ['auth', 'status']:
            return MagicMock(returncode=0, stdout=_json.dumps({'loggedIn': True, 'authMethod': 'claude.ai'}), stderr='')
        if '-p' in argv:
            return MagicMock(returncode=1 if saida_sonda.get('is_error') else 0,
                             stdout=_json.dumps(saida_sonda), stderr='')
        return MagicMock(returncode=0, stdout='', stderr='')
    return runner


def test_claude_preflight_prova_a_sessao_com_chamada_real(tmp_path, monkeypatch):
    checked = []
    monkeypatch.setattr('forge.services.preflight._check_service',
                        lambda name, *a, **kw: checked.append(name) or PreflightCheck(name, 'passed', '', ''))
    settings = _settings(tmp_path).model_copy(update={'provider': 'claude', 'image_provider': 'codex',
                                                      'codex_transport': 'cli', 'claude_runs_dir': tmp_path / 'c'})
    runner = _runner_claude({'is_error': False, 'result': 'ok'})
    report = check_preflight(settings, runner=runner, which=lambda _: None, path_exists=lambda _: True)
    assert 'lm_studio' not in checked
    assert next(c for c in report.checks if c.name == 'claude').state == 'passed'


def test_claude_preflight_reprova_sessao_expirada_mesmo_com_status_logado(tmp_path, monkeypatch):
    monkeypatch.setattr('forge.services.preflight._check_service', lambda name, *a, **kw: PreflightCheck(name, 'passed', '', ''))
    settings = _settings(tmp_path).model_copy(update={'provider': 'claude', 'claude_runs_dir': tmp_path / 'c'})
    runner = _runner_claude({'is_error': True, 'result': 'Failed to authenticate: OAuth session expired'})
    report = check_preflight(settings, runner=runner, which=lambda _: None, path_exists=lambda _: True)
    check = next(c for c in report.checks if c.name == 'claude')
    assert check.state == 'failed'
    assert 'claude auth login' in check.action


def test_revisor_claude_tambem_e_conferido(tmp_path, monkeypatch):
    monkeypatch.setattr('forge.services.preflight._check_service', lambda name, *a, **kw: PreflightCheck(name, 'passed', '', ''))
    settings = _settings(tmp_path).model_copy(update={'provider': 'codex', 'review_provider': 'claude',
                                                      'codex_transport': 'cli', 'claude_runs_dir': tmp_path / 'c'})
    runner = _runner_claude({'is_error': False, 'result': 'ok'})
    report = check_preflight(settings, runner=runner, which=lambda _: None, path_exists=lambda _: True)
    assert next(c for c in report.checks if c.name == 'claude').state == 'passed'


def _settings(tmp_path: Path) -> Settings:
    audio = tmp_path / "audio"
    audio.mkdir()
    return Settings(
        _env_file=None,
        audio_generate_dir=audio,
        tts_server_binary=audio / "bin.exe",
        tts_model=audio / "model.gguf",
        tts_voice_reference=audio / "voice.wav",
        studio_db_path=tmp_path / "data" / "forge.db",
        gaps_file=tmp_path / "gaps.txt",
        respostas_ruins_file=tmp_path / "respostas.jsonl",
    )


class TestPreflightCheckStates:
    def test_states_are_passed_warning_failed(self) -> None:
        # The three allowed state values for a PreflightCheck.
        assert PreflightCheck(name="a", state="passed", message="ok", action="").state == "passed"
        assert PreflightCheck(name="b", state="warning", message="maybe", action="").state == "warning"
        assert PreflightCheck(name="c", state="failed", message="no", action="").state == "failed"


class TestPreflightReportOk:
    @pytest.mark.parametrize(
        "states,expected_ok",
        [
            ([], True),
            (["passed"], True),
            (["passed", "warning"], True),
            (["warning"], True),
            (["passed", "failed"], False),
            (["failed"], False),
            (["passed", "warning", "failed"], False),
        ],
    )
    def test_ok_is_true_when_no_failed(self, states: list[str], expected_ok: bool) -> None:
        checks = [PreflightCheck(name=f"c{i}", state=s, message="", action="") for i, s in enumerate(states)]
        report = PreflightReport(checks=checks)
        assert report.ok is expected_ok

    def test_checks_is_accessible(self) -> None:
        checks = [PreflightCheck(name="x", state="passed", message="", action="")]
        report = PreflightReport(checks=checks)
        assert len(report.checks) == 1
        assert report.checks[0].name == "x"


class TestCheckPreflight:
    def test_python_312_plus_passes(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)

        def fake_runner(cmd, *args, **kwargs):
            result = MagicMock()
            result.stdout = "Python 3.13.1\n"
            result.stderr = ""
            return result

        report = check_preflight(s, runner=fake_runner, which=shutil.which, path_exists=lambda p: False)
        check = next(c for c in report.checks if c.name == "python")
        assert check.state == "passed"

    def test_python_below_312_fails(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)

        def fake_runner(cmd, *args, **kwargs):
            result = MagicMock()
            result.stdout = "Python 3.11.0\n"
            result.stderr = ""
            return result

        report = check_preflight(s, runner=fake_runner, which=shutil.which, path_exists=lambda p: False)
        check = next(c for c in report.checks if c.name == "python")
        assert check.state == "failed"

    def test_node_209_plus_passes(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)

        def fake_runner(cmd, *args, **kwargs):
            result = MagicMock()
            result.stdout = "v20.17.0\n"
            result.stderr = ""
            return result

        report = check_preflight(s, runner=fake_runner, which=shutil.which, path_exists=lambda p: False)
        check = next(c for c in report.checks if c.name == "node")
        assert check.state == "passed"

    def test_node_below_209_fails(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)

        def fake_runner(cmd, *args, **kwargs):
            result = MagicMock()
            result.stdout = "v20.8.0\n"
            result.stderr = ""
            return result

        report = check_preflight(s, runner=fake_runner, which=shutil.which, path_exists=lambda p: False)
        check = next(c for c in report.checks if c.name == "node")
        assert check.state == "failed"

    def test_uv_available_passes(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)

        def fake_which(cmd):
            if cmd == "uv":
                return "/usr/bin/uv"
            return None

        report = check_preflight(s, runner=lambda *a, **k: MagicMock(), which=fake_which, path_exists=lambda p: False)
        check = next(c for c in report.checks if c.name == "uv")
        assert check.state == "passed"

    def test_uv_missing_fails(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)

        def fake_which(cmd):
            return None

        report = check_preflight(s, runner=lambda *a, **k: MagicMock(), which=fake_which, path_exists=lambda p: False)
        check = next(c for c in report.checks if c.name == "uv")
        assert check.state == "failed"

    def test_ffmpeg_ffprobe_in_path_passes(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)

        def fake_which(cmd):
            if cmd in ("ffmpeg", "ffprobe"):
                return f"/usr/bin/{cmd}"
            return None

        report = check_preflight(s, runner=lambda *a, **k: MagicMock(), which=fake_which, path_exists=lambda p: False)
        check = next(c for c in report.checks if c.name == "ffmpeg")
        assert check.state == "passed"

    def test_ffprobe_missing_fails(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)

        def fake_which(cmd):
            if cmd == "ffmpeg":
                return "/usr/bin/ffmpeg"
            return None

        report = check_preflight(s, runner=lambda *a, **k: MagicMock(), which=fake_which, path_exists=lambda p: False)
        check = next(c for c in report.checks if c.name == "ffmpeg")
        assert check.state == "failed"

    def test_tts_paths_exist_passes(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        audio = tmp_path / "audio"
        (audio / "bin.exe").touch()
        (audio / "model.gguf").touch()
        (audio / "voice.wav").touch()

        report = check_preflight(s, runner=lambda *a, **k: MagicMock(), which=lambda c: None, path_exists=lambda p: True)
        check = next(c for c in report.checks if c.name == "tts")
        assert check.state == "passed"

    def test_tts_paths_missing_fails(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)

        def fake_path_exists(p):
            return False

        report = check_preflight(s, runner=lambda *a, **k: MagicMock(), which=lambda c: None, path_exists=fake_path_exists)
        check = next(c for c in report.checks if c.name == "tts")
        assert check.state == "failed"

    def test_tts_exige_binario_do_servidor(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        faltando = s.resolved_tts_server_binary

        report = check_preflight(
            s, runner=lambda *a, **k: MagicMock(), which=lambda c: None,
            path_exists=lambda p: Path(p) != faltando,
        )
        check = next(c for c in report.checks if c.name == "tts")
        assert check.state == "failed"
        assert "tts_server_binary" in check.message

    def test_web_node_modules_exists_passes(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        (tmp_path / "web" / "node_modules").mkdir(parents=True)

        report = check_preflight(
            s,
            runner=lambda *a, **k: MagicMock(),
            which=lambda c: None,
            path_exists=lambda p: True,
        )
        check = next(c for c in report.checks if c.name == "web")
        assert check.state == "passed"

    def test_web_node_modules_missing_fails(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)

        def fake_path_exists(p):
            return False

        report = check_preflight(
            s,
            runner=lambda *a, **k: MagicMock(),
            which=lambda c: None,
            path_exists=fake_path_exists,
        )
        check = next(c for c in report.checks if c.name == "web")
        assert check.state == "failed"

    def test_external_service_available_is_warning(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        s = _settings(tmp_path)

        def fake_get(url, timeout=2.0):
            result = MagicMock()
            result.status_code = 200
            return result

        httpx_mock = MagicMock()
        httpx_mock.get = fake_get
        monkeypatch.setitem(__import__("sys").modules, "httpx", httpx_mock)

        import forge.services.preflight as pf
        original_httpx = pf.httpx
        pf.httpx = httpx_mock
        try:
            report = check_preflight(
                s,
                runner=lambda *a, **k: MagicMock(),
                which=lambda c: "/usr/bin/uv",
                path_exists=lambda p: True,
            )
            research_check = next(c for c in report.checks if c.name == "research")
            assert research_check.state == "warning"
        finally:
            pf.httpx = original_httpx

    def test_external_service_unavailable_is_warning(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        s = _settings(tmp_path)

        import httpx as real_httpx

        def fake_get(url, timeout=2.0):
            raise real_httpx.ConnectError("refused")

        httpx_mock = MagicMock()
        httpx_mock.get = fake_get
        httpx_mock.ConnectError = real_httpx.ConnectError

        import forge.services.preflight as pf
        original_httpx = pf.httpx
        pf.httpx = httpx_mock
        try:
            report = check_preflight(
                s,
                runner=lambda *a, **k: MagicMock(),
                which=lambda c: "/usr/bin/uv",
                path_exists=lambda p: True,
            )
            research_check = next(c for c in report.checks if c.name == "research")
            assert research_check.state == "warning"
        finally:
            pf.httpx = original_httpx

    def test_report_ok_false_when_any_fails(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)

        def fake_which(cmd):
            return None  # uv missing

        report = check_preflight(s, runner=lambda *a, **k: MagicMock(), which=fake_which, path_exists=lambda p: True)
        assert report.ok is False

    def test_report_ok_true_when_all_pass_or_warn(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        s = _settings(tmp_path)
        audio = tmp_path / "audio"
        (audio / "bin.exe").touch()
        (audio / "model.gguf").touch()
        (audio / "voice.wav").touch()
        (tmp_path / "web" / "node_modules").mkdir(parents=True)

        def fake_which(cmd):
            return f"/usr/bin/{cmd}"

        def fake_runner(cmd, *args, **kwargs):
            result = MagicMock()
            result.stderr = ""
            if cmd[0] == "node":
                result.stdout = "v20.17.0\n"
            else:
                result.stdout = "Python 3.13.1\n"
            return result

        def fake_get(url, timeout=2.0):
            raise Exception("not running")

        httpx_mock = MagicMock()
        httpx_mock.get = fake_get

        import forge.services.preflight as pf
        original_httpx = pf.httpx
        pf.httpx = httpx_mock
        try:
            report = check_preflight(
                s,
                runner=fake_runner,
                which=fake_which,
                path_exists=lambda p: True,
            )
            assert report.ok is True
        finally:
            pf.httpx = original_httpx

    def test_checks_contains_all_expected_names(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        report = check_preflight(
            s,
            runner=lambda *a, **k: MagicMock(),
            which=lambda c: None,
            path_exists=lambda p: True,
        )
        names = {c.name for c in report.checks}
        assert "python" in names
        assert "node" in names
        assert "uv" in names
        assert "ffmpeg" in names
        assert "tts" in names
        assert "web" in names
        assert "research" in names
        assert "lm_studio" in names
        assert "comfyui" in names
