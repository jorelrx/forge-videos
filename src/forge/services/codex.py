"""Codex CLI oficial com sessão ChatGPT, execução contida e evidência em disco."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from forge.infrastructure.config import Settings
from forge.services.subprocesso import SubprocessExecutor


class CodexError(RuntimeError):
    """Falha explícita, sem fallback para outra conta, modelo ou API."""


class CodexUsageLimitError(CodexError):
    """Cota da conta esgotada; novas chamadas não recuperam o lote."""


@dataclass(frozen=True)
class CodexResponse:
    text: str
    work_dir: Path


def _strict_schema(schema: dict) -> dict:
    """Schemas do Codex exigem propriedades fechadas e explicitamente presentes."""
    def walk(value):
        if isinstance(value, list):
            return [walk(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {key: walk(item) for key, item in value.items() if key != 'default'}
        if result.get('type') == 'object' and 'properties' in result:
            result['additionalProperties'] = False
            result['required'] = list(result['properties'])
        return result
    return walk(schema)


class CodexCLI:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _environment() -> dict[str, str]:
        # Não permitir que chaves herdadas mudem a cobrança da chamada.
        return {
            key: value for key, value in os.environ.items()
            if not key.upper().endswith('API_KEY')
            and key.upper() not in {'OPENAI_BASE_URL', 'CODEX_ACCESS_TOKEN'}
        }

    def check_auth(self) -> None:
        try:
            result = subprocess.run(
                [self.settings.codex_bin, 'login', 'status'],
                capture_output=True, text=True, encoding='utf-8', errors='replace',
                timeout=15, env=self._environment(),
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise CodexError('Codex CLI indisponível; instale Codex e execute codex login') from error
        if result.returncode or 'logged in using chatgpt' not in (result.stdout + result.stderr).lower():
            raise CodexError('Sessão ChatGPT ausente; execute codex login e entre com sua assinatura')

    def run(
        self, prompt: str, *, model: str, timeout: float,
        schema: dict | None = None, allow_images: bool = False,
        work_dir: Path | None = None,
    ) -> CodexResponse:
        self.check_auth()
        if work_dir is None:
            root = self.settings.codex_runs_dir.resolve()
            root.mkdir(parents=True, exist_ok=True)
            work_dir = Path(tempfile.mkdtemp(prefix='call-', dir=root))
        work_dir = Path(work_dir).resolve()
        work_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = work_dir / 'prompt.txt'
        prompt_path.write_text(prompt, encoding='utf-8')
        final_path = work_dir / 'response.txt'
        final_path.unlink(missing_ok=True)
        argv = [
            self.settings.codex_bin, 'exec', '--ignore-user-config', '--json',
            '--ephemeral', '--skip-git-repo-check', '--sandbox',
            'workspace-write' if allow_images else 'read-only',
            '--cd', str(work_dir), '--model', model,
            '-c', 'forced_login_method="chatgpt"',
            '-c', 'model_provider="openai"',
            '-c', 'web_search="disabled"',
            '-c', 'features.shell_tool=false',
            '-c', f'model_reasoning_effort={json.dumps(self.settings.codex_effort)}',
            '-c', f'features.image_generation={str(allow_images).lower()}',
            '--output-last-message', str(final_path),
        ]
        if schema is not None:
            schema_path = work_dir / 'schema.json'
            schema_path.write_text(json.dumps(_strict_schema(schema), ensure_ascii=False), encoding='utf-8')
            argv.extend(['--output-schema', str(schema_path)])
        argv.append('-')
        owner = SubprocessExecutor(argv, timeout_seconds=timeout)
        process = None
        with prompt_path.open(encoding='utf-8') as stdin, \
             (work_dir / 'events.jsonl').open('w', encoding='utf-8') as stdout, \
             (work_dir / 'stderr.log').open('w', encoding='utf-8') as stderr:
            try:
                process, group, job = owner._spawn_process(
                    stdin=stdin, stdout=stdout, stderr=stderr,
                    cwd=work_dir, env=self._environment(),
                )
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired as error:
                raise CodexError(f'Codex excedeu prazo de {timeout:g}s; logs: {work_dir}') from error
            except OSError as error:
                raise CodexError(f'Falha ao executar Codex CLI; logs: {work_dir}') from error
            finally:
                if process is not None:
                    owner._terminate(process, process_group_id=group, windows_job=job)
        completed = False
        failure = ''
        usage_limit = ''
        with (work_dir / 'events.jsonl').open(encoding='utf-8') as events:
            for line in events:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get('type') == 'turn.completed':
                    completed = True
                if event.get('type') in {'turn.failed', 'error'}:
                    error = event.get('error', event.get('message', 'Codex falhou'))
                    message = str(error.get('message', error) if isinstance(error, dict) else error)
                    failure = message[:1200]
                    if 'hit your usage limit' in message.lower() or (
                        isinstance(error, dict) and error.get('code') == 'usage_limit_reached'
                    ):
                        usage_limit = failure
        if usage_limit:
            raise CodexUsageLimitError(
                f'Cota Codex esgotada. Aguarde a renovação da cota ou verifique os créditos '
                f'em https://chatgpt.com/codex/settings/usage; depois retome a etapa. '
                f'Detalhe: {usage_limit}; logs: {work_dir}'
            )
        if code or failure:
            raise CodexError(f'Codex falhou: {failure or code}; logs: {work_dir}')
        if not completed:
            raise CodexError(f'Codex sem turn.completed; logs: {work_dir}')
        if not final_path.is_file() or not final_path.read_text(encoding='utf-8').strip():
            raise CodexError(f'Codex terminou sem saída final; logs: {work_dir}')
        return CodexResponse(final_path.read_text(encoding='utf-8').strip(), work_dir)


__all__ = ['CodexCLI', 'CodexError', 'CodexUsageLimitError', 'CodexResponse']
