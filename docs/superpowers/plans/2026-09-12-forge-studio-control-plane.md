# Forge Studio Control Plane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir o domínio operacional persistente do Forge Studio — fila, runs, etapas, comandos e eventos — sem API, frontend ou execução real de mídia.

**Architecture:** O marco adiciona um aggregate operacional Pydantic, uma máquina de estados pura e repositórios SQLite ligados por transações curtas em WAL. `ControlPlaneService` é a única fronteira de escrita de alto nível: cria vídeos/runs, registra comandos idempotentes e invalida dependências sem apagar histórico. Arquivos de mídia continuam fora do banco; este marco persiste apenas metadados.

**Tech Stack:** Python 3.12, Pydantic 2, `sqlite3` da stdlib, pytest, `uv`.

**Design spec:** `docs/superpowers/specs/2026-09-11-forge-video-studio-design.md`

---

## Scope guard

Este plano cobre somente o **Marco 1** da spec. Não criar ainda:

- FastAPI ou endpoints HTTP;
- SSE;
- worker daemon, heartbeat periódico ou supervisão de subprocesso;
- frontend Next.js;
- executores de `research`, LM Studio, TTS, ComfyUI ou FFmpeg;
- launcher PowerShell;
- importador de runs antigas.

O marco termina com uma biblioteca Python funcional e testada. Marco 2 consumirá
`claim_next()` e os comandos aqui definidos para implementar worker, lease e
heartbeat.

## Working-tree safety

O clone principal contém mudanças locais anteriores. Antes de cada commit:

```bash
git status --short
git diff --cached --name-only
```

Nunca executar `git reset`, `git restore`, `git clean` ou adicionar arquivos já
modificados fora desta lista. Os commits deste plano só podem tocar:

```text
src/forge/domain/operacao.py
src/forge/services/maquina_estados.py
src/forge/services/control_plane.py
src/forge/services/studio.py
src/forge/repositories/__init__.py
src/forge/repositories/connection.py
src/forge/repositories/schema.py
src/forge/repositories/operacao.py
src/forge/repositories/comandos.py
src/forge/repositories/eventos.py
src/forge/infrastructure/config.py
data/.gitignore
tests/domain/test_operacao.py
tests/services/test_maquina_estados.py
tests/services/test_control_plane.py
tests/services/test_studio.py
tests/services/test_control_plane_acceptance.py
tests/repositories/test_connection.py
tests/repositories/test_schema.py
tests/repositories/test_operacao.py
tests/repositories/test_comandos.py
tests/repositories/test_eventos.py
tests/test_config.py
```

## File map

| File | Responsibility |
|---|---|
| `domain/operacao.py` | Enums, modelos Pydantic, ordem canônica das etapas e grafo de dependências |
| `services/maquina_estados.py` | Transições puras e erros de domínio |
| `repositories/connection.py` | Conexões SQLite, WAL, busy timeout e transações |
| `repositories/schema.py` | DDL idempotente e versão do schema |
| `repositories/operacao.py` | Aggregate `videos/runs/stage_runs/work_items/artifacts` e claim da fila |
| `repositories/comandos.py` | Persistência idempotente de comandos |
| `repositories/eventos.py` | Event log append-only e paginação por cursor |
| `services/control_plane.py` | Transações de aplicação: enqueue, pause, resume e retry de etapa |
| `infrastructure/config.py` | Caminho configurável do banco do Studio |
| `data/.gitignore` | Mantém banco/WAL/SHM fora do Git |

---

### Task 1: Vocabulário operacional e grafo de dependências

**Files:**
- Create: `src/forge/domain/operacao.py`
- Create: `tests/domain/test_operacao.py`

- [ ] **Step 1: Write failing tests for canonical stages and Pydantic models**

```python
# tests/domain/test_operacao.py
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from forge.domain.operacao import (
    ETAPAS,
    CommandStatus,
    CommandType,
    Run,
    RunStatus,
    StageName,
    StageStatus,
    dependentes_de,
)


def test_ordem_canônica_põe_audio_antes_de_imagens():
    assert ETAPAS == (
        StageName.PREPARACAO,
        StageName.PESQUISA,
        StageName.ROTEIRO,
        StageName.PLANO_MIDIA,
        StageName.AUDIO,
        StageName.IMAGENS,
        StageName.MONTAGEM,
        StageName.VALIDACAO,
    )
    assert ETAPAS.index(StageName.AUDIO) < ETAPAS.index(StageName.IMAGENS)


def test_dependentes_de_roteiro_inclui_tudo_apos_roteiro():
    assert dependentes_de(StageName.ROTEIRO) == (
        StageName.ROTEIRO,
        StageName.PLANO_MIDIA,
        StageName.AUDIO,
        StageName.IMAGENS,
        StageName.MONTAGEM,
        StageName.VALIDACAO,
    )


def test_run_recusa_prioridade_fora_de_0_a_100():
    with pytest.raises(ValidationError):
        Run(
            id="r1",
            video_id="v1",
            status=RunStatus.QUEUED,
            priority=101,
            queue_position=1,
            config_snapshot={},
            workflow_version=1,
            git_commit="abc",
            created_at=datetime.now(UTC),
        )


def test_enums_serializam_com_valores_estaveis():
    assert RunStatus.PAUSING.value == "pausing"
    assert StageStatus.INVALIDATED.value == "invalidated"
    assert CommandType.RETRY_STAGE.value == "retry_stage"
    assert CommandStatus.PENDING.value == "pending"
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
uv run pytest tests/domain/test_operacao.py -q
```

Expected: collection fails with `ModuleNotFoundError: forge.domain.operacao`.

- [ ] **Step 3: Implement enums, constants and models**

Create `src/forge/domain/operacao.py` with:

```python
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class RunStatus(StrEnum):
    QUEUED = "queued"
    PREPARING = "preparing"
    RUNNING = "running"
    PAUSING = "pausing"
    PAUSED = "paused"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"


class StageName(StrEnum):
    PREPARACAO = "preparacao"
    PESQUISA = "pesquisa"
    ROTEIRO = "roteiro"
    PLANO_MIDIA = "plano_midia"
    AUDIO = "audio"
    IMAGENS = "imagens"
    MONTAGEM = "montagem"
    VALIDACAO = "validacao"


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PAUSING = "pausing"
    PAUSED = "paused"
    INTERRUPTED = "interrupted"
    INVALIDATED = "invalidated"


class ItemStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INVALIDATED = "invalidated"


class CommandType(StrEnum):
    PAUSE = "pause"
    RESUME = "resume"
    RETRY_STAGE = "retry_stage"


class CommandStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    APPLIED = "applied"
    REJECTED = "rejected"


ETAPAS = tuple(StageName)


def dependentes_de(stage: StageName) -> tuple[StageName, ...]:
    return ETAPAS[ETAPAS.index(stage):]


class Video(BaseModel):
    id: str
    tema: str = Field(min_length=1, max_length=500)
    tese: str | None = Field(default=None, max_length=2000)
    created_at: datetime
    updated_at: datetime


class Run(BaseModel):
    id: str
    video_id: str
    status: RunStatus
    priority: int = Field(ge=0, le=100)
    queue_position: int = Field(ge=1)
    config_snapshot: dict[str, Any]
    workflow_version: int = Field(ge=1)
    git_commit: str
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    pause_requested_at: datetime | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    failure_code: str | None = None
    failure_message: str | None = None


class StageRun(BaseModel):
    id: str
    run_id: str
    stage: StageName
    attempt: int = Field(ge=1)
    status: StageStatus
    current_items: int = Field(default=0, ge=0)
    total_items: int = Field(default=0, ge=0)
    progress: float = Field(default=0, ge=0, le=1)
    gate_status: str | None = None
    input_hash: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    failure_code: str | None = None
    failure_message: str | None = None


class WorkItem(BaseModel):
    id: str
    stage_run_id: str
    item_key: str
    status: ItemStatus
    input: dict[str, Any]
    input_hash: str
    attempts: int = Field(default=0, ge=0)
    duration_ms: int | None = Field(default=None, ge=0)
    failure_code: str | None = None
    failure_message: str | None = None


class Artifact(BaseModel):
    id: str
    run_id: str
    stage_run_id: str
    work_item_id: str | None = None
    kind: str
    relative_path: str
    sha256: str
    size_bytes: int = Field(ge=0)
    mime_type: str
    metadata: dict[str, Any]
    is_current: bool
    created_at: datetime


class Event(BaseModel):
    id: int
    run_id: str | None = None
    stage_run_id: str | None = None
    work_item_id: str | None = None
    kind: str
    level: str
    message: str
    payload: dict[str, Any]
    created_at: datetime


class Command(BaseModel):
    id: str
    run_id: str
    type: CommandType
    stage: StageName | None = None
    idempotency_key: str
    status: CommandStatus
    result: dict[str, Any]
    created_at: datetime
    applied_at: datetime | None = None
```

- [ ] **Step 4: Run domain tests**

```bash
uv run pytest tests/domain/test_operacao.py -q
```

Expected: `4 passed`.

- [ ] **Step 5: Commit only Task 1 files**

```bash
git add src/forge/domain/operacao.py tests/domain/test_operacao.py
git diff --cached --check
git commit -m "feat(studio): define operational domain"
```

---

### Task 2: Pure run and stage state machines

**Files:**
- Create: `src/forge/services/maquina_estados.py`
- Create: `tests/services/test_maquina_estados.py`

- [ ] **Step 1: Write failing transition tests**

```python
# tests/services/test_maquina_estados.py
import pytest

from forge.domain.operacao import RunStatus, StageStatus
from forge.services.maquina_estados import TransicaoInvalida, mudar_run, mudar_etapa


def test_run_running_pode_solicitar_pausa():
    assert mudar_run(RunStatus.RUNNING, RunStatus.PAUSING) is RunStatus.PAUSING


def test_run_completed_so_volta_a_fila_por_retry():
    with pytest.raises(TransicaoInvalida):
        mudar_run(RunStatus.COMPLETED, RunStatus.QUEUED)
    assert mudar_run(
        RunStatus.COMPLETED, RunStatus.QUEUED, motivo="retry_stage"
    ) is RunStatus.QUEUED


def test_etapa_succeeded_pode_ser_invalidada():
    assert mudar_etapa(
        StageStatus.SUCCEEDED, StageStatus.INVALIDATED
    ) is StageStatus.INVALIDATED


def test_etapa_pending_nao_pode_pular_para_succeeded():
    with pytest.raises(TransicaoInvalida, match="pending -> succeeded"):
        mudar_etapa(StageStatus.PENDING, StageStatus.SUCCEEDED)
```

- [ ] **Step 2: Verify RED**

```bash
uv run pytest tests/services/test_maquina_estados.py -q
```

Expected: import fails because `maquina_estados.py` does not exist.

- [ ] **Step 3: Implement explicit transition maps**

Create `src/forge/services/maquina_estados.py`:

```python
from forge.domain.operacao import RunStatus, StageStatus


class TransicaoInvalida(ValueError):
    pass


_RUN_TRANSITIONS = {
    RunStatus.QUEUED: {RunStatus.PREPARING, RunStatus.CANCELLED},
    RunStatus.PREPARING: {
        RunStatus.RUNNING, RunStatus.PAUSING, RunStatus.FAILED,
        RunStatus.INTERRUPTED,
    },
    RunStatus.RUNNING: {
        RunStatus.PAUSING, RunStatus.VALIDATING, RunStatus.FAILED,
        RunStatus.INTERRUPTED,
    },
    RunStatus.PAUSING: {
        RunStatus.PAUSED, RunStatus.FAILED, RunStatus.INTERRUPTED,
    },
    RunStatus.PAUSED: {RunStatus.QUEUED, RunStatus.CANCELLED},
    RunStatus.VALIDATING: {
        RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.INTERRUPTED,
    },
    RunStatus.FAILED: {RunStatus.QUEUED, RunStatus.CANCELLED},
    RunStatus.INTERRUPTED: {RunStatus.QUEUED, RunStatus.CANCELLED},
    RunStatus.COMPLETED: set(),
    RunStatus.CANCELLED: set(),
}

_STAGE_TRANSITIONS = {
    StageStatus.PENDING: {StageStatus.RUNNING, StageStatus.INVALIDATED},
    StageStatus.RUNNING: {
        StageStatus.SUCCEEDED, StageStatus.FAILED, StageStatus.PAUSING,
        StageStatus.INTERRUPTED,
    },
    StageStatus.PAUSING: {
        StageStatus.PAUSED, StageStatus.FAILED, StageStatus.INTERRUPTED,
    },
    StageStatus.PAUSED: {StageStatus.PENDING, StageStatus.INVALIDATED},
    StageStatus.FAILED: {StageStatus.PENDING, StageStatus.INVALIDATED},
    StageStatus.INTERRUPTED: {StageStatus.PENDING, StageStatus.INVALIDATED},
    StageStatus.SUCCEEDED: {StageStatus.INVALIDATED},
    StageStatus.INVALIDATED: {StageStatus.PENDING},
}


def mudar_run(
    atual: RunStatus,
    destino: RunStatus,
    *,
    motivo: str | None = None,
) -> RunStatus:
    if atual is RunStatus.COMPLETED and destino is RunStatus.QUEUED:
        if motivo == "retry_stage":
            return destino
    if destino not in _RUN_TRANSITIONS[atual]:
        raise TransicaoInvalida(f"run: {atual.value} -> {destino.value}")
    return destino


def mudar_etapa(atual: StageStatus, destino: StageStatus) -> StageStatus:
    if destino not in _STAGE_TRANSITIONS[atual]:
        raise TransicaoInvalida(f"etapa: {atual.value} -> {destino.value}")
    return destino
```

- [ ] **Step 4: Run state-machine tests and domain regression**

```bash
uv run pytest tests/domain/test_operacao.py tests/services/test_maquina_estados.py -q
```

Expected: `8 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/forge/services/maquina_estados.py tests/services/test_maquina_estados.py
git diff --cached --check
git commit -m "feat(studio): enforce operational state transitions"
```

---

### Task 3: SQLite connection and idempotent schema

**Files:**
- Create: `src/forge/repositories/__init__.py`
- Create: `src/forge/repositories/connection.py`
- Create: `src/forge/repositories/schema.py`
- Create: `tests/repositories/test_connection.py`
- Create: `tests/repositories/test_schema.py`
- Create: `data/.gitignore`

- [ ] **Step 1: Write failing connection tests**

```python
# tests/repositories/test_connection.py
import sqlite3

import pytest

from forge.repositories.connection import Database


def test_connection_habilita_wal_foreign_keys_e_busy_timeout(tmp_path):
    db = Database(tmp_path / "forge.db")
    with db.connection() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_transaction_faz_rollback_em_erro(tmp_path):
    db = Database(tmp_path / "forge.db")
    with db.connection() as conn:
        conn.execute("CREATE TABLE x (id INTEGER PRIMARY KEY)")
    with pytest.raises(RuntimeError):
        with db.transaction(immediate=True) as conn:
            conn.execute("INSERT INTO x DEFAULT VALUES")
            raise RuntimeError("falha")
    with db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM x").fetchone()[0] == 0
```

- [ ] **Step 2: Write failing schema tests**

```python
# tests/repositories/test_schema.py
from forge.repositories.connection import Database
from forge.repositories.schema import TABLES, init_db


def test_init_db_cria_todas_as_tabelas(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)
    with db.connection() as conn:
        names = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert TABLES <= names


def test_init_db_e_idempotente(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)
    init_db(db)
    with db.connection() as conn:
        assert conn.execute("SELECT version FROM schema_version").fetchone()[0] == 1
```

`TABLES` must equal:

```python
{
    "schema_version", "videos", "runs", "stage_runs", "work_items",
    "artifacts", "events", "commands",
}
```

- [ ] **Step 3: Verify RED**

```bash
uv run pytest tests/repositories/test_connection.py tests/repositories/test_schema.py -q
```

Expected: import failure for `forge.repositories`.

- [ ] **Step 4: Implement `Database`**

Create `src/forge/repositories/connection.py`:

```python
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class Database:
    def __init__(self, path: Path, *, busy_timeout_ms: int = 5000) -> None:
        self.path = Path(path)
        self.busy_timeout_ms = busy_timeout_ms

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, isolation_level=None, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            try:
                yield conn
            except BaseException:
                conn.rollback()
                raise
            else:
                conn.commit()
```

- [ ] **Step 5: Implement schema v1**

Create `src/forge/repositories/schema.py`. Define `SCHEMA_VERSION = 1`, `TABLES`
and `SCHEMA_SQL`. DDL must implement every table from spec section 7, including:

```sql
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    tema TEXT NOT NULL CHECK(length(trim(tema)) > 0),
    tese TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL REFERENCES videos(id),
    status TEXT NOT NULL,
    priority INTEGER NOT NULL CHECK(priority BETWEEN 0 AND 100),
    queue_position INTEGER NOT NULL CHECK(queue_position >= 1),
    config_snapshot_json TEXT NOT NULL,
    workflow_version INTEGER NOT NULL CHECK(workflow_version >= 1),
    git_commit TEXT NOT NULL,
    lease_owner TEXT,
    lease_expires_at TEXT,
    pause_requested_at TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    failure_code TEXT,
    failure_message TEXT
);

CREATE TABLE IF NOT EXISTS stage_runs (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    stage TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK(attempt >= 1),
    status TEXT NOT NULL,
    current_items INTEGER NOT NULL DEFAULT 0 CHECK(current_items >= 0),
    total_items INTEGER NOT NULL DEFAULT 0 CHECK(total_items >= 0),
    progress REAL NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 1),
    gate_status TEXT,
    input_hash TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    failure_code TEXT,
    failure_message TEXT,
    UNIQUE(run_id, stage, attempt)
);

CREATE TABLE IF NOT EXISTS work_items (
    id TEXT PRIMARY KEY,
    stage_run_id TEXT NOT NULL REFERENCES stage_runs(id),
    item_key TEXT NOT NULL,
    status TEXT NOT NULL,
    input_json TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
    duration_ms INTEGER CHECK(duration_ms >= 0),
    failure_code TEXT,
    failure_message TEXT,
    UNIQUE(stage_run_id, item_key)
);

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    stage_run_id TEXT NOT NULL REFERENCES stage_runs(id),
    work_item_id TEXT REFERENCES work_items(id),
    kind TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
    mime_type TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 1 CHECK(is_current IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT REFERENCES runs(id),
    stage_run_id TEXT REFERENCES stage_runs(id),
    work_item_id TEXT REFERENCES work_items(id),
    kind TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS commands (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    type TEXT NOT NULL,
    stage TEXT,
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    applied_at TEXT,
    UNIQUE(run_id, idempotency_key)
);
```

Add indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_runs_queue
ON runs(status, priority DESC, queue_position ASC, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_stage_runs_current
ON stage_runs(run_id, stage, attempt DESC);
CREATE INDEX IF NOT EXISTS idx_artifacts_current
ON artifacts(run_id, is_current, kind);
CREATE INDEX IF NOT EXISTS idx_events_cursor
ON events(run_id, id);
CREATE INDEX IF NOT EXISTS idx_commands_pending
ON commands(status, created_at);
```

`init_db(db)` must run all DDL in one `BEGIN IMMEDIATE`, insert version 1 when
empty, and raise `RuntimeError` if the stored version is greater than the code's
version.

- [ ] **Step 6: Ignore runtime database files locally**

Create `data/.gitignore`:

```gitignore
*
!.gitignore
```

- [ ] **Step 7: Run repository-foundation tests**

```bash
uv run pytest tests/repositories/test_connection.py tests/repositories/test_schema.py -q
```

Expected: `4 passed`.

- [ ] **Step 8: Commit**

```bash
git add src/forge/repositories data/.gitignore tests/repositories/test_connection.py tests/repositories/test_schema.py
git diff --cached --check
git commit -m "feat(studio): add SQLite operational schema"
```

---

### Task 4: Operational aggregate repository and atomic queue claim

**Files:**
- Create: `src/forge/repositories/operacao.py`
- Create: `tests/repositories/test_operacao.py`

- [ ] **Step 1: Write failing tests for enqueue, projections and claim**

```python
# tests/repositories/test_operacao.py
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from forge.domain.operacao import (
    ETAPAS,
    Artifact,
    RunStatus,
    StageName,
    StageStatus,
)
from forge.repositories.connection import Database
from forge.repositories.operacao import OperacaoRepository
from forge.repositories.schema import init_db


def _repo(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)
    return db


def test_create_video_and_run_initializes_all_stages(tmp_path):
    db = _repo(tmp_path)
    with db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        video, run = repo.create_video_and_run(
            tema="O peso de ser livre",
            tese=None,
            priority=50,
            config_snapshot={"preset": "local-recomendado-v1"},
            workflow_version=1,
            git_commit="abc123",
        )
    with db.connection() as conn:
        repo = OperacaoRepository(conn)
        stages = repo.current_stages(run.id)
    assert video.tema == "O peso de ser livre"
    assert run.status is RunStatus.QUEUED
    assert [s.stage for s in stages] == list(ETAPAS)
    assert all(s.status is StageStatus.PENDING for s in stages)


def test_queue_orders_priority_then_position(tmp_path):
    db = _repo(tmp_path)
    with db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        low = repo.create_video_and_run(
            tema="baixo", tese=None, priority=10, config_snapshot={},
            workflow_version=1, git_commit="x",
        )[1]
        high = repo.create_video_and_run(
            tema="alto", tese=None, priority=90, config_snapshot={},
            workflow_version=1, git_commit="x",
        )[1]
    with db.connection() as conn:
        queued = OperacaoRepository(conn).list_queue()
    assert [r.id for r in queued] == [high.id, low.id]


def test_two_claims_never_return_same_run(tmp_path):
    db = _repo(tmp_path)
    with db.transaction(immediate=True) as conn:
        OperacaoRepository(conn).create_video_and_run(
            tema="único", tese=None, priority=50, config_snapshot={},
            workflow_version=1, git_commit="x",
        )

    def claim(worker):
        with db.transaction(immediate=True) as conn:
            return OperacaoRepository(conn).claim_next(worker, lease_seconds=15)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ["w1", "w2"]))
    claimed = [r for r in results if r is not None]
    assert len(claimed) == 1
    assert claimed[0].status is RunStatus.PREPARING
```

Also test:

```python
def test_current_stages_returns_highest_attempt_per_stage(tmp_path):
    db = _repo(tmp_path)
    with db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        _, run = repo.create_video_and_run(
            tema="tema", tese=None, priority=50, config_snapshot={},
            workflow_version=1, git_commit="x",
        )
        repo.invalidate_from_stage(run.id, StageName.ROTEIRO)
    with db.connection() as conn:
        stages = OperacaoRepository(conn).current_stages(run.id)
    attempts = {stage.stage: stage.attempt for stage in stages}
    assert attempts[StageName.PESQUISA] == 1
    assert attempts[StageName.ROTEIRO] == 2
    assert attempts[StageName.VALIDACAO] == 2


def test_mark_artifacts_not_current_preserves_rows(tmp_path):
    db = _repo(tmp_path)
    with db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        _, run = repo.create_video_and_run(
            tema="tema", tese=None, priority=50, config_snapshot={},
            workflow_version=1, git_commit="x",
        )
        stage = repo.current_stages(run.id)[2]
        repo.register_artifact(Artifact(
            id="artifact-1",
            run_id=run.id,
            stage_run_id=stage.id,
            kind="roteiro",
            relative_path="roteiro.md",
            sha256="a" * 64,
            size_bytes=12,
            mime_type="text/markdown",
            metadata={},
            is_current=True,
            created_at=datetime.now(UTC),
        ))
        changed = repo.invalidate_artifacts(run.id, (StageName.ROTEIRO,))
    with db.connection() as conn:
        artifacts = OperacaoRepository(conn).list_artifacts(
            run.id, current_only=False
        )
    assert changed == 1
    assert len(artifacts) == 1
    assert artifacts[0].is_current is False


def test_get_run_returns_none_for_unknown_id(tmp_path):
    db = _repo(tmp_path)
    with db.connection() as conn:
        assert OperacaoRepository(conn).get_run("missing") is None
```

The artifact test must register one artifact, invalidate it, then assert the row
still exists with `is_current is False`.

- [ ] **Step 2: Verify RED**

```bash
uv run pytest tests/repositories/test_operacao.py -q
```

Expected: import failure for `forge.repositories.operacao`.

- [ ] **Step 3: Implement repository row mapping and creation**

Create `OperacaoRepository(conn)` with the following exact public API:

- constructor `OperacaoRepository(conn: sqlite3.Connection)`;
- `create_video_and_run(*, tema: str, tese: str | None, priority: int,
  config_snapshot: dict, workflow_version: int, git_commit: str) -> tuple[Video, Run]`;
- `get_run(run_id: str) -> Run | None`;
- `list_queue() -> list[Run]`;
- `list_runs(*, limit: int = 50, offset: int = 0) -> list[Run]`;
- `current_stages(run_id: str) -> list[StageRun]`;
- `claim_next(worker_id: str, *, lease_seconds: int) -> Run | None`;
- `save_run(run: Run) -> Run`;
- `invalidate_from_stage(run_id: str, stage: StageName) -> list[StageRun]`;
- `register_artifact(artifact: Artifact) -> Artifact`;
- `invalidate_artifacts(run_id: str, stages: tuple[StageName, ...]) -> int`;
- `list_artifacts(run_id: str, *, current_only: bool = True) -> list[Artifact]`.

Use `save_run(run)` rather than a free-form `**fields` update. Callers obtain the
current model, use `run.model_copy(update={"status": RunStatus.QUEUED})` (including
all other fields that the transaction intentionally changes), and persist the
complete mutable run columns. This makes clearing a lease or failure explicit and
prevents arbitrary column names from reaching SQL.

- UUIDs use `uuid.uuid4()` strings.
- Times use `datetime.now(UTC)` and ISO strings.
- JSON uses `ensure_ascii=False`, `sort_keys=True`.
- Queue position is `COALESCE(MAX(queue_position), 0) + 1` among queued runs.
- `claim_next()` assumes caller opened `BEGIN IMMEDIATE`; select by priority DESC,
  queue position ASC, created time ASC; update only when status is still `queued`.
- Claimed run becomes `preparing`; set `lease_owner`, `lease_expires_at` and
  `started_at=COALESCE(started_at, now)`.
- `current_stages()` selects maximum attempt per stage and returns canonical
  `ETAPAS` order, never lexical order.
- `invalidate_from_stage()` changes current attempts to `invalidated`, creates a
  new `pending` attempt for every dependent stage, and preserves all old rows.
- Artifact invalidation updates `is_current=0`; it never deletes.
- Unknown IDs raise `KeyError` only for mutating operations; getters return
  `None`.

- [ ] **Step 4: Run aggregate tests**

```bash
uv run pytest tests/repositories/test_operacao.py -q
```

Expected: all tests pass, including the concurrent claim test.

- [ ] **Step 5: Run all repository tests**

```bash
uv run pytest tests/repositories -q
```

Expected: all repository tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/forge/repositories/operacao.py tests/repositories/test_operacao.py
git diff --cached --check
git commit -m "feat(studio): persist queue runs and stage attempts"
```

---

### Task 5: Append-only events and idempotent commands

**Files:**
- Create: `src/forge/repositories/eventos.py`
- Create: `src/forge/repositories/comandos.py`
- Create: `tests/repositories/test_eventos.py`
- Create: `tests/repositories/test_comandos.py`

- [ ] **Step 1: Write failing event tests**

```python
# tests/repositories/test_eventos.py
from forge.repositories.connection import Database
from forge.repositories.eventos import EventosRepository
from forge.repositories.operacao import OperacaoRepository
from forge.repositories.schema import init_db


def _create_run(db, tema):
    with db.transaction(immediate=True) as conn:
        return OperacaoRepository(conn).create_video_and_run(
            tema=tema,
            tese=None,
            priority=50,
            config_snapshot={},
            workflow_version=1,
            git_commit="test",
        )[1]


def test_events_are_monotonic_and_page_after_cursor(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)
    with db.transaction() as conn:
        repo = EventosRepository(conn)
        first = repo.append(
            kind="run.queued", level="info", message="Na fila", payload={}
        )
        second = repo.append(
            kind="run.started", level="info", message="Iniciada", payload={}
        )
    with db.connection() as conn:
        page = EventosRepository(conn).after(first.id, limit=100)
    assert second.id > first.id
    assert [e.id for e in page] == [second.id]


def test_events_filter_by_run_without_breaking_global_cursor(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)
    run_a = _create_run(db, "A")
    run_b = _create_run(db, "B")
    with db.transaction() as conn:
        repo = EventosRepository(conn)
        first_a = repo.append(
            run_id=run_a.id,
            kind="run.queued",
            level="info",
            message="A entrou",
            payload={},
        )
        repo.append(
            run_id=run_b.id,
            kind="run.queued",
            level="info",
            message="B entrou",
            payload={},
        )
        second_a = repo.append(
            run_id=run_a.id,
            kind="run.started",
            level="info",
            message="A iniciou",
            payload={},
        )
    with db.connection() as conn:
        page = EventosRepository(conn).after(
            first_a.id, run_id=run_a.id, limit=100
        )
    assert [event.id for event in page] == [second_a.id]
    assert second_a.id > first_a.id
```

The second test inserts interleaved events for runs A/B and asserts `after(cursor,
run_id="A")` only returns A while preserving monotonic event IDs.

- [ ] **Step 2: Write failing command tests**

```python
# tests/repositories/test_comandos.py
import pytest

from forge.domain.operacao import CommandStatus, CommandType, StageName
from forge.repositories.comandos import ComandosRepository, IdempotencyConflict
from forge.repositories.connection import Database
from forge.repositories.operacao import OperacaoRepository
from forge.repositories.schema import init_db


@pytest.fixture
def db_with_run(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)
    with db.transaction(immediate=True) as conn:
        run = OperacaoRepository(conn).create_video_and_run(
            tema="tema",
            tese=None,
            priority=50,
            config_snapshot={},
            workflow_version=1,
            git_commit="test",
        )[1]
    return db, run.id


def test_same_idempotency_key_returns_existing_command(db_with_run):
    db, run_id = db_with_run
    with db.transaction(immediate=True) as conn:
        repo = ComandosRepository(conn)
        one, created_one = repo.create_idempotent(
            run_id=run_id,
            type=CommandType.PAUSE,
            stage=None,
            idempotency_key="same-key",
            status=CommandStatus.ACCEPTED,
        )
        two, created_two = repo.create_idempotent(
            run_id=run_id,
            type=CommandType.PAUSE,
            stage=None,
            idempotency_key="same-key",
            status=CommandStatus.ACCEPTED,
        )
    assert created_one is True
    assert created_two is False
    assert two.id == one.id


def test_same_key_with_different_payload_is_rejected(db_with_run):
    db, run_id = db_with_run
    with db.transaction(immediate=True) as conn:
        repo = ComandosRepository(conn)
        repo.create_idempotent(
            run_id=run_id,
            type=CommandType.PAUSE,
            stage=None,
            idempotency_key="same-key",
            status=CommandStatus.ACCEPTED,
        )
        with pytest.raises(IdempotencyConflict):
            repo.create_idempotent(
                run_id=run_id,
                type=CommandType.RETRY_STAGE,
                stage=StageName.ROTEIRO,
                idempotency_key="same-key",
                status=CommandStatus.APPLIED,
            )
```

Put a local `db_with_run` fixture in this test module; do not modify global
`conftest.py`.

- [ ] **Step 3: Verify RED**

```bash
uv run pytest tests/repositories/test_eventos.py tests/repositories/test_comandos.py -q
```

Expected: both modules fail to import.

- [ ] **Step 4: Implement `EventosRepository`**

Public API:

- constructor `EventosRepository(conn: sqlite3.Connection)`;
- `append(*, kind: str, level: str, message: str, payload: dict,
  run_id: str | None = None, stage_run_id: str | None = None,
  work_item_id: str | None = None) -> Event`;
- `after(cursor: int, *, limit: int = 200,
  run_id: str | None = None) -> list[Event]`.

The insert must serialize `payload` with:

```python
payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
created_at = datetime.now(UTC).isoformat()
cursor = self.conn.execute(
    """INSERT INTO events (
        run_id, stage_run_id, work_item_id, kind, level, message,
        payload_json, created_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
    (
        run_id, stage_run_id, work_item_id, kind, level, message,
        payload_json, created_at,
    ),
)
event_id = cursor.lastrowid
assert event_id is not None
```

Validate `1 <= limit <= 1000`. Query `id > ? ORDER BY id ASC LIMIT ?`. When
filtering by run, cursor still refers to the global event ID.

- [ ] **Step 5: Implement `ComandosRepository`**

Public API:

- constructor `ComandosRepository(conn: sqlite3.Connection)`;
- `create_idempotent(*, run_id: str, type: CommandType,
  stage: StageName | None, idempotency_key: str,
  status: CommandStatus) -> tuple[Command, bool]`;
- `get(command_id: str) -> Command | None`;
- `pending(run_id: str) -> list[Command]`;
- `set_status(command_id: str, status: CommandStatus, *, result: dict) -> Command`.

Define the conflict explicitly:

```python
class IdempotencyConflict(ValueError):
    def __init__(self, run_id: str, idempotency_key: str) -> None:
        super().__init__(
            f"idempotency key {idempotency_key!r} already has another payload "
            f"for run {run_id}"
        )
```

`set_status()` sets `applied_at` only for `applied` or `rejected`, keeps it null
for `pending` or `accepted`, and raises `KeyError(command_id)` when absent.

`create_idempotent()` follows these rules:

1. reject blank key;
2. query existing `(run_id, idempotency_key)` first;
3. same type/stage returns existing command and `False`;
4. different type/stage raises `IdempotencyConflict`;
5. otherwise insert and return `(command, True)`;
6. never catch unrelated `sqlite3.IntegrityError` as idempotency success.

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/repositories/test_eventos.py tests/repositories/test_comandos.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/forge/repositories/eventos.py src/forge/repositories/comandos.py tests/repositories/test_eventos.py tests/repositories/test_comandos.py
git diff --cached --check
git commit -m "feat(studio): add event log and idempotent commands"
```

---

### Task 6: Transactional `ControlPlaneService`

**Files:**
- Create: `src/forge/services/control_plane.py`
- Create: `tests/services/test_control_plane.py`

- [ ] **Step 1: Write failing enqueue and idempotent pause tests**

```python
# tests/services/test_control_plane.py
from datetime import UTC, datetime

import pytest

from forge.domain.operacao import (
    Artifact,
    CommandStatus,
    RunStatus,
    StageName,
    StageStatus,
)
from forge.repositories.connection import Database
from forge.repositories.operacao import OperacaoRepository
from forge.repositories.schema import init_db
from forge.services.control_plane import ControlPlaneService
from forge.services.maquina_estados import TransicaoInvalida


def _service(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)
    return ControlPlaneService(db, now=None)


def _enqueue(service):
    return service.enqueue_video(
        tema="tema",
        tese=None,
        priority=50,
        config_snapshot={},
        workflow_version=1,
        git_commit="test",
    )[1]


def _set_run_status(service, run_id, status):
    with service.db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        run = repo.get_run(run_id)
        assert run is not None
        repo.save_run(run.model_copy(update={"status": status}))


def _command_count(service, run_id):
    with service.db.connection() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM commands WHERE run_id = ?", (run_id,)
        ).fetchone()[0]


def test_enqueue_is_atomic_and_records_event(tmp_path):
    service = _service(tmp_path)
    video, run = service.enqueue_video(
        tema="O peso de ser livre",
        tese=None,
        priority=50,
        config_snapshot={"preset": "local-recomendado-v1"},
        workflow_version=1,
        git_commit="abc123",
    )
    detail = service.get_run(run.id)
    assert video.id == run.video_id
    assert detail.run.status is RunStatus.QUEUED
    assert len(detail.stages) == 8
    assert [e.kind for e in service.events_after(0, run_id=run.id)] == ["run.queued"]


def test_pause_is_idempotent_and_moves_running_to_pausing(tmp_path):
    service = _service(tmp_path)
    _, run = service.enqueue_video(
        tema="tema", tese=None, priority=50, config_snapshot={},
        workflow_version=1, git_commit="x",
    )
    _set_run_status(service, run.id, RunStatus.RUNNING)
    one = service.request_pause(run.id, idempotency_key="pause-1")
    two = service.request_pause(run.id, idempotency_key="pause-1")
    assert one.id == two.id
    assert one.status is CommandStatus.ACCEPTED
    assert service.get_run(run.id).run.status is RunStatus.PAUSING
    assert [e.kind for e in service.events_after(0, run_id=run.id)].count(
        "command.pause_requested"
    ) == 1
```

The private helpers shown above change setup state through
`OperacaoRepository.save_run()` inside a transaction. Do not expose any
`_set_status_for_test` method in production.

- [ ] **Step 2: Write failing resume and retry tests**

```python
def test_resume_paused_returns_run_to_queue(tmp_path):
    service = _service(tmp_path)
    run = _enqueue(service)
    _set_run_status(service, run.id, RunStatus.PAUSED)

    command = service.request_resume(run.id, idempotency_key="resume-1")

    assert command.status is CommandStatus.APPLIED
    assert service.get_run(run.id).run.status is RunStatus.QUEUED
    assert service.events_after(0, run_id=run.id)[-1].kind == "run.queued"


def test_resume_running_is_rejected_without_writing_command(tmp_path):
    service = _service(tmp_path)
    run = _enqueue(service)
    _set_run_status(service, run.id, RunStatus.RUNNING)

    with pytest.raises(TransicaoInvalida):
        service.request_resume(run.id, idempotency_key="resume-invalid")

    assert _command_count(service, run.id) == 0
    assert service.get_run(run.id).run.status is RunStatus.RUNNING


def test_retry_roteiro_invalidates_downstream_and_preserves_history(tmp_path):
    service = _service(tmp_path)
    _, run = _enqueue(service)
    _set_run_status(service, run.id, RunStatus.FAILED)
    before = service.get_run(run.id).stages

    command = service.request_retry_stage(
        run.id,
        StageName.ROTEIRO,
        idempotency_key="retry-roteiro-1",
    )

    after = service.get_run(run.id)
    attempts = {stage.stage: stage.attempt for stage in after.stages}
    assert command.status is CommandStatus.APPLIED
    assert after.run.status is RunStatus.QUEUED
    assert attempts[StageName.PESQUISA] == 1
    assert attempts[StageName.ROTEIRO] == 2
    assert attempts[StageName.VALIDACAO] == 2
    assert all(
        stage.status is StageStatus.PENDING
        for stage in after.stages
        if stage.stage in (
            StageName.ROTEIRO, StageName.PLANO_MIDIA, StageName.AUDIO,
            StageName.IMAGENS, StageName.MONTAGEM, StageName.VALIDACAO,
        )
    )
    assert before[1].attempt == 1
```

Also test:

```python
def test_retry_running_is_rejected_with_no_side_effects(tmp_path):
    service = _service(tmp_path)
    run = _enqueue(service)
    _set_run_status(service, run.id, RunStatus.RUNNING)
    attempts_before = [s.attempt for s in service.get_run(run.id).stages]

    with pytest.raises(TransicaoInvalida):
        service.request_retry_stage(
            run.id,
            StageName.ROTEIRO,
            idempotency_key="retry-invalid",
        )

    assert _command_count(service, run.id) == 0
    assert [s.attempt for s in service.get_run(run.id).stages] == attempts_before


def test_retry_same_idempotency_key_does_not_create_attempt_three(tmp_path):
    service = _service(tmp_path)
    run = _enqueue(service)
    _set_run_status(service, run.id, RunStatus.FAILED)
    first = service.request_retry_stage(
        run.id, StageName.ROTEIRO, idempotency_key="retry-once"
    )
    second = service.request_retry_stage(
        run.id, StageName.ROTEIRO, idempotency_key="retry-once"
    )
    assert first.id == second.id
    assert service.get_run(run.id).stages[2].attempt == 2


def test_retry_marks_old_artifacts_not_current(tmp_path):
    service = _service(tmp_path)
    run = _enqueue(service)
    _set_run_status(service, run.id, RunStatus.FAILED)
    with service.db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        roteiro_stage = repo.current_stages(run.id)[2]
        repo.register_artifact(Artifact(
            id="old-script",
            run_id=run.id,
            stage_run_id=roteiro_stage.id,
            kind="roteiro",
            relative_path="roteiro.md",
            sha256="b" * 64,
            size_bytes=100,
            mime_type="text/markdown",
            metadata={},
            is_current=True,
            created_at=datetime.now(UTC),
        ))

    service.request_retry_stage(
        run.id, StageName.ROTEIRO, idempotency_key="retry-artifact"
    )

    assert service.get_run(run.id).artifacts == []
    with service.db.connection() as conn:
        old = OperacaoRepository(conn).list_artifacts(
            run.id, current_only=False
        )
    assert len(old) == 1
    assert old[0].is_current is False
```

- [ ] **Step 3: Verify RED**

```bash
uv run pytest tests/services/test_control_plane.py -q
```

Expected: import failure for `forge.services.control_plane`.

- [ ] **Step 4: Implement read projection and service**

Create `src/forge/services/control_plane.py` with the imports and projection below:

```python
from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel

from forge.domain.operacao import (
    Artifact, Command, CommandStatus, CommandType, Event, Run, RunStatus,
    StageName, StageRun, Video, dependentes_de,
)
from forge.repositories.comandos import ComandosRepository
from forge.repositories.connection import Database
from forge.repositories.eventos import EventosRepository
from forge.repositories.operacao import OperacaoRepository
from forge.services.maquina_estados import mudar_run


class RunDetail(BaseModel):
    run: Run
    stages: list[StageRun]
    artifacts: list[Artifact]
```

`ControlPlaneService` has constructor
`(db: Database, *, now: Callable[[], datetime] | None = None)` and stores
`now or (lambda: datetime.now(UTC))`. Expose this exact public API:

- `enqueue_video(*, tema: str, tese: str | None, priority: int,
  config_snapshot: dict, workflow_version: int,
  git_commit: str) -> tuple[Video, Run]`;
- `get_run(run_id: str) -> RunDetail`;
- `list_queue() -> list[Run]`;
- `list_runs(*, limit: int = 50, offset: int = 0) -> list[Run]`;
- `events_after(cursor: int, *, run_id: str | None = None,
  limit: int = 200) -> list[Event]`;
- `claim_next(worker_id: str, *, lease_seconds: int) -> Run | None`;
- `request_pause(run_id: str, *, idempotency_key: str) -> Command`;
- `request_resume(run_id: str, *, idempotency_key: str) -> Command`;
- `request_retry_stage(run_id: str, stage: StageName, *,
  idempotency_key: str) -> Command`.

`claim_next()` is the future worker boundary. In one `BEGIN IMMEDIATE`, call the
aggregate repository claim and, when a run is returned, append `run.claimed` with
`{"worker_id": worker_id, "lease_seconds": lease_seconds}`. Return `None` without
an event when the queue is empty.

- `enqueue_video()` inserts video, run, eight stage rows and `run.queued` event in
  one `BEGIN IMMEDIATE`.
- Every command checks for existing idempotency key **before** applying side
  effects. Existing identical command returns immediately.
- `request_pause()` accepts only `preparing`, `running` or `validating`; transitions
  to `pausing`, sets `pause_requested_at`, stores command as `accepted`, appends
  `command.pause_requested`.
- `request_resume()` accepts only `paused`, `failed` or `interrupted`; clears
  lease/failure, transitions to `queued`, stores `applied`, appends `run.queued`.
- `request_retry_stage()` accepts only `paused`, `failed` or `completed`;
  invalidates target and downstream stage attempts, marks their artifacts
  non-current, creates new pending attempts, transitions run to `queued` with
  reason `retry_stage`, stores `applied`, appends `stages.invalidated` with the
  exact stage values and then `run.queued`.
- Invalid transition raises `TransicaoInvalida`; transaction rolls back command,
  state and event together.
- Getters use read connections and raise `KeyError(run_id)` when a requested run
  does not exist.

- [ ] **Step 5: Run service tests**

```bash
uv run pytest tests/services/test_control_plane.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Run all new tests together**

```bash
uv run pytest tests/domain/test_operacao.py tests/repositories tests/services/test_maquina_estados.py tests/services/test_control_plane.py -q
```

Expected: all new tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/forge/services/control_plane.py tests/services/test_control_plane.py
git diff --cached --check
git commit -m "feat(studio): add transactional control plane"
```

---

### Task 7: Configuration and application bootstrap

**Files:**
- Modify: `src/forge/infrastructure/config.py:24-87`
- Create: `src/forge/services/studio.py`
- Create: `tests/services/test_studio.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing configuration tests**

Append to `tests/test_config.py`:

```python
def test_studio_database_default_is_local_data_dir():
    s = Settings(_env_file=None)
    assert s.studio_db_path == Path("data/forge.db")


def test_studio_database_can_be_overridden(monkeypatch, tmp_path):
    path = tmp_path / "studio.db"
    monkeypatch.setenv("FORGE_STUDIO_DB_PATH", str(path))
    assert Settings(_env_file=None).studio_db_path == path
```

Ensure `Path` is imported from `pathlib` in the test.

- [ ] **Step 2: Write failing bootstrap test**

```python
# tests/services/test_studio.py
from forge.infrastructure.config import Settings
from forge.services.studio import build_control_plane


def test_build_control_plane_initializes_database(tmp_path):
    settings = Settings(_env_file=None, studio_db_path=tmp_path / "forge.db")
    service = build_control_plane(settings)
    _, run = service.enqueue_video(
        tema="tema", tese=None, priority=50, config_snapshot={},
        workflow_version=1, git_commit="test",
    )
    assert service.get_run(run.id).run.id == run.id
```

- [ ] **Step 3: Verify RED**

```bash
uv run pytest tests/test_config.py tests/services/test_studio.py -q
```

Expected: failures for missing `studio_db_path` and `build_control_plane`.

- [ ] **Step 4: Add setting and bootstrap**

Add to `Settings`:

```python
studio_db_path: Path = Path("data/forge.db")
```

Create `src/forge/services/studio.py`:

```python
from forge.infrastructure.config import Settings
from forge.repositories.connection import Database
from forge.repositories.schema import init_db
from forge.services.control_plane import ControlPlaneService


def build_control_plane(settings: Settings) -> ControlPlaneService:
    db = Database(settings.studio_db_path)
    init_db(db)
    return ControlPlaneService(db)
```

- [ ] **Step 5: Run config/bootstrap tests**

```bash
uv run pytest tests/test_config.py tests/services/test_studio.py -q
```

Expected: all pass.

- [ ] **Step 6: Run full non-integration suite**

```bash
uv run pytest -q
```

Expected: all existing and new tests pass; integration tests remain excluded by
`pyproject.toml`.

- [ ] **Step 7: Commit**

```bash
git add src/forge/infrastructure/config.py src/forge/services/studio.py tests/test_config.py tests/services/test_studio.py
git diff --cached --check
git commit -m "feat(studio): bootstrap persistent control plane"
```

---

### Task 8: Milestone acceptance and regression proof

**Files:**
- Create: `tests/services/test_control_plane_acceptance.py`

- [ ] **Step 1: Write the end-to-end acceptance test**

Create one scenario that uses the public `ControlPlaneService` API only:

```python
# tests/services/test_control_plane_acceptance.py
from forge.domain.operacao import RunStatus, StageName
from forge.infrastructure.config import Settings
from forge.repositories.operacao import OperacaoRepository
from forge.services.studio import build_control_plane


def _mark_failed(service, run_id):
    with service.db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        run = repo.get_run(run_id)
        assert run is not None
        repo.save_run(run.model_copy(update={"status": RunStatus.FAILED}))


def test_control_plane_survives_restart_and_preserves_queue_commands_and_history(tmp_path):
    settings = Settings(_env_file=None, studio_db_path=tmp_path / "forge.db")
    first = build_control_plane(settings)

    _, a = first.enqueue_video(
        tema="A", tese=None, priority=10, config_snapshot={"preset": "local"},
        workflow_version=1, git_commit="abc",
    )
    _, b = first.enqueue_video(
        tema="B", tese=None, priority=90, config_snapshot={"preset": "local"},
        workflow_version=1, git_commit="abc",
    )

    restarted = build_control_plane(settings)
    assert [r.id for r in restarted.list_queue()] == [b.id, a.id]

    claimed = restarted.claim_next("worker-1", lease_seconds=15)
    assert claimed is not None
    assert claimed.id == b.id
    assert claimed.status is RunStatus.PREPARING

    _mark_failed(restarted, b.id)
    retried = restarted.request_retry_stage(
        b.id, StageName.ROTEIRO, idempotency_key="retry-b-script-1"
    )
    same = restarted.request_retry_stage(
        b.id, StageName.ROTEIRO, idempotency_key="retry-b-script-1"
    )
    assert retried.id == same.id
    assert restarted.get_run(b.id).run.status is RunStatus.QUEUED
    assert restarted.get_run(b.id).stages[2].attempt == 2

    kinds = [e.kind for e in restarted.events_after(0, run_id=b.id)]
    assert kinds == ["run.queued", "run.claimed", "stages.invalidated", "run.queued"]
```

The local `_mark_failed` helper emulates the future worker-only failure
transition through `OperacaoRepository`; it is not added to production. Queue
claim and every owner command use the public service API.

- [ ] **Step 2: Run acceptance test and verify it passes**

```bash
uv run pytest tests/services/test_control_plane_acceptance.py -q
```

Expected: `1 passed`.

- [ ] **Step 3: Run formatting-independent checks**

```bash
python -m compileall -q src/forge
uv run pytest -q
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 4: Verify milestone boundaries**

```bash
git diff --name-only HEAD~8..HEAD
```

Expected: only files listed under `Working-tree safety`; no `web/`, `api/`,
worker daemon, executor or POC runtime dependency.

- [ ] **Step 5: Verify POC is not referenced by runtime code**

Use repository search for the literal path in Python source:

```python
search_files(
    pattern=r"_pipeline-poc|C:\\dev\\_pipeline-poc",
    target="content",
    path="src/forge",
    file_glob="*.py",
)
```

Expected: zero matches.

- [ ] **Step 6: Commit acceptance proof**

```bash
git add tests/services/test_control_plane_acceptance.py
git diff --cached --check
git commit -m "test(studio): prove control plane restart and retry semantics"
```

---

## Final verification checklist

- [ ] `uv run pytest -q` passes.
- [ ] `python -m compileall -q src/forge` passes.
- [ ] Three queued runs preserve priority order after process restart.
- [ ] Two concurrent claims cannot return the same run.
- [ ] Duplicate idempotency key produces one command and one side effect.
- [ ] Invalid transition rolls back command, state and event.
- [ ] Retry creates new stage attempts and preserves old rows.
- [ ] Retry marks dependent artifacts non-current without deleting them.
- [ ] Event IDs are monotonic and cursor pagination is gap-free.
- [ ] SQLite runs in WAL with foreign keys and 5-second busy timeout.
- [ ] Runtime code has no `_pipeline-poc` dependency.
- [ ] Existing dirty files remain unstaged and unmodified by this plan.

## Handoff after completion

Marco 1 entrega somente o control plane testável. Não começar Marco 2
automaticamente. Após revisão, criar uma nova spec/plano para o worker: lease,
heartbeat, comandos pendentes, subprocessos, pausa cooperativa e recuperação.
