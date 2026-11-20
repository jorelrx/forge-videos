import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from forge.infrastructure.config import Settings
from forge.services.claude_cli import (
    ClaudeAuthError,
    ClaudeCLI,
    ClaudeError,
    ClaudeUsageLimitError,
)


def settings(tmp_path):
    return Settings(_env_file=None, claude_runs_dir=tmp_path / 'calls')


def resultado(**sobrescritas):
    base = {
        'type': 'result', 'subtype': 'success', 'is_error': False,
        'result': 'olá', 'structured_output': None, 'stop_reason': 'end_turn',
        'usage': {'input_tokens': 12, 'output_tokens': 3}, 'api_error_status': None,
    }
    base.update(sobrescritas)
    return base


class FakeOwner:
    def __init__(self, argv, *, saida=None, bruto=None, exit_code=0, timeout=False):
        self.argv = argv
        self.saida = saida if saida is not None else resultado()
        self.bruto = bruto
        self.exit_code = exit_code
        self.timeout = timeout
        self.terminated = False

    def _spawn_process(self, **options):
        self.options = options
        self.prompt = options['stdin'].read()
        options['stdout'].write(self.bruto if self.bruto is not None else json.dumps(self.saida))
        options['stdout'].flush()
        return self, None, None

    def wait(self, timeout=None):
        if self.timeout and timeout:
            raise subprocess.TimeoutExpired(self.argv, timeout)
        return self.exit_code

    def _terminate(self, *args, **kwargs):
        self.terminated = True


def fake_cli(tmp_path, monkeypatch, **kwargs):
    cli = ClaudeCLI(settings(tmp_path))
    monkeypatch.setattr(cli, 'check_auth', lambda: None)
    owners = []

    def factory(argv, **options):
        owner = FakeOwner(argv, **kwargs)
        owners.append(owner)
        return owner

    monkeypatch.setattr('forge.services.claude_cli.SubprocessExecutor', factory)
    return cli, owners


def test_argv_isolado_e_ambiente_sem_chave(tmp_path, monkeypatch):
    cli, owners = fake_cli(tmp_path, monkeypatch)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'secret')
    monkeypatch.setenv('FORGE_API_KEY', 'other-secret')
    monkeypatch.setenv('ANTHROPIC_BASE_URL', 'https://proxy.invalid')
    monkeypatch.setenv('ANTHROPIC_AUTH_TOKEN', 'token')
    response = cli.run('Escreva o gancho', system='Você é roteirista.',
                       model='claude-opus-5-5', timeout=30)
    owner = owners[0]
    argv = owner.argv
    assert argv[0] == 'claude'
    for flag in ('-p', '--safe-mode', '--strict-mcp-config', '--no-session-persistence',
                 '--exclude-dynamic-system-prompt-sections'):
        assert flag in argv
    assert argv[argv.index('--output-format') + 1] == 'json'
    assert argv[argv.index('--model') + 1] == 'claude-opus-5-5'
    assert argv[argv.index('--effort') + 1] == 'high'
    assert '--tools=' in argv
    assert '--json-schema' not in argv
    env = owner.options['env']
    for chave in ('ANTHROPIC_API_KEY', 'FORGE_API_KEY', 'ANTHROPIC_BASE_URL', 'ANTHROPIC_AUTH_TOKEN'):
        assert chave not in env
    assert owner.prompt == 'Escreva o gancho'
    assert owner.options['cwd'] == response.work_dir
    assert (response.work_dir / 'prompt.txt').read_text(encoding='utf-8') == 'Escreva o gancho'
    assert (response.work_dir / 'system.txt').read_text(encoding='utf-8') == 'Você é roteirista.'
    assert (response.work_dir / 'response.json').is_file()
    assert owner.terminated


def test_argv_aceito_pelo_dono_real_do_processo(tmp_path):
    # O SubprocessExecutor recusa argv vazio; `--tools ''` passava no fake e
    # quebrava na primeira chamada real.
    from forge.services.subprocesso import SubprocessExecutor

    cli = ClaudeCLI(settings(tmp_path))
    for schema in (None, {'type': 'object'}):
        argv = cli._argv(model='claude-opus-5-5', system_path=tmp_path / 's.txt',
                         effort='high', schema=schema)
        assert all(argv)
        SubprocessExecutor(argv, timeout_seconds=30)


def test_ambiente_sem_marcas_de_sessao_claude_aninhada(tmp_path, monkeypatch):
    """O Studio pode ter sido aberto de dentro de um Claude Code: as variáveis
    da sessão-mãe não podem mudar o comportamento do filho."""
    cli, owners = fake_cli(tmp_path, monkeypatch)
    monkeypatch.setenv('CLAUDECODE', '1')
    monkeypatch.setenv('CLAUDE_CODE_ENTRYPOINT', 'claude-desktop')
    monkeypatch.setenv('CLAUDE_CODE_OAUTH_TOKEN', 'tok')
    cli.run('p', system='s', model='claude-opus-5-5', timeout=30)
    env = owners[0].options['env']
    assert 'CLAUDECODE' not in env and 'CLAUDE_CODE_ENTRYPOINT' not in env
    # Token de assinatura explícito do usuário é autenticação legítima.
    assert env['CLAUDE_CODE_OAUTH_TOKEN'] == 'tok'


def test_diretorio_padrao_fica_fora_do_repositorio():
    """O CLI sobe de diretório procurando CLAUDE.md e .claude/: um diretório
    de chamada dentro do repo arriscaria levar as instruções do projeto."""
    padrao = Settings(_env_file=None).claude_runs_dir.resolve()
    raiz = Path(__file__).resolve().parents[2]
    assert raiz not in padrao.parents


def test_run_confere_login_uma_vez_por_instancia(tmp_path, monkeypatch):
    cli, _ = fake_cli(tmp_path, monkeypatch)
    vezes = []
    monkeypatch.setattr(cli, 'check_auth', lambda: vezes.append(1))
    cli.run('p', system='s', model='claude-opus-5-5', timeout=30)
    cli.run('p', system='s', model='claude-opus-5-5', timeout=30)
    assert vezes == [1]


def test_falha_ao_criar_processo_vira_claude_error(tmp_path, monkeypatch):
    cli = ClaudeCLI(settings(tmp_path))
    monkeypatch.setattr(cli, 'check_auth', lambda: None)

    class Quebra(FakeOwner):
        def _spawn_process(self, **options):
            raise RuntimeError('Job Object recusado')

    monkeypatch.setattr('forge.services.claude_cli.SubprocessExecutor', lambda argv, **o: Quebra(argv))
    with pytest.raises(ClaudeError, match='logs:'):
        cli.run('p', system='s', model='claude-opus-5-5', timeout=30)


def test_sondar_de_revisor_usa_o_modelo_do_revisor(tmp_path):
    run, chamadas = _runner_sonda({'loggedIn': True, 'authMethod': 'claude.ai'}, resultado(result='ok'))
    s = Settings(_env_file=None, provider='codex', review_provider='claude',
                 review_model='claude-sonnet-5-5', claude_runs_dir=tmp_path / 'c')
    ClaudeCLI(s, runner=run).sondar()
    argv = chamadas[-1][0]
    assert argv[argv.index('--model') + 1] == 'claude-sonnet-5-5'


def test_system_prompt_vai_por_arquivo(tmp_path, monkeypatch):
    cli, owners = fake_cli(tmp_path, monkeypatch)
    system = 'regra ' * 8000
    response = cli.run('p', system=system, model='claude-opus-5-5', timeout=30)
    argv = owners[0].argv
    assert all(system not in parte for parte in argv)
    caminho = Path(argv[argv.index('--system-prompt-file') + 1])
    assert caminho.read_text(encoding='utf-8') == system
    assert caminho.parent == response.work_dir


def test_schema_vai_em_json_schema(tmp_path, monkeypatch):
    cli, owners = fake_cli(tmp_path, monkeypatch)
    schema = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}}, 'required': ['ok']}
    cli.run('p', system='s', model='claude-opus-5-5', timeout=30, schema=schema)
    argv = owners[0].argv
    assert json.loads(argv[argv.index('--json-schema') + 1]) == schema


def test_sucesso_devolve_texto_e_estruturado(tmp_path, monkeypatch):
    cli, _ = fake_cli(tmp_path, monkeypatch, saida=resultado(
        result='', structured_output={'ok': True}, stop_reason='max_tokens',
    ))
    response = cli.run('p', system='s', model='claude-opus-5-5', timeout=30, schema={'type': 'object'})
    assert response.structured == {'ok': True}
    assert response.stop_reason == 'max_tokens'
    assert response.usage == {'input_tokens': 12, 'output_tokens': 3}


@pytest.mark.parametrize('saida,erro,trecho', [
    (resultado(is_error=True, result='Failed to authenticate: OAuth session expired and could not be refreshed'),
     ClaudeAuthError, 'claude auth login'),
    (resultado(is_error=True, result='API Error', api_error_status=401), ClaudeAuthError, 'claude auth login'),
    (resultado(is_error=True, result='Claude AI usage limit reached|1763337600'), ClaudeUsageLimitError, 'cota'),
    (resultado(is_error=True, result="You've hit your limit · resets 4am"), ClaudeUsageLimitError, 'cota'),
    # Medido numa run real (assinatura Pro): a frase leva o tipo do limite.
    (resultado(is_error=True, result="You've hit your session limit · resets 2:20pm (America/Fortaleza)"),
     ClaudeUsageLimitError, 'cota'),
    # 429 sem a frase de cota é limite de taxa passageiro, não cota esgotada.
    (resultado(is_error=True, result='API Error: rate limit', api_error_status=429), ClaudeError, 'rate limit'),
    (resultado(is_error=True, result='Output limit reached for structured output'), ClaudeError, 'limit reached'),
    (resultado(is_error=True, result='modelo indisponível'), ClaudeError, 'modelo indisponível'),
])
def test_is_error_decide_mesmo_com_subtype_success(tmp_path, monkeypatch, saida, erro, trecho):
    cli, owners = fake_cli(tmp_path, monkeypatch, saida=saida, exit_code=1)
    with pytest.raises(ClaudeError) as caught:
        cli.run('p', system='s', model='claude-opus-5-5', timeout=30)
    assert type(caught.value) is erro
    assert trecho in str(caught.value).lower() or trecho in str(caught.value)
    assert 'logs:' in str(caught.value)
    assert owners[0].terminated


@pytest.mark.parametrize('bruto,code', [('', 1), ('não é json', 0), ('[]', 0)])
def test_saida_nao_json_falha_fechado(tmp_path, monkeypatch, bruto, code):
    cli, _ = fake_cli(tmp_path, monkeypatch, bruto=bruto, exit_code=code)
    with pytest.raises(ClaudeError, match='logs:'):
        cli.run('p', system='s', model='claude-opus-5-5', timeout=30)


def test_exit_diferente_de_zero_sem_is_error_falha(tmp_path, monkeypatch):
    cli, _ = fake_cli(tmp_path, monkeypatch, exit_code=2)
    with pytest.raises(ClaudeError):
        cli.run('p', system='s', model='claude-opus-5-5', timeout=30)


def test_timeout_encerra_arvore(tmp_path, monkeypatch):
    cli, owners = fake_cli(tmp_path, monkeypatch, timeout=True)
    with pytest.raises(ClaudeError, match='prazo'):
        cli.run('p', system='s', model='claude-opus-5-5', timeout=0.1)
    assert owners[0].terminated


def _runner_sonda(status, saida):
    chamadas = []

    def run(argv, **kwargs):
        chamadas.append((argv, kwargs))
        if argv[1:] == ['auth', 'status']:
            return SimpleNamespace(returncode=0, stdout=json.dumps(status), stderr='')
        return SimpleNamespace(returncode=1 if saida.get('is_error') else 0,
                               stdout=json.dumps(saida), stderr='')

    return run, chamadas


def test_sondar_faz_chamada_real_isolada(tmp_path, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'secret')
    run, chamadas = _runner_sonda({'loggedIn': True, 'authMethod': 'claude.ai'}, resultado(result='ok'))
    ClaudeCLI(settings(tmp_path), runner=run).sondar()
    argv, kwargs = chamadas[-1]
    assert '-p' in argv and '--safe-mode' in argv and '--strict-mcp-config' in argv
    assert '--tools=' in argv
    assert argv[argv.index('--model') + 1] == 'claude-opus-5-5'
    assert 'ANTHROPIC_API_KEY' not in kwargs['env']
    assert kwargs['input']


def test_sondar_pega_sessao_morta_que_o_status_esconde(tmp_path):
    run, _ = _runner_sonda(
        {'loggedIn': True, 'authMethod': 'claude.ai'},
        resultado(is_error=True, result='Failed to authenticate: OAuth session expired and could not be refreshed'),
    )
    with pytest.raises(ClaudeAuthError, match='claude auth login'):
        ClaudeCLI(settings(tmp_path), runner=run).sondar()


@pytest.mark.parametrize('status,code,ok', [
    ({'loggedIn': True, 'authMethod': 'claude.ai'}, 0, True),
    ({'loggedIn': False}, 1, False),
    ({'loggedIn': True, 'authMethod': 'api_key'}, 0, False),
])
def test_check_auth(tmp_path, monkeypatch, status, code, ok):
    chamadas = []

    def run(argv, **kwargs):
        chamadas.append((argv, kwargs))
        return SimpleNamespace(returncode=code, stdout=json.dumps(status), stderr='')

    monkeypatch.setattr('forge.services.claude_cli.subprocess.run', run)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'secret')
    cli = ClaudeCLI(settings(tmp_path))
    if ok:
        cli.check_auth()
    else:
        with pytest.raises(ClaudeAuthError, match='claude auth login'):
            cli.check_auth()
    argv, kwargs = chamadas[0]
    assert argv[1:] == ['auth', 'status']
    assert 'ANTHROPIC_API_KEY' not in kwargs['env']
