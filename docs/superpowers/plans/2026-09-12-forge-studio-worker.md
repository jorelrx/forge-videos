# Forge Studio Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Worker persistente e testável para uma única run: lease, heartbeat, pausa cooperativa, subprocesso JSONL e recuperação segura.

**Architecture:** `OperacaoRepository` mantém exclusividade/leases em SQLite; `StudioWorker` coordena executores injetados; adaptador subprocesso valida JSONL. Sem executores reais, API ou frontend.

**Tech Stack:** Python 3.12, sqlite3, subprocess, threading, Pydantic, pytest.

## Global Constraints

- Uma run ativa por banco: `preparing`, `running`, `pausing`, `validating` bloqueiam novo claim.
- Heartbeat a cada 5s; lease perdido vira `interrupted`, nunca reenfileiramento automático.
- Pausa termina limite atômico atual antes de `paused`.
- JSONL é contrato; stderr apenas diagnóstico.
- Recuperação não apaga artefatos.

---

### Task 1: Exclusividade, lease e transições persistentes

**Files:** Modify `src/forge/repositories/operacao.py`, `src/forge/services/control_plane.py`; modify `tests/repositories/test_operacao.py`, `tests/services/test_control_plane.py`.

- [ ] **Step 1: RED.** Testar duas runs em fila e dois claims concorrentes: exatamente uma claim. Testar `renew_lease(run_id, worker_id, lease_seconds)` somente para dono ativo. Testar lease vencido: run e etapa corrente passam a `interrupted`.
- [ ] **Step 2: Verify RED.** `uv run --no-cache pytest tests/repositories/test_operacao.py tests/services/test_control_plane.py -q` falha por APIs/semântica ausentes.
- [ ] **Step 3: GREEN.** Criar `renew_lease`, `interrupt_expired(now)` e `save_stage`; tornar `claim_next` retornar `None` enquanto existir run ativa. Eventos continuam na fronteira worker/service.
- [ ] **Step 4: Verify GREEN.** Cobrir dono errado, histórico de lease e nenhum segundo claim.
- [ ] **Step 5: Commit.** `feat(studio): enforce worker lease ownership`.

### Task 2: Worker genérico e ciclo de etapa

**Files:** Create `src/forge/services/worker.py`; modify `src/forge/domain/operacao.py`; create `tests/services/test_worker.py`.

- [ ] **Step 1: RED.** Fakes provam `pending → running → succeeded`; resultado falho torna etapa/run `failed`; executor ausente registra `executor_missing` sem avançar.
- [ ] **Step 2: GREEN.** Definir `StageContext`, `EventSink`, `StageResult(gate_status, current_items=0, total_items=0)`, protocolo `StageExecutor.execute(context, emit)`, e `StudioWorker.run_once()`. `run_once` reconcilia leases, reivindica uma run, executa só a etapa corrente, persiste `stage.started`, `stage.succeeded` ou `stage.failed`.
- [ ] **Step 3: Verify GREEN.** `uv run --no-cache pytest tests/services/test_worker.py -q`.
- [ ] **Step 4: Commit.** `feat(studio): add deterministic stage worker`.

### Task 3: Heartbeat e pausa cooperativa

**Files:** Modify `src/forge/services/worker.py`; modify `tests/services/test_worker.py`.

- [ ] **Step 1: RED.** Testar tick de heartbeat, perda de propriedade e pausa aceita aplicada somente após retorno do executor.
- [ ] **Step 2: GREEN.** Implementar `LeaseHeartbeat.tick()` e wrapper daemon; consultar comandos pause `accepted` via `ComandosRepository`; limpar lease ao pausar e marcar comando `applied`.
- [ ] **Step 3: Verify GREEN.** Uma pausa/evento; progresso concluído preservado.
- [ ] **Step 4: Commit.** `feat(studio): pause runs at safe worker boundaries`.

### Task 4: Adaptador subprocesso JSONL confiável

**Files:** Create `src/forge/services/subprocesso.py`; modify `src/forge/services/worker.py`; create `tests/services/test_subprocesso.py`.

- [ ] **Step 1: RED.** Filho `sys.executable -c`: JSON válido vira evento; stdout inválido gera `worker.invalid_event`; exit não-zero gera `subprocess_failed` com stderr limitado.
- [ ] **Step 2: GREEN.** Criar `SubprocessExecutor(argv)`; recusar argv vazio; usar `Popen` sem shell; aceitar só objeto com `kind`, `level`, `message` não vazios e `payload` objeto.
- [ ] **Step 3: Verify GREEN.** `uv run --no-cache pytest tests/services/test_subprocesso.py tests/services/test_worker.py -q`.
- [ ] **Step 4: Commit.** `feat(studio): persist worker subprocess events`.

### Task 5: Configuração e prova de recuperação

**Files:** Modify `src/forge/infrastructure/config.py`, `src/forge/services/studio.py`; create `tests/services/test_worker_acceptance.py`.

- [ ] **Step 1: RED.** Enfileirar duas runs, expirar a primeira, reiniciar worker, verificar primeira `interrupted`, segunda na fila; retomar e provar só uma claim posterior.
- [ ] **Step 2: GREEN.** Adicionar `worker_lease_seconds=15`, `worker_heartbeat_seconds=5`; rejeitar heartbeat maior/igual ao lease; expor `build_worker(settings, executors, worker_id)`.
- [ ] **Step 3: Verify.** Rodar `uv run --no-cache pytest -q`, `uv run --no-cache python -m compileall -q src/forge` e `git diff --check`.
- [ ] **Step 4: Commit.** `test(studio): prove worker recovery and single-run lease`.

## Handoff

Marco 2 termina no worker genérico testado. A reconciliação de artefatos (hash,
arquivos ausentes e órfãos) fica explicitamente adiada para o marco dos
executores, que terá validadores de artefato; este marco genérico não possui
esses validadores. Não iniciar reconciliação ampla de mídia, executores reais,
API/dashboard ou launcher sem nova spec/plano aprovado.
