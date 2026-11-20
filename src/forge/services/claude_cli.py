"""Claude Code oficial (`claude -p`) com a assinatura do usuário.

O login de assinatura só pode ser usado pelas ferramentas da Anthropic, então
este é o único caminho: nada de ler o token OAuth e chamar a API direto.

A chamada roda isolada da configuração do usuário. `--safe-mode` desliga
CLAUDE.md, skills, plugins, hooks e MCP; sem isso, as instruções pessoais do
usuário (estilo de resposta, hooks de sessão) entrariam no prompt do roteiro.
`--bare` isolaria também, mas só aceita `ANTHROPIC_API_KEY` — inútil aqui.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from forge.infrastructure.config import MODELO_PADRAO, Settings
from forge.services.subprocesso import SubprocessExecutor

ACAO_LOGIN = 'execute claude auth login num terminal e entre com sua assinatura'


class ClaudeError(RuntimeError):
    """Falha explícita, sem fallback para outra conta, modelo ou API."""


class ClaudeAuthError(ClaudeError):
    """Sessão de assinatura ausente ou expirada."""


class ClaudeUsageLimitError(ClaudeError):
    """Cota da assinatura esgotada; novas chamadas não recuperam a etapa."""


@dataclass(frozen=True)
class ClaudeResponse:
    text: str
    structured: dict | None
    work_dir: Path
    stop_reason: str | None = None
    usage: dict = field(default_factory=dict)


# Só as frases da cota da assinatura. Um 429 sem elas é limite de taxa
# passageiro: mandar o usuário "aguardar a renovação" seria o conselho errado.
# Medido: "You've hit your session limit" (Pro). A frase traz o tipo do
# limite no meio, então casa por expressão, não por substring fixa.
_SINAL_COTA = re.compile(r'usage limit|hit your (?:\w+ )?limit')
_SINAIS_AUTH = ('failed to authenticate', 'not logged in', 'oauth', 'invalid api key', 'please run /login')


def _herdavel(chave: str) -> bool:
    nome = chave.upper()
    # Chave herdada faria o CLI cobrar a API em vez da assinatura, sem aviso.
    if nome.endswith('API_KEY') or nome in {'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL'}:
        return False
    # Marcas da sessão Claude Code que abriu o Studio, se houver. O token de
    # assinatura explícito do usuário fica: é autenticação, não marca.
    if nome == 'CLAUDECODE' or (nome.startswith('CLAUDE_CODE_') and nome != 'CLAUDE_CODE_OAUTH_TOKEN'):
        return False
    return True


def _ambiente() -> dict[str, str]:
    return {chave: valor for chave, valor in os.environ.items() if _herdavel(chave)}


def _interpretar(dados, codigo: int, work_dir: Path) -> ClaudeResponse:
    """Resultado JSON do `claude -p` em resposta ou erro tipado.

    `subtype` vem "success" até em falha de autenticação (medido): quem decide
    é `is_error`.
    """
    if not isinstance(dados, dict):
        raise ClaudeError(f'Claude sem resultado JSON (exit {codigo}); logs: {work_dir}')
    if dados.get('is_error'):
        detalhe = str(dados.get('result') or dados.get('terminal_reason') or 'erro')[:1200]
        status = dados.get('api_error_status')
        minusculo = detalhe.lower()
        if _SINAL_COTA.search(minusculo):
            raise ClaudeUsageLimitError(
                f'Cota da assinatura Claude esgotada. Aguarde a renovação e retome a '
                f'etapa, ou troque o provider. Detalhe: {detalhe}; logs: {work_dir}'
            )
        if status in (401, 403) or any(sinal in minusculo for sinal in _SINAIS_AUTH):
            raise ClaudeAuthError(f'Sessão Claude inválida: {detalhe}; {ACAO_LOGIN}; logs: {work_dir}')
        raise ClaudeError(f'Claude falhou: {detalhe}; logs: {work_dir}')
    if codigo:
        raise ClaudeError(f'Claude terminou com exit {codigo}; logs: {work_dir}')
    estruturado = dados.get('structured_output')
    return ClaudeResponse(
        text=str(dados.get('result') or ''),
        structured=estruturado if isinstance(estruturado, dict) else None,
        work_dir=work_dir,
        stop_reason=dados.get('stop_reason'),
        usage=dados.get('usage') if isinstance(dados.get('usage'), dict) else {},
    )


class ClaudeCLI:
    def __init__(self, settings: Settings, runner=None) -> None:
        self.settings = settings
        # Resolvido na chamada, não na definição: o teste troca o módulo.
        self._runner = runner or (lambda *args, **kwargs: subprocess.run(*args, **kwargs))
        self._login_conferido = False

    def _work_dir(self) -> Path:
        raiz = self.settings.claude_runs_dir.resolve()
        raiz.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix='call-', dir=raiz)).resolve()

    def _argv(self, *, model: str, system_path: Path, effort: str, schema: dict | None) -> list[str]:
        argv = [
            self.settings.claude_bin, '-p', '--output-format', 'json',
            '--model', model, '--effort', effort,
            # `--tools=` e não `--tools ''`: o SubprocessExecutor recusa argv
            # vazio. Medido: as duas grafias deixam o modelo sem ferramenta.
            '--safe-mode', '--strict-mcp-config', '--tools=',
            '--no-session-persistence', '--exclude-dynamic-system-prompt-sections',
            '--system-prompt-file', str(system_path),
        ]
        if schema is not None:
            argv.extend(['--json-schema', json.dumps(schema, ensure_ascii=False)])
        return argv

    def sondar(self, timeout: float = 120.0) -> None:
        """Prova que a sessão responde: login declarado + uma chamada mínima.

        Custa uma chamada da cota; é do preflight, não do painel.
        """
        self.check_auth()
        work_dir = self._work_dir()
        system_path = work_dir / 'system.txt'
        system_path.write_text('Responda somente: ok', encoding='utf-8')
        modelo = (
            self.settings.resolved_model if self.settings.provider == 'claude'
            else self.settings.review_model or MODELO_PADRAO['claude']
        )
        argv = self._argv(model=modelo, system_path=system_path, effort='low', schema=None)
        try:
            resultado = self._runner(
                argv, input='ok', capture_output=True, text=True, encoding='utf-8',
                errors='replace', timeout=timeout, env=_ambiente(), cwd=work_dir,
            )
        except (OSError, subprocess.TimeoutExpired) as erro:
            raise ClaudeError(f'Claude Code não respondeu à sonda; logs: {work_dir}') from erro
        (work_dir / 'response.json').write_text(resultado.stdout or '', encoding='utf-8')
        try:
            dados = json.loads(resultado.stdout or '')
        except ValueError:
            dados = None
        _interpretar(dados, resultado.returncode, work_dir)

    def check_auth(self) -> None:
        """Confere o login declarado. Não prova que a sessão ainda renova:
        medido nesta máquina, `auth status` diz `loggedIn` com o refresh já
        morto. Quem precisa de prova chama `sondar`."""
        try:
            resultado = self._runner(
                [self.settings.claude_bin, 'auth', 'status'],
                capture_output=True, text=True, encoding='utf-8', errors='replace',
                timeout=15, env=_ambiente(),
            )
        except (OSError, subprocess.TimeoutExpired) as erro:
            raise ClaudeAuthError(f'Claude Code indisponível; instale e {ACAO_LOGIN}') from erro
        try:
            status = json.loads(resultado.stdout or '{}')
        except ValueError:
            status = {}
        if (
            resultado.returncode
            or not isinstance(status, dict)
            or status.get('loggedIn') is not True
            or status.get('authMethod') != 'claude.ai'
        ):
            raise ClaudeAuthError(f'Sessão de assinatura Claude ausente; {ACAO_LOGIN}')

    def run(
        self, prompt: str, *, system: str, model: str, timeout: float,
        schema: dict | None = None,
    ) -> ClaudeResponse:
        # `authMethod == claude.ai` é a garantia de cobrar a assinatura, e o
        # `forge roteiro` não passa pelo preflight. Uma vez por instância.
        if not self._login_conferido:
            self.check_auth()
            self._login_conferido = True
        work_dir = self._work_dir()
        prompt_path = work_dir / 'prompt.txt'
        prompt_path.write_text(prompt, encoding='utf-8')
        # Por arquivo: o prompt de sistema leva as skills e passa fácil do
        # limite de linha de comando do Windows (~32 mil caracteres).
        system_path = work_dir / 'system.txt'
        system_path.write_text(system, encoding='utf-8')
        saida_path = work_dir / 'response.json'
        argv = self._argv(
            model=model, system_path=system_path, effort=self.settings.claude_effort,
            schema=schema,
        )
        dono = SubprocessExecutor(argv, timeout_seconds=timeout)
        processo = None
        with prompt_path.open(encoding='utf-8') as stdin, \
             saida_path.open('w', encoding='utf-8') as stdout, \
             (work_dir / 'stderr.log').open('w', encoding='utf-8') as stderr:
            try:
                processo, grupo, job = dono._spawn_process(
                    stdin=stdin, stdout=stdout, stderr=stderr,
                    cwd=work_dir, env=_ambiente(),
                )
                codigo = processo.wait(timeout=timeout)
            except subprocess.TimeoutExpired as erro:
                raise ClaudeError(f'Claude excedeu prazo de {timeout:g}s; logs: {work_dir}') from erro
            except (OSError, RuntimeError) as erro:
                # RuntimeError: o dono do processo recusa criar o Job Object.
                raise ClaudeError(f'Falha ao executar Claude Code: {erro}; logs: {work_dir}') from erro
            finally:
                if processo is not None:
                    dono._terminate(processo, process_group_id=grupo, windows_job=job)
        try:
            dados = json.loads(saida_path.read_text(encoding='utf-8'))
        except ValueError:
            dados = None
        return _interpretar(dados, codigo, work_dir)


__all__ = [
    'ClaudeAuthError', 'ClaudeCLI', 'ClaudeError', 'ClaudeResponse', 'ClaudeUsageLimitError',
]
