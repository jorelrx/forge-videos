# Task 3 — execução de stages em subprocesso tipado

## Implementação

- `SubprocessExecutor` agora exige exatamente um evento `stage.result` válido; valida `StageChildResult`, rejeita ausência/duplicidade/evento terminal malformado e traduz gate/failure para `StageResult`, preservando evidência em `outputs`.
- `StageProcessExecutor` cria snapshot `RunSnapshot` atômico em `video/.stage-<stage>-r<attempt>.json`, lança `python -m forge.executors.entrypoint` com argv fixo e sem shell, mantém snapshot em falhas de protocolo/processo e remove-o após parse operacional válido.
- `entrypoint` usa allowlist de oito stages, contexto absoluto, dispatcher por import seguro e emite JSONL UTF-8 com `stage.result` tipado.
- `RetryPolicy` aplica retry somente a `FailureClass.TRANSIENT`, backoff exponencial limitado e evento `operation.retrying`; falhas de capacidade e demais classes não repetem.
- `StudioWorker` entrega ao contexto vídeo, artefatos e itens de trabalho; defaults de listas em `StageContext` usam `dataclasses.field`.

## Arquivos

- Criados: `src/forge/executors/process.py`, `src/forge/executors/entrypoint.py`, `src/forge/executors/retry.py`.
- Modificados: `src/forge/services/subprocesso.py`, `src/forge/services/worker.py`, `tests/services/test_subprocesso.py`.
- Testes criados: `tests/executors/test_process.py`, `tests/executors/test_entrypoint.py`, `tests/executors/test_retry.py`.

## Comandos e resultados

- RED: `uv run --no-cache pytest tests/executors/test_process.py tests/executors/test_entrypoint.py tests/executors/test_retry.py tests/services/test_subprocesso.py -q` — falhou na coleta com `ModuleNotFoundError` para `forge.executors.process` e `forge.executors.retry`.
- GREEN focado: mesmo comando — `33 passed`.
- Integração: `uv run --no-cache pytest tests/services/test_worker.py tests/services/test_worker_acceptance.py tests/executors/test_process.py tests/executors/test_entrypoint.py tests/executors/test_retry.py -q` — `18 passed`.
- Suíte completa: `uv run --no-cache pytest -q` — `498 passed, 1 skipped, 1 deselected`.
- Verificação: `uv run --no-cache python -m compileall -q src/forge` — sucesso; `git diff --check` — sucesso.

## Evidência TDD

Testes de contrato foram escritos antes dos módulos novos e a execução RED confirmou falhas de importação. A implementação mínima passou no GREEN focado; depois foram corrigidas regressões legítimas dos testes antigos para o protocolo obrigatório `stage.result` e repetidos os testes até a suíte completa ficar verde.

## Autorrevisão

- argv não aceita comando/módulo vindo do usuário; stage é enum allowlisted e subprocesso usa `shell=False`.
- snapshot não lê nem serializa ambiente; credenciais efetivas continuam responsabilidade do processo filho/configuração.
- timeout, cancelamento, stderr limitado e contenção de descendentes existentes foram preservados.
- ausência/duplicidade/malformed terminal resultam em falha de protocolo, não em gate aprovado/reprovado.

## Preocupações

- Os módulos concretos dos oito stages ainda serão entregues nas tasks seguintes; o dispatcher retorna erro de filho se um stage allowlisted ainda não estiver instalado.
- `StageProcessExecutor` exige `video` no `StageContext`; o worker agora o carrega do repositório.

## Round 1 — correções de revisão

### Mudanças

- `StudioWorker._finish_stage` agora copia `result.outputs["failure"]` para o payload de `stage.failed`, usando `Redactor` para sanitização recursiva. A evidência preserva adapter, comando/argv, tentativa, item, stack trace, serviços/GPU, `retriable` e ação recomendada.
- `forge.executors.entrypoint` valida que `--stage` coincide com `RunSnapshot.stage` antes de chamar o dispatcher/import dinâmico; divergência encerra o filho com erro estável.

### Arquivos

- Modificados: `src/forge/services/worker.py`, `src/forge/executors/entrypoint.py`.
- Testes modificados: `tests/services/test_worker.py`, `tests/executors/test_entrypoint.py`.

### TDD e verificação

- RED: `uv run --no-cache pytest tests/services/test_worker.py::test_run_once_persists_sanitized_failure_evidence_on_stage_failed tests/executors/test_entrypoint.py::test_entrypoint_rejects_stage_flag_mismatch_before_importing_executor -q` — `2 failed`: chave `failure` ausente e dispatcher chamado com stage divergente.
- GREEN focado: `uv run --no-cache pytest tests/services/test_worker.py tests/executors/test_entrypoint.py -q` — `16 passed`.
- Suíte completa: `uv run --no-cache pytest -q` — `500 passed, 1 skipped, 1 deselected`.

### Autorrevisão

- A evidência completa só é anexada no ramo `stage.failed`; dados credenciais em chaves reconhecidas são redigidos antes da persistência.
- O snapshot é validado antes de qualquer import de implementação, impedindo executar módulo de outro stage por flag adulterada.
- Não houve alteração em timeout, cancelamento, contenção ou protocolo JSONL.

## Round 2 — injeção de segredos no redator

### Mudanças

- `Settings.secret_values()` reúne chaves configuradas, sem valores vazios ou duplicados.
- `build_worker` injeta `Redactor(settings.secret_values())` no `StudioWorker`.
- `StudioWorker` mantém uma única instância injetada e a reutiliza em `_event_sink` e no payload de `stage.failed`. Call sites diretos continuam compatíveis com fallback explícito de redaction por nomes de credencial, sem alegar conhecer segredos de ambiente.
- Stack traces e argv/command com segredo efetivo agora viram `[REDACTED]` antes da persistência do evento.

### Arquivos

- Modificados: `src/forge/infrastructure/config.py`, `src/forge/services/studio.py`, `src/forge/services/worker.py`.
- Testes modificados: `tests/test_config.py`, `tests/services/test_worker.py`.

### TDD e verificação

- RED: `uv run --no-cache pytest tests/services/test_worker.py::test_run_once_persists_sanitized_failure_evidence_on_stage_failed tests/test_config.py::test_secret_values_exposes_configured_provider_keys_for_redaction -q` — `2 failed`: `redactor` não era aceito e `Settings.secret_values` não existia.
- GREEN mínimo: mesmo comando mais `tests/services/test_studio.py` — `4 passed`.
- Foco afetado: `uv run --no-cache pytest tests/services/test_worker.py tests/services/test_catalogo.py tests/services/test_redacao.py tests/services/test_studio.py tests/test_config.py -q` — `63 passed`.
- Suíte completa: `uv run --no-cache pytest -q` — `501 passed, 1 skipped, 1 deselected`.

### Autorrevisão

- Segredos efetivos configurados chegam ao mesmo redator usado pelos eventos normais e por `stage.failed`; não há nova instância vazia no caminho de produção.
- O teste cobre segredo dentro de stack trace e lista de argv, além de verificar redaction do evento emitido pelo `_event_sink`.
- Call sites antigos de `StudioWorker` seguem funcionais, mas só recebem mascaramento estrutural quando não fornecem configuração de segredos.
