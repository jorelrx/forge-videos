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

- [x] **Step 1: RED.** Testar duas runs em fila e dois claims concorrentes: exatamente uma claim. Testar `renew_lease(run_id, worker_id, lease_seconds)` somente para dono ativo. Testar lease vencido: run e etapa corrente passam a `interrupted`.
- [x] **Step 2: Verify RED.** `uv run --no-cache pytest tests/repositories/test_operacao.py tests/services/test_control_plane.py -q` falha por APIs/semântica ausentes.
- [x] **Step 3: GREEN.** Criar `renew_lease`, `interrupt_expired(now)` e `save_stage`; tornar `claim_next` retornar `None` enquanto existir run ativa. Eventos continuam na fronteira worker/service.
- [x] **Step 4: Verify GREEN.** Cobrir dono errado, histórico de lease e nenhum segundo claim.
- [x] **Step 5: Commit.** `feat(studio): enforce worker lease ownership`.

### Task 2: Worker genérico e ciclo de etapa

**Files:** Create `src/forge/services/worker.py`; modify `src/forge/domain/operacao.py`; create `tests/services/test_worker.py`.

- [x] **Step 1: RED.** Fakes provam `pending → running → succeeded`; resultado falho torna etapa/run `failed`; executor ausente registra `executor_missing` sem avançar.
- [x] **Step 2: GREEN.** Definir `StageContext`, `EventSink`, `StageResult(gate_status, current_items=0, total_items=0)`, protocolo `StageExecutor.execute(context, emit)`, e `StudioWorker.run_once()`. `run_once` reconcilia leases, reivindica uma run, executa só a etapa corrente, persiste `stage.started`, `stage.succeeded` ou `stage.failed`.
- [x] **Step 3: Verify GREEN.** `uv run --no-cache pytest tests/services/test_worker.py -q`.
- [x] **Step 4: Commit.** `feat(studio): add deterministic stage worker`.

### Task 3: Heartbeat e pausa cooperativa

**Files:** Modify `src/forge/services/worker.py`; modify `tests/services/test_worker.py`.

- [x] **Step 1: RED.** Testar tick de heartbeat, perda de propriedade e pausa aceita aplicada somente após retorno do executor.
- [x] **Step 2: GREEN.** Implementar `LeaseHeartbeat.tick()` e wrapper daemon; consultar comandos pause `accepted` via `ComandosRepository`; limpar lease ao pausar e marcar comando `applied`.
- [x] **Step 3: Verify GREEN.** Uma pausa/evento; progresso concluído preservado.
- [x] **Step 4: Commit.** `feat(studio): pause runs at safe worker boundaries`.

### Task 4: Adaptador subprocesso JSONL confiável

**Files:** Create `src/forge/services/subprocesso.py`; modify `src/forge/services/worker.py`; create `tests/services/test_subprocesso.py`.

- [x] **Step 1: RED.** Filho `sys.executable -c`: JSON válido vira evento; stdout inválido gera `worker.invalid_event`; exit não-zero gera `subprocess_failed` com stderr limitado.
- [x] **Step 2: GREEN.** Criar `SubprocessExecutor(argv)`; recusar argv vazio; usar `Popen` sem shell; aceitar só objeto com `kind`, `level`, `message` não vazios e `payload` objeto.
- [x] **Step 3: Verify GREEN.** `uv run --no-cache pytest tests/services/test_subprocesso.py tests/services/test_worker.py -q`.
- [x] **Step 4: Commit.** `feat(studio): persist worker subprocess events`.

### Task 5: Configuração e prova de recuperação

**Files:** Modify `src/forge/infrastructure/config.py`, `src/forge/services/studio.py`; create `tests/services/test_worker_acceptance.py`.

- [x] **Step 1: RED.** Enfileirar duas runs, expirar a primeira, reiniciar worker, verificar primeira `interrupted`, segunda na fila; retomar e provar só uma claim posterior.
- [x] **Step 2: GREEN.** Adicionar `worker_lease_seconds=15`, `worker_heartbeat_seconds=5`; rejeitar heartbeat maior/igual ao lease; expor `build_worker(settings, executors, worker_id)`.
- [x] **Step 3: Verify.** Rodar `uv run --no-cache pytest -q`, `uv run --no-cache python -m compileall -q src/forge` e `git diff --check`.
- [x] **Step 4: Commit.** `test(studio): prove worker recovery and single-run lease`.

## Handoff

Marco 2 termina no worker genérico testado. A reconciliação de artefatos (hash,
arquivos ausentes e órfãos) fica explicitamente adiada para o marco dos
executores, que terá validadores de artefato; este marco genérico não possui
esses validadores. Não iniciar reconciliação ampla de mídia, executores reais,
API/dashboard ou launcher sem nova spec/plano aprovado.

## Completion

Tasks 1–5 concluídas. Commits principais do marco:

- `c9283d2` — `feat(studio): enforce worker lease ownership`
- `5d5ebb2` — `feat(studio): add deterministic stage worker`
- `23329ca` — `feat(studio): pause runs at safe worker boundaries`
- `9d167a6` — `feat(studio): persist worker subprocess events`
- `824bbea` — `test(studio): prove worker recovery and single-run lease`
- `a8059f2`, `1811029`, `c31274f`, `cba330e` — hardening de ciclo de vida e contenção Windows/POSIX
- `ceee765` — polling resiliente do PID nos testes

Minor parked: arquivo de PID com conteúdo numérico parcialmente escrito continua uma observação de baixo risco no helper de teste; contenção de produção não é afetada.
