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
