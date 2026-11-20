import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from forge.infrastructure.config import Settings
from forge.services.codex import CodexCLI, CodexError


def settings(tmp_path):
    return Settings(_env_file=None, codex_runs_dir=tmp_path / 'calls')


class FakeOwner:
    def __init__(self, argv, *, result='olá', events=None, exit_code=0, timeout=False):
        self.argv = argv
        self.result = result
        self.events = events if events is not None else [{'type': 'turn.completed'}]
        self.exit_code = exit_code
        self.timeout = timeout
        self.terminated = False

    def _spawn_process(self, **options):
        self.options = options
        self.prompt = options['stdin'].read()
        options['stdout'].write('\n'.join(json.dumps(e) for e in self.events))
        options['stdout'].flush()
        if self.result is not None:
            Path(self.argv[self.argv.index('--output-last-message') + 1]).write_text(self.result, encoding='utf-8')
        return self, None, None

    def wait(self, timeout=None):
        if self.timeout and timeout:
            raise subprocess.TimeoutExpired(self.argv, timeout)
        return self.exit_code

    def _terminate(self, *args, **kwargs):
        self.terminated = True


def fake_cli(tmp_path, monkeypatch, **kwargs):
    cli = CodexCLI(settings(tmp_path))
    monkeypatch.setattr(cli, 'check_auth', lambda: None)
    owners = []
    def factory(argv, **options):
        owner = FakeOwner(argv, **kwargs)
        owners.append(owner)
        return owner
    monkeypatch.setattr('forge.services.codex.SubprocessExecutor', factory)
    return cli, owners


def test_exec_uses_chatgpt_utf8_stdin_and_isolated_logs(tmp_path, monkeypatch):
    cli, owners = fake_cli(tmp_path, monkeypatch)
    monkeypatch.setenv('OPENAI_API_KEY', 'secret')
    monkeypatch.setenv('FORGE_API_KEY', 'other-secret')
    response = cli.run('Ilustração sobre resiliência', model='gpt-6-astra', timeout=30)
    owner = owners[0]
    assert response.text == 'olá'
    assert owner.prompt == 'Ilustração sobre resiliência'
    assert '--ignore-user-config' in owner.argv
    assert 'forced_login_method="chatgpt"' in owner.argv
    assert 'model_provider="openai"' in owner.argv
    assert 'web_search="disabled"' in owner.argv
    assert 'features.shell_tool=false' in owner.argv
    assert '--output-last-message' in owner.argv
    assert '--ephemeral' in owner.argv
    assert 'OPENAI_API_KEY' not in owner.options['env']
    assert 'FORGE_API_KEY' not in owner.options['env']
    assert owner.terminated
    assert (response.work_dir / 'prompt.txt').read_text(encoding='utf-8') == owner.prompt


@pytest.mark.parametrize('output,code', [('Logged in using ChatGPT', 0), ('Logged in using an API key', 0), ('Not logged in', 1)])
def test_auth_requires_chatgpt(tmp_path, monkeypatch, output, code):
    monkeypatch.setattr('forge.services.codex.subprocess.run', lambda *a, **kw: SimpleNamespace(returncode=code, stdout='', stderr=output))
    cli = CodexCLI(settings(tmp_path))
    if 'ChatGPT' in output and code == 0:
        cli.check_auth()
    else:
        with pytest.raises(CodexError, match='codex login'):
            cli.check_auth()


@pytest.mark.parametrize('events,result,code,match', [
    ([{'type': 'turn.failed', 'error': {'message': 'modelo indisponível'}}], None, 1, 'modelo indisponível'),
    ([], 'texto', 0, 'turn.completed'),
    ([{'type': 'turn.completed'}], None, 0, 'saída'),
    ([{'type': 'turn.completed'}], '   ', 0, 'saída'),
])
def test_fail_closed(tmp_path, monkeypatch, events, result, code, match):
    cli, owners = fake_cli(tmp_path, monkeypatch, events=events, result=result, exit_code=code)
    with pytest.raises(CodexError, match=match):
        cli.run('prompt', model='gpt-6-astra', timeout=10)
    assert owners[0].terminated


def test_timeout_terminates_owned_tree(tmp_path, monkeypatch):
    cli, owners = fake_cli(tmp_path, monkeypatch, timeout=True)
    with pytest.raises(CodexError, match='prazo'):
        cli.run('prompt', model='gpt-6-astra', timeout=0.1)
    assert owners[0].terminated


def test_schema_is_passed_as_file(tmp_path, monkeypatch):
    cli, owners = fake_cli(tmp_path, monkeypatch, result='{"texto":"ok"}')
    schema = {'type': 'object', 'properties': {'texto': {'type': 'string'}}}
    cli.run('prompt', model='gpt-6-astra', timeout=10, schema=schema)
    argv = owners[0].argv
    supplied = json.loads(Path(argv[argv.index('--output-schema') + 1]).read_text(encoding='utf-8'))
    assert supplied['additionalProperties'] is False
    assert supplied['required'] == ['texto']


def test_non_object_events_do_not_hide_missing_completion(tmp_path, monkeypatch):
    cli, _ = fake_cli(tmp_path, monkeypatch, events=[[], 'diagnóstico'])
    with pytest.raises(CodexError, match='turn.completed'):
        cli.run('prompt', model='gpt-6-astra', timeout=10)


@pytest.mark.parametrize('event', [
    {'type': 'error', 'message': "You've hit your usage limit. Try again at 4:00 AM."},
    {'type': 'turn.failed', 'error': {'message': "You've hit your usage limit. Try again at 4:00 AM."}},
    {'type': 'turn.failed', 'error': {'code': 'usage_limit_reached', 'message': 'Quota unavailable until 4:00 AM.'}},
])
def test_usage_limit_is_distinguished_from_item_failure(tmp_path, monkeypatch, event):
    cli, _ = fake_cli(tmp_path, monkeypatch, events=[event], result=None, exit_code=1)
    with pytest.raises(CodexError) as caught:
        cli.run('prompt', model='gpt-6-astra', timeout=10)
    assert type(caught.value).__name__ == 'CodexUsageLimitError'
    assert 'cota' in str(caught.value).lower()
    assert '4:00 AM' in str(caught.value)
    assert 'logs:' in str(caught.value)


def test_later_failure_event_does_not_hide_usage_limit(tmp_path, monkeypatch):
    cli, _ = fake_cli(tmp_path, monkeypatch, events=[
        {'type': 'error', 'message': "You've hit your usage limit."},
        {'type': 'turn.failed', 'error': {'message': 'Turn failed'}},
    ], result=None, exit_code=1)
    with pytest.raises(CodexError) as caught:
        cli.run('prompt', model='gpt-6-astra', timeout=10)
    assert type(caught.value).__name__ == 'CodexUsageLimitError'

