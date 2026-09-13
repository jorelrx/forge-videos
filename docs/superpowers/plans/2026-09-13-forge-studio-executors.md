# Forge Studio Executors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar os oito executores reais do Forge Studio, com isolamento por subprocesso, checkpoints por item, catálogo de artefatos, gates objetivos e retomada sem repetir saídas válidas.

**Architecture:** O worker continua sendo o único escritor do estado operacional. Cada etapa roda em um subprocesso Python do Forge, grava somente dentro de `output/runs/<run-id>/` e emite JSONL tipado; o processo pai valida esses eventos e projeta itens, artefatos e progresso no SQLite. Os executores reutilizam o grafo, `PlanoMidia`, manifesto, runner e broker existentes, enquanto comportamentos comprovados no `_pipeline-poc` entram como código novo acompanhado por testes de caracterização.

**Tech Stack:** Python 3.12, LangGraph, Pydantic 2, sqlite3/WAL, httpx, filelock, NumPy, SoundFile, Pillow, FFmpeg/ffprobe, LM Studio OpenAI-compatible API, `audio-generate`, ComfyUI, pytest, `uv`.

**Design spec:** `docs/superpowers/specs/2026-09-11-forge-video-studio-design.md`

## Global Constraints

- Ordem interna fixa: `preparacao`, `pesquisa`, `roteiro`, `plano_midia`, `audio`, `imagens`, `montagem`, `validacao`.
- Áudio executa antes de imagens; montagem nunca inicia com áudio ou imagens obrigatórios incompletos.
- Uma única run executa por vez; um único consumidor de GPU fica residente por vez.
- Cada etapa pesada roda em subprocesso separado; stdout aceita somente eventos JSONL e stderr permanece diagnóstico limitado.
- SQLite é a fonte de verdade operacional; `midia.json` e `manifesto.json` permanecem snapshots auditáveis, não um segundo estado concorrente.
- Todo artefato persistido usa caminho relativo a `output/runs/<run-id>/`; nenhum path vindo do cliente ou do POC é aceito.
- Nenhum import, subprocesso, configuração ou teste de produção aponta para `C:\dev\_pipeline-poc`.
- Pesquisa usa somente `research`/acervo em `127.0.0.1:8000`; não existe fallback web.
- LM Studio usa contexto `16384`; `reasoning_content` continua separado de `content`; `qwen/qwen3.8-27b` não entra no preset.
- TTS usa seed `42`, sampler padrão do modelo e nenhuma tag de emoção na V1.
- Imagens usam `1024x576`, `14` steps, CFG `3.2`, `VAEDecodeTiled` e somente LoRAs SDXL validadas.
- Vídeo final usa H.264 + AAC, `1920x1080`; `ffprobe` aprova a saída antes de `completed`.
- Pausa continua cooperativa: termina o item atômico atual, persiste checkpoint e só então para.
- Falhas parciais nunca viram sucesso; `36/41` blocos de áudio é etapa `failed`.
- Retomada preserva item `succeeded` somente quando arquivo, tamanho e SHA-256 continuam válidos.
- Recuperação nunca apaga arquivos; órfãos conhecidos são catalogados com `is_current=false` e nunca consumidos automaticamente.
- Testes padrão não acessam rede, GPU nem serviços locais; testes reais usam marcador `integration`.

---

## Scope Guard

Este plano cobre somente o **Marco 3 — Executores**. Não criar FastAPI, SSE,
frontend Next.js, launcher PowerShell, importador de runs antigas ou publicação.
Health checks usados internamente pelos executores podem existir, mas a rota
`GET /api/services` pertence ao Marco 4.

O Marco 3 termina com uma run completa simulada por executores falsos e testes
unitários de cada integração. O vídeo real com todos os serviços pertence ao
Marco 5; aqui entram apenas testes `integration` opt-in para cada adaptador.

## File Map

| File | Responsibility |
|---|---|
| `src/forge/domain/execucao.py` | Contratos tipados de plano, gate, falha, evento filho e snapshot do contexto |
| `src/forge/domain/roteiro.py` | Arquitetura narrativa de nove seções migrada do POC |
| `src/forge/repositories/operacao.py` | CRUD transacional de `work_items`, vídeos e catálogo de artefatos |
| `src/forge/services/catalogo.py` | SHA-256, MIME, path seguro e projeção dos eventos do subprocesso |
| `src/forge/services/reconciliacao.py` | Conferência de artefatos após interrupção e catálogo de órfãos |
| `src/forge/services/qualidade_roteiro.py` | Métricas e defeitos objetivos migrados do POC |
| `src/forge/services/worker.py` | Contexto rico, preparação da etapa, projeção JSONL e aplicação do gate |
| `src/forge/services/subprocesso.py` | Exige exatamente um `stage.result` válido por subprocesso |
| `src/forge/services/studio.py` | Montagem do registro real de executores |
| `src/forge/executors/base.py` | Protocolo interno `prepare/execute/validate` e utilidades comuns |
| `src/forge/executors/process.py` | Adaptador pai que lança `python -m forge.executors.entrypoint` |
| `src/forge/executors/entrypoint.py` | Dispatcher filho por allowlist e emissor JSONL UTF-8 |
| `src/forge/executors/preparacao.py` | Diretório da run e snapshot inicial |
| `src/forge/executors/pesquisa.py` | Pesquisa inicial no acervo e gate de procedência |
| `src/forge/executors/roteiro.py` | LangGraph a partir de pesquisa existente e gate narrativo |
| `src/forge/executors/plano_midia.py` | Plano determinístico de blocos/beats e cobertura literal |
| `src/forge/executors/audio_generate.py` | argv seguro, lotes, WAV, classificação de erro e voz/F0 |
| `src/forge/executors/audio.py` | Checkpoint por bloco e gate de 100% do áudio |
| `src/forge/executors/estilo_visual.py` | Preset Cosmos Interior e validação safetensors SDXL |
| `src/forge/executors/comfy.py` | Cliente ComfyUI, auto-start, workflow, cache e download |
| `src/forge/executors/imagens.py` | Checkpoint por beat e gate de 100% das imagens |
| `src/forge/executors/ffmpeg.py` | Execução segura, probe, concat, clipes, áudio, SRT e silêncio |
| `src/forge/executors/montagem.py` | Composição somente com artefatos atuais catalogados |
| `src/forge/executors/validacao.py` | Gate final cruzado e amostragem de frames |
| `src/forge/infrastructure/config.py` | Paths, limites e preset local dos executores |
| `src/forge/gpu/broker.py` | Estado com PID, lock órfão e inspeção conservadora |
| `src/forge/gpu/liberadores.py` | Descarga global, shutdown do ComfyUI e diagnóstico de órfãos |

---

### Task 1: Freeze the executor contracts and run workspace

**Files:**
- Create: `src/forge/domain/execucao.py`
- Create: `src/forge/executors/__init__.py`
- Create: `src/forge/executors/base.py`
- Modify: `src/forge/domain/operacao.py`
- Modify: `src/forge/services/worker.py`
- Create: `tests/domain/test_execucao.py`
- Modify: `tests/services/test_worker.py`

**Interfaces:**
- Produces: `StudioPreset`, `StagePlan`, `WorkItemPlan`, `ArtifactOutput`, `GateFinding`, `GateResult`, `FailureClass`, `FailureDetail`, `StageExecutionResult`, `StageChildResult`, `RunSnapshot`.
- Produces: child-side `StageImplementation.prepare(context)`, `execute(context, plan, emit)`, `validate(context, plan, result)`.
- Preserves: parent-side `StageExecutor.execute(context, emit) -> StageResult`, so completed Marco 2 remains source-compatible.

- [ ] **Step 1: Write failing contract tests**

```python
# tests/domain/test_execucao.py
from pathlib import Path

import pytest
from pydantic import ValidationError

from forge.domain.execucao import (
    FailureClass, GateResult, RunSnapshot, StagePlan, StudioPreset, WorkItemPlan,
)
from forge.domain.operacao import StageName


def test_stage_plan_requires_stable_unique_item_keys():
    with pytest.raises(ValidationError, match="item_key"):
        StagePlan(
            stage=StageName.AUDIO,
            input_hash="a" * 64,
            items=[
                WorkItemPlan(item_key="b001", input={"texto": "A"}, input_hash="b" * 64),
                WorkItemPlan(item_key="b001", input={"texto": "B"}, input_hash="c" * 64),
            ],
        )


def test_gate_rejected_requires_findings():
    with pytest.raises(ValidationError, match="findings"):
        GateResult(approved=False, code="audio_incomplete")


def test_run_snapshot_rejects_run_dir_outside_output_root(tmp_path):
    with pytest.raises(ValidationError, match="run_dir"):
        RunSnapshot(
            run_id="r1", video_id="v1", tema="Tema", tese=None,
            stage=StageName.PREPARACAO, attempt=1,
            output_root=tmp_path / "runs", run_dir=Path("C:/escape"),
            config_snapshot={}, artifacts=[], work_items=[],
        )


def test_failure_classes_are_stable_strings():
    assert FailureClass.TRANSIENT.value == "transient"
    assert FailureClass.CAPACITY.value == "capacity"
    assert FailureClass.DETERMINISTIC.value == "deterministic"
    assert FailureClass.PROCESS.value == "process"
    assert FailureClass.USER.value == "user"
    assert FailureClass.ITEM.value == "item"


def test_recommended_preset_matches_approved_snapshot_and_rejects_secrets():
    preset = StudioPreset()
    assert preset.model_dump() == {
        "preset": "local-recomendado-v1", "model": "google/gemma-4-e4b",
        "context_length": 16384, "llm_max_tokens": 4000,
        "tts_backend": "vulkan", "tts_seed": 42,
        "tts_sampler": "model-defaults", "visual_style": "cosmos-interior",
        "image_width": 1024, "image_height": 576,
        "image_steps": 14, "image_cfg": 3.2,
    }
    with pytest.raises(ValidationError, match="api_key"):
        StudioPreset(api_key="secret")
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run --no-cache pytest tests/domain/test_execucao.py tests/services/test_worker.py -q`

Expected: collection fails with `ModuleNotFoundError: forge.domain.execucao`.

- [ ] **Step 3: Implement exact shared models**

```python
# src/forge/domain/execucao.py
from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from forge.domain.operacao import Artifact, JSON_OBJECT, StageName, WorkItem

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class FailureClass(StrEnum):
    TRANSIENT = "transient"
    CAPACITY = "capacity"
    DETERMINISTIC = "deterministic"
    PROCESS = "process"
    USER = "user"
    ITEM = "item"


class StudioPreset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset: Literal["local-recomendado-v1"] = "local-recomendado-v1"
    model: str = "google/gemma-4-e4b"
    context_length: int = 16384
    llm_max_tokens: int = 4000
    tts_backend: Literal["vulkan", "cpu"] = "vulkan"
    tts_seed: int = 42
    tts_sampler: Literal["model-defaults"] = "model-defaults"
    visual_style: Literal["cosmos-interior"] = "cosmos-interior"
    image_width: int = 1024
    image_height: int = 576
    image_steps: int = 14
    image_cfg: float = 3.2


class FailureDetail(BaseModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    failure_class: FailureClass
    retriable: bool
    recommended_action: str = Field(min_length=1)
    adapter: str
    command: list[str] = Field(default_factory=list)
    attempt: int = Field(ge=1)
    item_key: str | None = None
    stack_trace: str = ""
    services: JSON_OBJECT = Field(default_factory=dict)
    gpu: JSON_OBJECT = Field(default_factory=dict)


class WorkItemPlan(BaseModel):
    item_key: str = Field(min_length=1, max_length=200)
    input: JSON_OBJECT
    input_hash: Sha256


class StagePlan(BaseModel):
    stage: StageName
    input_hash: Sha256
    items: list[WorkItemPlan] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_item_keys(self):
        keys = [item.item_key for item in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError("item_key must be unique within a stage plan")
        return self


class ArtifactOutput(BaseModel):
    item_key: str | None = None
    kind: str = Field(min_length=1)
    relative_path: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    metadata: JSON_OBJECT = Field(default_factory=dict)


class GateFinding(BaseModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    item_key: str | None = None
    details: JSON_OBJECT = Field(default_factory=dict)


class GateResult(BaseModel):
    approved: bool
    code: str = Field(min_length=1)
    findings: list[GateFinding] = Field(default_factory=list)
    metrics: JSON_OBJECT = Field(default_factory=dict)

    @model_validator(mode="after")
    def rejected_has_evidence(self):
        if not self.approved and not self.findings:
            raise ValueError("rejected gate requires findings")
        return self


class StageExecutionResult(BaseModel):
    current_items: int = Field(ge=0)
    total_items: int = Field(ge=0)
    artifacts: list[ArtifactOutput] = Field(default_factory=list)
    failure: FailureDetail | None = None

    @property
    def failure_class(self) -> FailureClass | None:
        return self.failure.failure_class if self.failure is not None else None


class StageChildResult(StageExecutionResult):
    gate: GateResult


class RunSnapshot(BaseModel):
    run_id: str
    video_id: str
    tema: str
    tese: str | None
    stage: StageName
    attempt: int = Field(ge=1)
    output_root: Path
    run_dir: Path
    config_snapshot: JSON_OBJECT
    artifacts: list[Artifact]
    work_items: list[WorkItem]

    @model_validator(mode="after")
    def run_dir_is_canonical(self):
        expected = (self.output_root / self.run_id).resolve()
        if self.run_dir.resolve() != expected:
            raise ValueError("run_dir must equal output_root/run_id")
        return self


ChildEventKind = Literal[
    "item.planned", "item.started", "item.succeeded", "item.failed",
    "artifact.created", "stage.progress", "stage.result",
]
```

Add `outputs: JSON_OBJECT = Field(default_factory=dict)` to existing
`StageResult`. Add `video`, `run_dir`, `artifacts` and `work_items` to
`StageContext`; the worker obtains these from its repositories before calling
the parent executor.

- [ ] **Step 4: Define the child implementation protocol without changing the worker contract**

```python
# src/forge/executors/base.py
from abc import ABC, abstractmethod

from forge.domain.execucao import (
    GateResult, RunSnapshot, StageChildResult, StageExecutionResult, StagePlan,
)
from forge.services.worker import EventSink


class StageImplementation(ABC):
    @abstractmethod
    def prepare(self, context: RunSnapshot) -> StagePlan:
        raise NotImplementedError

    @abstractmethod
    def execute(
        self, context: RunSnapshot, plan: StagePlan, emit: EventSink
    ) -> StageExecutionResult:
        raise NotImplementedError

    @abstractmethod
    def validate(
        self, context: RunSnapshot, plan: StagePlan, result: StageExecutionResult
    ) -> GateResult:
        raise NotImplementedError

    def run(self, context: RunSnapshot, emit: EventSink) -> StageChildResult:
        plan = self.prepare(context)
        for item in plan.items:
            emit(
                kind="item.planned", level="info", message="Item planejado",
                payload=item.model_dump(mode="json"),
            )
        execution = self.execute(context, plan, emit)
        gate = self.validate(context, plan, execution)
        return StageChildResult(**execution.model_dump(), gate=gate)
```

Keep `services.worker.StageExecutor.execute(context, emit) -> StageResult` as
the process-parent boundary. This prevents a broad rewrite of Marco 2 while the
child gets the complete three-method contract required by the spec.

- [ ] **Step 5: Run tests and commit**

Run: `uv run --no-cache pytest tests/domain/test_execucao.py tests/services/test_worker.py -q`

Expected: PASS.

```bash
git add src/forge/domain/execucao.py src/forge/domain/operacao.py src/forge/executors/__init__.py src/forge/executors/base.py src/forge/services/worker.py tests/domain/test_execucao.py tests/services/test_worker.py
git diff --cached --check
git commit -m "feat(studio): define executor contracts"
```

---

### Task 2: Make work items and artifacts operational

**Files:**
- Modify: `src/forge/repositories/operacao.py`
- Create: `src/forge/services/catalogo.py`
- Create: `src/forge/services/redacao.py`
- Modify: `src/forge/services/worker.py`
- Modify: `tests/repositories/test_operacao.py`
- Create: `tests/services/test_catalogo.py`
- Create: `tests/services/test_redacao.py`
- Modify: `tests/services/test_worker.py`

**Interfaces:**
- Produces: `upsert_work_items(stage_run_id, plans)`, `list_work_items(stage_run_id)`, `start_work_item`, `finish_work_item`.
- Produces: `CatalogoArtefatos.register_file() -> Artifact` and `ChildEventProjector.project()`.
- Produces: `CatalogoArtefatos.find_reusable_output()` for same-key, same-hash outputs from an earlier stage attempt.
- Produces: recursive `Redactor.clean()` used before every event append.
- Consumes: Task 1 models and current SQLite schema v1; no migration is needed.

- [ ] **Step 1: Write failing repository and projector tests**

```python
def test_upsert_preserves_succeeded_item_when_input_hash_is_equal(db):
    with db.transaction(immediate=True) as conn:
        repo, run, stage = audio_stage(conn)
        original = repo.upsert_work_items(stage.id, [item_plan("b001", "same")])[0]
        repo.start_work_item(original.id)
        repo.finish_work_item(original.id, succeeded=True, duration_ms=900)
        resumed = repo.upsert_work_items(stage.id, [item_plan("b001", "same")])[0]
    assert resumed.status is ItemStatus.SUCCEEDED
    assert resumed.attempts == 1


def test_changed_input_hash_invalidates_old_output_and_resets_item(db):
    with db.transaction(immediate=True) as conn:
        repo, run, stage = audio_stage(conn)
        old = repo.upsert_work_items(stage.id, [item_plan("b001", "old")])[0]
        repo.start_work_item(old.id)
        repo.finish_work_item(old.id, succeeded=True, duration_ms=900)
        fresh = repo.upsert_work_items(stage.id, [item_plan("b001", "new")])[0]
    assert fresh.status is ItemStatus.PENDING
    assert fresh.attempts == 1


def test_prior_attempt_output_is_reusable_only_with_same_input_hash(tmp_path, db):
    run_dir, run, old_stage, new_stage = retried_audio_stage(tmp_path, db)
    old_item, old_artifact = succeeded_audio_item(run_dir, run, old_stage, input_hash="a" * 64)
    catalog = CatalogoArtefatos(db, run_dir)
    assert catalog.find_reusable_output(
        run_id=run.id, stage=StageName.AUDIO, item_key=old_item.item_key,
        input_hash="a" * 64,
    ) == old_artifact
    assert catalog.find_reusable_output(
        run_id=run.id, stage=StageName.AUDIO, item_key=old_item.item_key,
        input_hash="b" * 64,
    ) is None


def test_catalog_registers_only_file_inside_run_and_computes_sha(tmp_path, db):
    run_dir, run, stage = prepared_run(tmp_path, db)
    target = run_dir / "video" / "audio" / "b001.wav"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"RIFFpayload")
    artifact = CatalogoArtefatos(db, run_dir).register_file(
        run=run, stage_run=stage, item=None, kind="audio.wav",
        path=target, mime_type="audio/wav", metadata={"sample_rate": 24000},
    )
    assert artifact.relative_path == "video/audio/b001.wav"
    assert artifact.sha256 == hashlib.sha256(b"RIFFpayload").hexdigest()


def test_projector_rejects_unknown_item_key_and_path_escape(tmp_path, db):
    projector = child_projector(tmp_path, db)
    with pytest.raises(ChildProtocolError, match="unknown item_key"):
        projector.project("item.succeeded", {"item_key": "ghost", "duration_ms": 1})
    with pytest.raises(ChildProtocolError, match="outside run_dir"):
        projector.project("artifact.created", {
            "item_key": None, "kind": "x", "relative_path": "../escape",
            "mime_type": "application/json", "metadata": {},
        })


def test_event_redactor_masks_values_and_credential_keys():
    redactor = Redactor(secrets=["sk-live-123"])
    assert redactor.clean({
        "message": "falhou com sk-live-123", "api_key": "another",
        "nested": ["safe", "token sk-live-123"],
    }) == {
        "message": "falhou com [REDACTED]", "api_key": "[REDACTED]",
        "nested": ["safe", "token [REDACTED]"],
    }
```

- [ ] **Step 2: Verify RED**

Run: `uv run --no-cache pytest tests/repositories/test_operacao.py tests/services/test_catalogo.py tests/services/test_redacao.py tests/services/test_worker.py -q`

Expected: FAIL because work-item mutations, `CatalogoArtefatos` and `Redactor` do not exist.

- [ ] **Step 3: Implement transactional work-item mutations**

Add these public methods to `OperacaoRepository`; use the shown SQL and the
new `_work_item_from_row` mapper so callers always receive validated models:

```python
def get_video(self, video_id: str) -> Video | None:
    row = self.conn.execute(
        "SELECT * FROM videos WHERE id = ?", (video_id,)
    ).fetchone()
    return _video_from_row(row) if row is not None else None


def upsert_work_items(
    self, stage_run_id: str, plans: list[WorkItemPlan]
) -> list[WorkItem]:
    if self.conn.execute(
        "SELECT 1 FROM stage_runs WHERE id = ?", (stage_run_id,)
    ).fetchone() is None:
        raise KeyError(stage_run_id)
    for plan in plans:
        row = self.conn.execute(
            "SELECT * FROM work_items WHERE stage_run_id = ? AND item_key = ?",
            (stage_run_id, plan.item_key),
        ).fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO work_items "
                "(id, stage_run_id, item_key, status, input_json, input_hash) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()), stage_run_id, plan.item_key,
                    ItemStatus.PENDING.value, _json(plan.input), plan.input_hash,
                ),
            )
        elif row["input_hash"] != plan.input_hash:
            self.conn.execute(
                "UPDATE artifacts SET is_current = 0 WHERE work_item_id = ?",
                (row["id"],),
            )
            self.conn.execute(
                "UPDATE work_items SET status = ?, input_json = ?, input_hash = ?, "
                "duration_ms = NULL, failure_code = NULL, failure_message = NULL "
                "WHERE id = ?",
                (ItemStatus.PENDING.value, _json(plan.input), plan.input_hash, row["id"]),
            )
    return self.list_work_items(stage_run_id)


def list_work_items(self, stage_run_id: str) -> list[WorkItem]:
    rows = self.conn.execute(
        "SELECT * FROM work_items WHERE stage_run_id = ? ORDER BY item_key",
        (stage_run_id,),
    ).fetchall()
    return [_work_item_from_row(row) for row in rows]


def start_work_item(self, work_item_id: str) -> WorkItem:
    row = self.conn.execute(
        "UPDATE work_items SET status = ?, attempts = attempts + 1 "
        "WHERE id = ? AND status IN (?, ?) RETURNING *",
        (
            ItemStatus.RUNNING.value, work_item_id,
            ItemStatus.PENDING.value, ItemStatus.FAILED.value,
        ),
    ).fetchone()
    if row is None:
        raise KeyError(work_item_id)
    return _work_item_from_row(row)


def finish_work_item(
    self, work_item_id: str, *, succeeded: bool, duration_ms: int | None,
    failure_code: str | None = None, failure_message: str | None = None,
) -> WorkItem:
    if succeeded and (failure_code is not None or failure_message is not None):
        raise ValueError("succeeded item cannot contain failure")
    if not succeeded and (not failure_code or not failure_message):
        raise ValueError("failed item requires code and message")
    row = self.conn.execute(
        "UPDATE work_items SET status = ?, duration_ms = ?, failure_code = ?, "
        "failure_message = ? WHERE id = ? AND status = ? RETURNING *",
        (
            ItemStatus.SUCCEEDED.value if succeeded else ItemStatus.FAILED.value,
            duration_ms, failure_code, failure_message, work_item_id,
            ItemStatus.RUNNING.value,
        ),
    ).fetchone()
    if row is None:
        raise KeyError(work_item_id)
    return _work_item_from_row(row)
```

`upsert_work_items` uses `(stage_run_id, item_key)` as identity. Equal hashes
preserve status; changed hashes invalidate current artifacts linked to the old
item and reset status to `pending` while preserving attempt count. `start_work_item`
increments `attempts` atomically. `finish_work_item` requires the item to be
`running` and persists either both failure fields or neither.

- [ ] **Step 4: Implement catalog and worker event projection**

```python
# src/forge/services/catalogo.py
ALLOWED_MIME = {
    "text/markdown", "application/json", "image/png", "image/jpeg",
    "image/webp", "audio/wav", "video/mp4", "application/x-subrip",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class CatalogoArtefatos:
    def register_file(self, *, run, stage_run, item, kind, path, mime_type, metadata):
        resolved = path.resolve(strict=True)
        resolved.relative_to(self.run_dir.resolve(strict=True))
        if mime_type not in ALLOWED_MIME:
            raise ValueError(f"MIME não permitido: {mime_type}")
        return self._persist(
            run=run, stage_run=stage_run, item=item, kind=kind,
            relative_path=resolved.relative_to(self.run_dir).as_posix(),
            sha256=sha256_file(resolved), size_bytes=resolved.stat().st_size,
            mime_type=mime_type, metadata=metadata,
        )
```

`ChildEventProjector.project()` handles only the seven `ChildEventKind` values
from Task 1. It validates payloads with Pydantic, looks up `item_key` in the
current stage attempt and performs the DB mutation before appending the public
event. `item.planned` calls `upsert_work_items` before a matching
`item.started` can arrive. Any other child `kind` remains a diagnostic event
and cannot mutate items or artifacts. Update `_event_sink()` in `StudioWorker`
to use this projector.

`find_reusable_output()` searches earlier attempts of the same run/stage and
item key, requires identical `input_hash`, a succeeded work item, regular file,
stored size and SHA-256 match. Reuse creates a new work-item/artifact history
row for the current attempt; it never flips the old artifact back to current.
`Redactor` recursively replaces configured secret values and values under keys
matching `api_key`, `authorization`, `password`, `secret` or `token`. Apply it
to message and payload before both diagnostic and projected child events reach
`EventosRepository`.

- [ ] **Step 5: Verify and commit**

Run: `uv run --no-cache pytest tests/repositories/test_operacao.py tests/services/test_catalogo.py tests/services/test_redacao.py tests/services/test_worker.py -q`

Expected: PASS.

```bash
git add src/forge/repositories/operacao.py src/forge/services/catalogo.py src/forge/services/redacao.py src/forge/services/worker.py tests/repositories/test_operacao.py tests/services/test_catalogo.py tests/services/test_redacao.py tests/services/test_worker.py
git diff --cached --check
git commit -m "feat(studio): persist executor items and artifacts"
```

---

### Task 3: Run every stage through a typed child process

**Files:**
- Create: `src/forge/executors/process.py`
- Create: `src/forge/executors/entrypoint.py`
- Create: `src/forge/executors/retry.py`
- Modify: `src/forge/services/subprocesso.py`
- Modify: `src/forge/services/worker.py`
- Create: `tests/executors/test_process.py`
- Create: `tests/executors/test_entrypoint.py`
- Create: `tests/executors/test_retry.py`
- Modify: `tests/services/test_subprocesso.py`

**Interfaces:**
- Produces: `StageProcessExecutor(stage, output_root, timeout_seconds)` implementing parent `StageExecutor`.
- Produces CLI: `python -m forge.executors.entrypoint --context <absolute-json> --stage <allowlisted-name>`.
- Produces: `RetryPolicy.run(operation, classify)`; only transient failures retry with bounded exponential backoff.
- Consumes: `stage.result.payload` validated as `StageChildResult` and returned as operational `StageResult`.

- [ ] **Step 1: Write failing protocol tests**

```python
def test_subprocess_requires_exactly_one_stage_result(tmp_path):
    executor = SubprocessExecutor(child(event("stage.progress", {"current": 1, "total": 1})))
    result = executor.execute(context(), collect())
    assert result.failure_code == "missing_stage_result"


def test_subprocess_rejects_duplicate_stage_result():
    line = stage_result_line(approved=True)
    result = SubprocessExecutor(child(line, line)).execute(context(), collect())
    assert result.failure_code == "duplicate_stage_result"


def test_process_executor_uses_argv_and_absolute_context_file(tmp_path, monkeypatch):
    seen = capture_subprocess(monkeypatch)
    StageProcessExecutor(
        StageName.AUDIO, output_root=tmp_path / "runs", timeout_seconds=90,
    ).execute(stage_context(tmp_path), collect())
    assert seen.argv[:3] == [sys.executable, "-m", "forge.executors.entrypoint"]
    assert Path(seen.argv[seen.argv.index("--context") + 1]).is_absolute()
    assert seen.shell is False


def test_entrypoint_rejects_non_allowlisted_stage(tmp_path):
    completed = run_entrypoint(tmp_path, stage="shell:whoami")
    assert completed.returncode == 2
    assert "invalid choice" in completed.stderr


def test_retry_policy_retries_only_transient_failures():
    calls = Counter(failures=[transient("service_starting"), success("ok")])
    result = RetryPolicy(max_attempts=3, base_delay=1, max_delay=4, sleep=no_sleep).run(
        calls, classify=lambda error: error.detail
    )
    assert result == "ok"
    assert calls.count == 2


def test_retry_policy_does_not_repeat_capacity_failure():
    calls = Counter(failures=[capacity("tts_vulkan_oom")])
    with pytest.raises(ExecutionFailure, match="tts_vulkan_oom"):
        RetryPolicy(max_attempts=3, sleep=no_sleep).run(
            calls, classify=lambda error: error.detail
        )
    assert calls.count == 1
```

- [ ] **Step 2: Verify RED**

Run: `uv run --no-cache pytest tests/executors/test_process.py tests/executors/test_entrypoint.py tests/executors/test_retry.py tests/services/test_subprocesso.py -q`

Expected: import failures for new executor modules and missing-result assertion failure.

- [ ] **Step 3: Teach `SubprocessExecutor` to return the child result**

Inside `_parse_event`, validate `stage.result.payload` using
`StageChildResult.model_validate`. Store one result under a lock shared with
the stdout reader. After process exit `0`, return:

```python
if duplicate_result:
    return StageResult(
        failure_code="duplicate_stage_result",
        failure_message="Subprocesso emitiu mais de um stage.result",
    )
if child_result is None:
    return StageResult(
        failure_code="missing_stage_result",
        failure_message="Subprocesso não emitiu stage.result",
    )
return StageResult(
    gate_status=child_result.gate.code,
    current_items=child_result.current_items,
    total_items=child_result.total_items,
    failure_code=(
        child_result.failure.code if child_result.failure is not None
        else None if child_result.gate.approved else child_result.gate.code
    ),
    failure_message=(
        child_result.failure.message if child_result.failure is not None
        else None if child_result.gate.approved else child_result.gate.findings[0].message
    ),
    outputs=child_result.model_dump(mode="json"),
)
```

Malformed or duplicate terminal events are process-protocol failures, not gate
failures. Keep all existing timeout, cancellation and descendant-containment
behavior from Marco 2. When `child_result.failure` exists, copy its stable code
and operator message into `StageResult`; retain full sanitized evidence under
`outputs["failure"]` so `stage.failed` persists adapter, argv, attempt, item,
stack trace, service/GPU snapshot, `retriable` and recommended action.

- [ ] **Step 4: Implement safe parent adapter and child dispatcher**

```python
# src/forge/executors/entrypoint.py
IMPLEMENTATIONS = {
    StageName.PREPARACAO: "forge.executors.preparacao:PreparationExecutor",
    StageName.PESQUISA: "forge.executors.pesquisa:ResearchExecutor",
    StageName.ROTEIRO: "forge.executors.roteiro:ScriptExecutor",
    StageName.PLANO_MIDIA: "forge.executors.plano_midia:MediaPlanExecutor",
    StageName.AUDIO: "forge.executors.audio:AudioExecutor",
    StageName.IMAGENS: "forge.executors.imagens:ImageExecutor",
    StageName.MONTAGEM: "forge.executors.montagem:ComposeExecutor",
    StageName.VALIDACAO: "forge.executors.validacao:ValidationExecutor",
}


def emit(*, kind: str, level: str, message: str, payload: dict) -> None:
    line = {"kind": kind, "level": level, "message": message, "payload": payload}
    print(json.dumps(line, ensure_ascii=False), flush=True)
```

`StageProcessExecutor` writes `RunSnapshot.model_dump_json()` atomically to
`<run>/video/.stage-<stage>-r<attempt>.json`, launches the fixed module argv,
and deletes only that context file after a successful parse. No environment
secret is serialized; effective secrets come from process environment through
`Settings`.

Implement `RetryPolicy` with delays `base_delay * 2 ** (attempt - 1)`, capped
by `max_delay`. Retry only `FailureClass.TRANSIENT`; capacity, deterministic,
process, user and item failures return immediately. Every retry emits one
`operation.retrying` event with attempt, maximum, stable code and next delay.
Executors may override attempt counts from immutable configuration but cannot
retry forever.

- [ ] **Step 5: Verify and commit**

Run: `uv run --no-cache pytest tests/executors/test_process.py tests/executors/test_entrypoint.py tests/executors/test_retry.py tests/services/test_subprocesso.py tests/services/test_worker.py -q`

Expected: PASS.

```bash
git add src/forge/executors/process.py src/forge/executors/entrypoint.py src/forge/executors/retry.py src/forge/services/subprocesso.py src/forge/services/worker.py tests/executors/test_process.py tests/executors/test_entrypoint.py tests/executors/test_retry.py tests/services/test_subprocesso.py
git diff --cached --check
git commit -m "feat(studio): isolate stages in typed subprocesses"
```

---

### Task 4: Preparation and research executors

**Files:**
- Create: `src/forge/executors/preparacao.py`
- Create: `src/forge/executors/pesquisa.py`
- Modify: `src/forge/infrastructure/config.py`
- Modify: `src/forge/agents/research.py`
- Create: `tests/executors/test_preparacao.py`
- Create: `tests/executors/test_pesquisa.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Produces: `video/input.json`, `video/research.json`, `01-research.md`, `01-research.raw.md` and artifact events.
- Produces config: `studio_runs_dir=Path("output/runs")`, `research_min_sources=3`.
- Consumes: existing `Acervo`, `agents.research.pesquisar`, model factory and atomic persistence.

- [ ] **Step 1: Write failing executor tests with fake model/acervo**

```python
def test_preparation_creates_only_canonical_run_tree(snapshot, emit):
    result = PreparationExecutor().run(snapshot, emit)
    assert (snapshot.run_dir / "video" / "input.json").is_file()
    assert result.gate.approved
    assert artifact_paths(emit) == ["video/input.json"]


def test_research_requires_minimum_canonical_sources(snapshot, emit):
    executor = ResearchExecutor(
        model=fake_query_and_summary_model(),
        acervo=FakeAcervo([passage(path=None), passage(path="12/ch1/p2")]),
        minimum_sources=2,
    )
    result = executor.run(snapshot, emit)
    assert not result.gate.approved
    assert result.gate.code == "research_gate_failed"
    assert {finding.code for finding in result.gate.findings} == {
        "research_source_missing_path", "research_minimum_not_met",
    }


def test_research_unavailable_has_stable_transient_failure(snapshot, emit):
    executor = ResearchExecutor(model=fake_model(), acervo=OfflineAcervo(), minimum_sources=1)
    result = executor.run(snapshot, emit)
    assert result.failure_class is FailureClass.TRANSIENT
    assert result.gate.findings[0].code == "research_unavailable"
```

- [ ] **Step 2: Verify RED**

Run: `uv run --no-cache pytest tests/executors/test_preparacao.py tests/executors/test_pesquisa.py tests/test_config.py -q`

Expected: import failures for both executors.

- [ ] **Step 3: Implement preparation with atomic input snapshot**

`PreparationExecutor.prepare()` returns a zero-item `StagePlan` hashed from
`run_id`, `video_id`, `tema`, `tese`, workflow version and
`StudioPreset.model_validate(config_snapshot)`. Unknown fields, including any
credential-like field, fail before disk writes. Its
`execute()` creates `run_dir/video` with `mkdir(parents=True, exist_ok=True)`,
writes `video/input.json` through `gravar_modelo`, emits
`artifact.created`, and never writes outside the canonical run directory.
`validate()` rejects a missing or unreadable snapshot with
`preparation_snapshot_invalid`.

- [ ] **Step 4: Implement research and expose raw passages for the gate**

Refactor `agents.research.pesquisar` to return a typed `ResearchBundle` without
changing its public semantic result:

```python
class PassageEvidence(BaseModel):
    path: str
    book_id: int | None = None
    title: str
    authors: list[str] = Field(default_factory=list)
    text: str


class ResearchBundle(BaseModel):
    brief: str
    fontes: list[Fonte]
    raw_markdown: str
    passages: list[PassageEvidence]
    passage_count: int
    canonical_paths: list[str]
    unanswered_queries: list[str] = Field(default_factory=list)
```

`ResearchExecutor` builds the model from `Settings`, acquires broker resource
`llm` once, calls the existing acervo path, writes the same numbered
human-readable artifact plus `video/research.json`, and emits metadata
containing counts but never passage bodies or secrets. Gate approval
requires: acervo call succeeded, all accepted sources have non-empty canonical
`path`, `len(set(canonical_paths)) >= settings.research_min_sources`, and every
reported lacuna was recorded without a fabricated source.

- [ ] **Step 5: Verify and commit**

Run: `uv run --no-cache pytest tests/executors/test_preparacao.py tests/executors/test_pesquisa.py tests/agents/test_research.py tests/test_config.py -q`

Expected: PASS.

```bash
git add src/forge/executors/preparacao.py src/forge/executors/pesquisa.py src/forge/infrastructure/config.py src/forge/agents/research.py tests/executors/test_preparacao.py tests/executors/test_pesquisa.py tests/agents/test_research.py tests/test_config.py
git diff --cached --check
git commit -m "feat(studio): execute preparation and research stages"
```

---

### Task 5: Migrate narrative architecture and enforce the local-model script gate

**Files:**
- Create: `src/forge/domain/roteiro.py`
- Create: `src/forge/services/qualidade_roteiro.py`
- Create: `src/forge/executors/lm_studio.py`
- Modify: `src/forge/domain/models.py`
- Modify: `src/forge/llms/model.py`
- Modify: `src/forge/agents/plan.py`
- Modify: `src/forge/agents/research.py`
- Modify: `src/forge/agents/review.py`
- Modify: `src/forge/agents/write.py`
- Modify: `src/forge/prompts/write.md`
- Modify: `src/forge/prompts/review.md`
- Modify: `src/forge/skills/story.md`
- Modify: `src/forge/skills/retention.md`
- Create: `src/forge/executors/roteiro.py`
- Create: `tests/domain/test_roteiro.py`
- Create: `tests/services/test_qualidade_roteiro.py`
- Create: `tests/executors/test_roteiro.py`
- Create: `tests/executors/test_lm_studio.py`
- Modify: `tests/test_llm_model.py`
- Add fixtures: `tests/fixtures/poc/roteiro_poc_3_graves.json`, `tests/fixtures/poc/roteiro_sintetico_aprovado.json`

**Interfaces:**
- Produces: immutable `ARQUITETURA`, `avaliar_roteiro(roteiro, passages_by_section)`, `conferir_roteiro(roteiro, passages_by_section) -> ScriptGateReport`.
- Produces: `LMStudioManager.ensure_loaded()` and bounded `invoke_structured()` retry after `finish_reason=length`.
- Produces: `ScriptExecutor` running current graph from `plan`, with directed research re-entry still enabled.
- Consumes: research artifacts from Task 4; no import from POC.

- [ ] **Step 1: Copy two small POC outcomes as characterization fixtures and write RED tests**

```python
def test_narrative_order_is_the_approved_nine_functions():
    assert [section.nome for section in ARQUITETURA] == [
        "Gancho", "Estake", "Tensao", "Virada", "Filosofo",
        "Prova", "Espelho", "Aplicacao", "Fecho",
    ]


def test_characterization_preserves_three_poc_gate_failures():
    report = conferir_roteiro(load_fixture("roteiro_poc_3_graves.json"))
    assert not report.approved
    assert report.serious_count == 3
    assert report.codes == {"sem_citacao", "frase_longa", "aberturas_parecidas"}


def test_gate_approves_clean_nine_section_fixture():
    report = conferir_roteiro(load_fixture("roteiro_sintetico_aprovado.json"))
    assert report.approved
    assert report.metrics["sections_ok"] == 9
    assert report.metrics["robot_labels"] == 0


def test_hook_is_deliberately_exempt_from_source_citation():
    report = conferir_secao("Gancho", valid_hook_without_author(), passages())
    assert "sem_citacao" not in {finding.code for finding in report.findings}


def test_lm_studio_loads_recommended_model_with_16k_context(settings, runner):
    LMStudioManager(settings, run=runner).ensure_loaded()
    assert runner.argv == [
        settings.lms_bin, "load", "google/gemma-4-e4b", "-c", "16384",
        "--ttl", "3600", "-y",
    ]


def test_structured_length_retries_once_with_doubled_budget():
    model = BudgetModel([
        raw_result(parsed=None, finish_reason="length", reasoning_content="thinking"),
        raw_result(parsed=Plano(tese="T", esboco="E"), finish_reason="stop"),
    ])
    result = invoke_structured(
        model, Plano, messages(), initial_max_tokens=4000, ceiling_max_tokens=16000,
    )
    assert result == Plano(tese="T", esboco="E")
    assert model.bound_budgets == [4000, 8000]
```

Build `roteiro_poc_3_graves.json` from the section text and minimal source
metadata in POC run
`runs/20260911-1416-o-peso-de-ser-livre/{secoes,fontes,detector}.json`; expected
codes come from that run's persisted detector result. Build the approved
fixture from nine short, distinct sections satisfying every threshold. Fixtures
contain no absolute POC path and no complete run directory.

- [ ] **Step 2: Verify RED**

Run: `uv run --no-cache pytest tests/domain/test_roteiro.py tests/services/test_qualidade_roteiro.py tests/executors/test_lm_studio.py tests/test_llm_model.py -q`

Expected: collection fails for both new modules.

- [ ] **Step 3: Port behavior into typed Forge modules**

Move constants and algorithms from POC `arquitetura.py`, `metricas.py` and
`detector.py`, converting dictionaries and ad-hoc `Defeito` objects to:

```python
class NarrativeSection(BaseModel, frozen=True):
    nome: str
    papel: str
    instrucao: str
    alvo_palavras: tuple[int, int]
    abre_loop: bool = False
    fecha_loop: bool = False
    rehook: bool = False
    pergunta_publico: bool = False


class ScriptGateReport(BaseModel):
    approved: bool
    serious_count: int
    findings: list[GateFinding]
    metrics: JSON_OBJECT

    @property
    def codes(self) -> set[str]:
        return {finding.code for finding in self.findings}
```

Preserve thresholds exactly: grave below `60%` of section minimum, warning
above `160%` of maximum, grave sentence above `40` words, warning above `35`,
opening similarity grave above `0.45`, warning above `0.30`, size deviation
grave above `0.45`, and F0-independent source anchoring through author/title.
Set `SECOES_NOMES` from `ARQUITETURA` to keep resume parsing aligned.

Add Studio-local settings `llm_context_length=16384`, `llm_max_tokens=4000`,
`llm_max_tokens_ceiling=16000`, `lm_studio_ttl_seconds=3600`; change only the
`lm-studio` default model to `google/gemma-4-e4b`. `LMStudioManager` uses fixed
argv and rejects `qwen/qwen3.8-27b` before invoking `lms`. `invoke_structured`
uses `with_structured_output(schema, include_raw=True)`, records
`reasoning_content` separately, and doubles the bound `max_tokens` only when
the raw response ended with `finish_reason=length` and parsing produced no
value. Stop at the ceiling and raise `llm_output_truncated`; other parsing
failures never receive a blind retry. Route plan, research, review and write
structured calls through this helper.

- [ ] **Step 4: Implement ScriptExecutor and make the code gate authoritative**

`ScriptExecutor.prepare()` hashes current research artifacts plus model/preset.
`execute()` acquires broker resource `llm` once, calls
`LMStudioManager.ensure_loaded()` when provider is `lm-studio`, loads
`ResearchBundle`, builds
the existing graph with entry point
`plan`, and preserves its internal `review -> research` and `write -> research`
fact-check loops. It writes numbered graph artifacts, `video/roteiro.json` and
final `roteiro.md` inside the run.
`validate()` ignores a model's optimistic approval when the deterministic
report has a grave defect:

```python
gate = conferir_roteiro(roteiro, passages_by_section)
return GateResult(
    approved=gate.approved,
    code="script_approved" if gate.approved else "script_gate_failed",
    findings=gate.findings,
    metrics=gate.metrics,
)
```

Prompts and skills must name the new nine sections and enforce Gancho citation
exemption, Espelho final question and Fecho loop closure. A script with fewer
or more than nine named sections fails `script_sections_invalid`.

- [ ] **Step 5: Verify and commit**

Run: `uv run --no-cache pytest tests/domain/test_roteiro.py tests/services/test_qualidade_roteiro.py tests/executors/test_lm_studio.py tests/executors/test_roteiro.py tests/test_llm_model.py tests/agents tests/orchestration -q`

Expected: PASS.

```bash
git add src/forge/domain/roteiro.py src/forge/services/qualidade_roteiro.py src/forge/executors/lm_studio.py src/forge/domain/models.py src/forge/llms/model.py src/forge/agents/plan.py src/forge/agents/research.py src/forge/agents/review.py src/forge/agents/write.py src/forge/prompts/write.md src/forge/prompts/review.md src/forge/skills/story.md src/forge/skills/retention.md src/forge/executors/roteiro.py tests/domain/test_roteiro.py tests/services/test_qualidade_roteiro.py tests/executors/test_lm_studio.py tests/executors/test_roteiro.py tests/test_llm_model.py tests/fixtures/poc/roteiro_poc_3_graves.json tests/fixtures/poc/roteiro_sintetico_aprovado.json
git diff --cached --check
git commit -m "feat(studio): enforce narrative quality gate"
```

---

### Task 6: Media-plan executor and single manifest bridge

**Files:**
- Create: `src/forge/executors/plano_midia.py`
- Modify: `src/forge/agents/midia.py`
- Modify: `src/forge/services/manifesto.py`
- Modify: `src/forge/services/runner.py`
- Create: `tests/executors/test_plano_midia.py`
- Modify: `tests/services/test_manifesto.py`
- Modify: `tests/services/test_runner.py`

**Interfaces:**
- Produces: `video/midia.json`, work-item plans for every narration block and visual beat.
- Produces: `Manifesto.from_work_items()` as a human-readable mirror of SQLite state.
- Consumes: approved `roteiro.md`; current `planejar_midia`, `gravar_plano`, `_conferir_cobertura` behavior.

- [ ] **Step 1: Write RED coverage and manifest-authority tests**

```python
def test_media_plan_reproduces_narration_word_for_word(snapshot, model, emit):
    result = MediaPlanExecutor(model=model).run(snapshot, emit)
    plan = carregar_plano(snapshot.run_dir)
    assert " ".join(block.texto for block in plan.blocos) == expected_narration(snapshot)
    assert result.gate.approved


def test_media_plan_rejects_missing_beat_reference(snapshot, model, emit):
    model.return_value = beats_with_unknown_block("ghost")
    result = MediaPlanExecutor(model=model).run(snapshot, emit)
    assert result.gate.code == "media_plan_gate_failed"
    assert result.gate.findings[0].code == "beat_block_missing"


def test_manifest_is_rebuilt_from_database_items_not_used_as_authority(tmp_path):
    items = [db_item("b001", ItemStatus.SUCCEEDED), db_item("i001", ItemStatus.PENDING)]
    manifest = Manifesto.from_work_items(items)
    assert [(item.id, item.estado) for item in manifest.itens] == [
        ("b001", "ok"), ("i001", "pendente")
    ]
```

- [ ] **Step 2: Verify RED**

Run: `uv run --no-cache pytest tests/executors/test_plano_midia.py tests/services/test_manifesto.py tests/services/test_runner.py -q`

Expected: missing executor and mirror constructor.

- [ ] **Step 3: Implement MediaPlanExecutor**

`prepare()` hashes the current script artifact and media settings.
`execute()` acquires broker resource `llm` once, ensures the configured local
model is loaded, loads the approved `Roteiro`, calls `planejar_midia` once
through Task 5's bounded structured-output helper, and writes
`video/midia.json` atomically and emits an artifact. `validate()` performs both
coverage checks already encoded in `agents/midia.py`, confirms unique stable
block/beat IDs, every beat references an existing block and every section has
at least one visual beat.

The downstream audio and image executors independently derive these exact item
specs from the current `midia.json` during their own `prepare()` calls:

```python
audio_items = [
    WorkItemPlan(item_key=block.id, input=block.model_dump(), input_hash=hash_json(block))
    for block in plan.blocos
]
image_items = [
    WorkItemPlan(item_key=beat.id, input=beat.model_dump(), input_hash=hash_json(beat))
    for beat in plan.beats
]
```

- [ ] **Step 4: Make the existing manifesto a projection**

Add `Manifesto.from_work_items(items)` and `Manifesto.merge_outputs(artifacts)`.
The worker rewrites `video/manifesto.json` atomically after every projected
item event. Remove any resume decision based only on `manifesto.json`; runner
receives pending items chosen from SQLite. Preserve current per-item writes and
group-level broker acquisition.

- [ ] **Step 5: Verify and commit**

Run: `uv run --no-cache pytest tests/executors/test_plano_midia.py tests/services/test_manifesto.py tests/services/test_runner.py tests/agents/test_midia.py -q`

Expected: PASS.

```bash
git add src/forge/executors/plano_midia.py src/forge/agents/midia.py src/forge/services/manifesto.py src/forge/services/runner.py tests/executors/test_plano_midia.py tests/services/test_manifesto.py tests/services/test_runner.py
git diff --cached --check
git commit -m "feat(studio): plan media with one checkpoint authority"
```

---

### Task 7: Harden GPU ownership for real executors

**Files:**
- Modify: `src/forge/gpu/broker.py`
- Modify: `src/forge/gpu/liberadores.py`
- Modify: `src/forge/infrastructure/config.py`
- Modify: `tests/gpu/test_broker.py`
- Modify: `tests/gpu/test_liberadores.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Produces broker state `{ "recurso", "pid", "claimed_at" }`.
- Produces `ProcessInspector.is_alive(pid)`, `shutdown_comfy()`, `diagnose_gpu_orphans()`.
- Consumes: shared `.gpu.lock` and `.gpu-residente.json` already used by CLI.

- [ ] **Step 1: Write RED tests for the three measured POC failures**

```python
def test_dead_owner_state_is_orphan_and_all_consumers_are_released(tmp_path):
    state(tmp_path).write_text(json.dumps({"recurso": "imagem", "pid": 4455}))
    inspector = FakeInspector(dead={4455})
    with broker(tmp_path, inspector=inspector).exclusivo("tts"):
        pass
    assert releases == ["imagem", "llm", "tts"]


def test_manual_comfy_is_released_even_without_registered_resident(tmp_path):
    with broker(tmp_path, resident=None, probes={"imagem": True}).exclusivo("tts"):
        pass
    assert "shutdown_comfy" in actions


def test_tts_shuts_down_comfy_when_free_keeps_vulkan_heap(settings):
    client = comfy_client(free_ok=True, vram_free=2_000_000_000)
    liberar_para_tts(settings, cliente=client, shutdown=record_shutdown)
    assert record_shutdown.calls == 1
```

- [ ] **Step 2: Verify RED**

Run: `uv run --no-cache pytest tests/gpu/test_broker.py tests/gpu/test_liberadores.py tests/test_config.py -q`

Expected: state shape and manual-consumer assertions fail.

- [ ] **Step 3: Persist PID ownership and detect stale state conservatively**

Replace string-only broker state with a Pydantic `GPUState`. `_gravar` uses
`os.getpid()` and UTC ISO timestamp. `ProcessInspector` uses `os.kill(pid, 0)`
on POSIX and `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` on Windows; any
inspection error means “alive” so the broker never steals a possibly valid
owner. A dead PID or unreadable state invokes every liberator before claiming.

- [ ] **Step 4: Release externally started services and diagnose rather than kill arbitrary Python**

Before every claim, probe LM Studio and ComfyUI even when no resident was
recorded. For target `tts`, call `/free`, inspect returned VRAM, then stop only
the configured ComfyUI process tree when heap remains. Replace POC's broad
“kill Python over 600 MB” behavior with a diagnostic event listing PID,
command line and working set; automatic termination is allowed only for a PID
previously started by the configured ComfyUI launcher.

Add settings `comfy_process_timeout=60`, `gpu_orphan_diagnostic_threshold_mb=600`
and validate both as positive.

- [ ] **Step 5: Verify and commit**

Run: `uv run --no-cache pytest tests/gpu/test_broker.py tests/gpu/test_liberadores.py tests/test_config.py -q`

Expected: PASS.

```bash
git add src/forge/gpu/broker.py src/forge/gpu/liberadores.py src/forge/infrastructure/config.py tests/gpu/test_broker.py tests/gpu/test_liberadores.py tests/test_config.py
git diff --cached --check
git commit -m "fix(studio): harden shared GPU ownership"
```

---

### Task 8: Audio executor, voice guard and 100% gate

**Files:**
- Create: `src/forge/executors/audio_generate.py`
- Create: `src/forge/executors/audio.py`
- Modify: `src/forge/infrastructure/config.py`
- Modify: `pyproject.toml`
- Create: `tests/executors/test_audio_generate.py`
- Create: `tests/executors/test_audio.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Produces: `AudioGenerateClient.synthesize_batch(items, output_dir) -> list[AudioOutcome]`.
- Produces artifacts: `video/audio/<block-id>.wav`; emits one terminal item event per block.
- Consumes: audio work items seeded by media-plan output and broker resource `tts` once per stage.

- [ ] **Step 1: Write RED tests for argv, classification, rescue and gate**

```python
def test_audio_command_uses_seed_and_model_defaults_without_sampler_flags(settings):
    argv = AudioGenerateClient(settings).build_argv(batch_file(), output_dir())
    assert argv[argv.index("--seed") + 1] == "42"
    assert "--temperature" not in argv
    assert "--top-k" not in argv
    assert "--top-p" not in argv
    assert "<|emotion:" not in batch_file().read_text(encoding="utf-8")


@pytest.mark.parametrize((stderr, code, failure_class), [
    ("reached max_tokens before EOC", "tts_max_tokens_before_eoc", FailureClass.DETERMINISTIC),
    ("ggml_vulkan: Device memory allocation", "tts_vulkan_oom", FailureClass.CAPACITY),
])
def test_audio_error_classification(stderr, code, failure_class):
    failure = classify_audio_failure(stderr, exit_code=1)
    assert (failure.code, failure.failure_class) == (code, failure_class)


def test_failed_batch_is_rescued_one_item_at_a_time(snapshot, emit, fake_client):
    fake_client.batch_result = failed_batch("b002")
    fake_client.single_results = {"b001": ok_wav(), "b002": failed_eoc(), "b003": ok_wav()}
    result = AudioExecutor(fake_client, fake_broker()).run(snapshot, emit)
    assert terminal_item_keys(emit) == {"b001", "b002", "b003"}
    assert result.gate.code == "audio_incomplete"
    assert result.current_items == 2
    assert result.total_items == 3


def test_retry_reuses_valid_successes_and_executes_only_previous_failures(snapshot, emit, fake_client):
    snapshot = retried_audio_snapshot(snapshot, succeeded=["b001", "b003"], failed=["b002"])
    AudioExecutor(fake_client, fake_broker()).run(snapshot, emit)
    assert fake_client.requested_item_keys == ["b002"]
    assert reused_item_keys(emit) == ["b001", "b003"]


def test_wav_gate_requires_24khz_mono_nonempty(tmp_path):
    invalid = write_wav(tmp_path / "stereo.wav", rate=44100, channels=2, frames=100)
    findings = validate_wav(invalid, expected_rate=24000, expected_channels=1)
    assert {item.code for item in findings} == {"audio_sample_rate", "audio_channels"}
```

- [ ] **Step 2: Verify RED**

Run: `uv run --no-cache pytest tests/executors/test_audio_generate.py tests/executors/test_audio.py tests/test_config.py -q`

Expected: new modules missing.

- [ ] **Step 3: Implement audio adapter with explicit configuration**

Add explicit dependencies `numpy>=2.0` and `soundfile>=0.13`. Add settings:

```python
audio_generate_dir: Path = Path(r"C:\dev\audio-generate")
tts_binary: Path | None = None
tts_model: Path | None = None
tts_voice_reference: Path | None = None
tts_seed: int = 42
tts_batch_size: int = Field(default=3, ge=1, le=8)
tts_item_timeout: float = Field(default=900, gt=0)
tts_batch_timeout: float = Field(default=3600, gt=0)
tts_sample_rate: int = Field(default=24000, gt=0)
```

Resolved properties point inside `audio_generate_dir` when explicit paths are
absent. `build_argv` uses a list, `shell=False`, fixed `cwd`, `--batch-text-file`,
seed and voice reference. Never add sampler or emotion flags. Capture only the
last 4 KiB of stderr.

- [ ] **Step 4: Implement stage-level batching, checkpoint and gate**

`AudioExecutor.prepare()` reads blocks from current `midia.json` and upserts
one item per block. Under one `broker.exclusivo("tts")`, `execute()` processes
pending items in groups of `tts_batch_size`; a partial/failed group retries
each unfinished block once alone. Each valid file emits `artifact.created`
with sample rate, channels, duration, F0 and seed, followed by
`item.succeeded`. Voice divergence uses median F0 and `3.5` MAD after at least
five valid blocks; at most two alternate seeds (`1042`, `2042`) are tried.
Before synthesis, exact same-hash outputs from earlier attempts pass through
`find_reusable_output()`; the executor emits a new current artifact record and
successful item event without invoking `audio-generate`.

`validate()` approves only when every planned block has a current, readable,
non-empty 24 kHz mono WAV and voice guard passes. It emits the Higgs
non-commercial license notice as `configuration.warning`, not as a gate pass.

- [ ] **Step 5: Verify and commit**

Run: `uv run --no-cache pytest tests/executors/test_audio_generate.py tests/executors/test_audio.py tests/narracao tests/services/test_runner.py tests/test_config.py -q`

Expected: PASS.

```bash
git add src/forge/executors/audio_generate.py src/forge/executors/audio.py src/forge/infrastructure/config.py pyproject.toml uv.lock tests/executors/test_audio_generate.py tests/executors/test_audio.py tests/test_config.py
git diff --cached --check
git commit -m "feat(studio): synthesize and gate complete narration"
```

---

### Task 9: Image executor, SDXL validation and reusable library

**Files:**
- Create: `src/forge/executors/estilo_visual.py`
- Create: `src/forge/executors/comfy.py`
- Create: `src/forge/executors/imagens.py`
- Modify: `src/forge/infrastructure/config.py`
- Modify: `pyproject.toml`
- Create: `tests/executors/test_estilo_visual.py`
- Create: `tests/executors/test_comfy.py`
- Create: `tests/executors/test_imagens.py`

**Interfaces:**
- Produces: deterministic `build_sdxl_workflow(prompt, seed, preset, compatible_loras)`.
- Produces: run-local `video/images/<beat-id>.png` and cache index under configured library.
- Consumes: image work items from `midia.json`, broker resource `imagem` once per stage.

- [ ] **Step 1: Write RED workflow, cache and image-gate tests**

```python
def test_body_preset_keeps_measured_sdxl_values():
    assert COSMOS_INTERIOR.width == 1024
    assert COSMOS_INTERIOR.height == 576
    assert COSMOS_INTERIOR.steps == 14
    assert COSMOS_INTERIOR.cfg == 3.2
    workflow = build_sdxl_workflow("threshold", seed=42, preset=COSMOS_INTERIOR, loras=[])
    assert workflow["decode"]["class_type"] == "VAEDecodeTiled"


def test_sd15_lora_is_rejected_from_sdxl_workflow(tmp_path):
    lora = write_safetensors_header(tmp_path / "old.safetensors", keys=576, max_dim=10240)
    assert inspect_lora(lora).compatible_sdxl is False


def test_exact_cache_hit_is_copied_into_run_and_records_provenance(snapshot, emit):
    cache = image_cache_with("prompt-hash", valid_png())
    result = ImageExecutor(fake_comfy(offline=True), cache, fake_broker()).run(snapshot, emit)
    artifact = artifact_event(emit)
    assert artifact["relative_path"].startswith("video/images/")
    assert artifact["metadata"]["source"] == "cache"
    assert result.gate.approved


def test_image_gate_requires_every_beat_and_exact_resolution(snapshot, emit):
    client = fake_comfy(images={"i001": png(1024, 576), "i002": png(512, 512)})
    result = ImageExecutor(client, empty_cache(), fake_broker()).run(snapshot, emit)
    assert result.gate.code == "images_incomplete"
    assert result.gate.findings[0].code == "image_resolution"


def test_retry_reuses_same_hash_images_and_renders_only_failed_beats(snapshot, emit):
    snapshot = retried_image_snapshot(snapshot, succeeded=["i001"], failed=["i002"])
    client = fake_comfy(images={"i002": png(1024, 576)})
    ImageExecutor(client, empty_cache(), fake_broker()).run(snapshot, emit)
    assert client.requested_item_keys == ["i002"]
    assert reused_item_keys(emit) == ["i001"]
```

- [ ] **Step 2: Verify RED**

Run: `uv run --no-cache pytest tests/executors/test_estilo_visual.py tests/executors/test_comfy.py tests/executors/test_imagens.py -q`

Expected: new modules missing.

- [ ] **Step 3: Port measured style and implement ComfyUI client**

Add `Pillow>=11`. Port Cosmos Interior constants without POC paths. The style
token excludes `starfield`; cosmic content comes from the beat scene. Keep only
LoRAs whose safetensors header has at least `1500` tensor keys and maximum
dimension at least `2048`.

`ComfyClient` uses httpx for `/system_stats`, `/prompt`, `/history/{id}` and
`/view`. `ensure_started()` launches only configured argv with `shell=False`,
hidden window, fixed cwd and PID file under `data/`. Poll every five seconds up
to configured timeout. Extract `execution_error` node type/id/message into a
stable failure, instead of persisting the raw status dict.

- [ ] **Step 4: Implement exact-key cache and 100% beat gate**

Add settings for `comfy_dir`, `comfy_python`, `comfy_output_dir`, `lora_dir`,
`image_library_dir`, `image_seed=42`, `image_width=1024`, `image_height=576`,
`image_steps=14`, `image_cfg=3.2`, `image_timeout=1800`. Cache key is SHA-256
over final prompt, negative prompt, seed, checkpoint, compatible LoRAs and
sampler settings. Protect index writes with `FileLock` plus atomic replace.

Every cache hit or generated image is copied into the run directory before
artifact registration. Metadata contains prompt, negative prompt, seed,
workflow hash, checkpoint, LoRAs, cache key and source (`generated`, `cache` or
`fallback`). Gate approval requires one current valid Pillow-readable image at
exact resolution for every required beat.
An earlier attempt's same-hash, catalog-verified beat output is registered for
the new attempt as `source="retry-reuse"` before cache or ComfyUI lookup.

- [ ] **Step 5: Verify and commit**

Run: `uv run --no-cache pytest tests/executors/test_estilo_visual.py tests/executors/test_comfy.py tests/executors/test_imagens.py tests/gpu -q`

Expected: PASS.

```bash
git add src/forge/executors/estilo_visual.py src/forge/executors/comfy.py src/forge/executors/imagens.py src/forge/infrastructure/config.py pyproject.toml uv.lock tests/executors/test_estilo_visual.py tests/executors/test_comfy.py tests/executors/test_imagens.py
git diff --cached --check
git commit -m "feat(studio): generate and gate visual beats"
```

---

### Task 10: FFmpeg composition from cataloged artifacts only

**Files:**
- Create: `src/forge/executors/ffmpeg.py`
- Create: `src/forge/executors/montagem.py`
- Modify: `src/forge/infrastructure/config.py`
- Create: `tests/executors/test_ffmpeg.py`
- Create: `tests/executors/test_montagem.py`

**Interfaces:**
- Produces: `probe_media(path) -> MediaProbe`, `build_ken_burns_filter(seconds, index, portrait)`, `ComposeExecutor`.
- Produces: `video/narration.wav`, `video/subtitles.srt`, `video/final.mp4`.
- Consumes: only current catalog entries supplied in `RunSnapshot.artifacts`; no filesystem discovery for inputs.

- [ ] **Step 1: Write RED command-construction and missing-input tests**

```python
def test_ken_burns_filter_scales_before_zoom_and_outputs_1080p():
    value = build_ken_burns_filter(seconds=12.0, index=0, portrait=False)
    assert value.index("scale=7680:4320") < value.index("zoompan=")
    assert "s=1920x1080" in value
    assert "format=yuv420p" in value


def test_concat_list_escapes_single_quotes_without_shell(tmp_path, runner):
    path = tmp_path / "image's clip.mp4"
    concat_files([path], tmp_path / "list.txt")
    assert "image'\\''s clip.mp4" in (tmp_path / "list.txt").read_text()
    assert runner.shell_values == {False}


def test_compose_refuses_36_of_41_audio_before_ffmpeg(snapshot, emit, runner):
    snapshot = with_artifacts(snapshot, audio=36, expected_audio=41, images=9)
    result = ComposeExecutor(runner).run(snapshot, emit)
    assert result.gate.code == "compose_inputs_incomplete"
    assert runner.calls == []


def test_compose_uses_only_catalog_paths(snapshot, emit, runner, tmp_path):
    (snapshot.run_dir / "video" / "images" / "uncataloged.png").write_bytes(png())
    ComposeExecutor(runner).run(snapshot, emit)
    assert "uncataloged.png" not in flatten(runner.calls)
```

- [ ] **Step 2: Verify RED**

Run: `uv run --no-cache pytest tests/executors/test_ffmpeg.py tests/executors/test_montagem.py -q`

Expected: new modules missing.

- [ ] **Step 3: Port deterministic media helpers**

Port only characterized behavior from POC `montar.py` and `montar_video.py`:
24 fps, 1920x1080, adaptive overscan `0.94/0.86`, 7680-wide pre-scale,
four alternating movements, `0.35s` silence between blocks, 92-character
subtitle cards and proportional timing. All subprocess calls use argv lists,
`shell=False`, bounded stderr and a timeout. Paths in concat files are absolute
paths derived by the backend from catalog entries.

- [ ] **Step 4: Implement ComposeExecutor and its immediate gate**

`prepare()` rejects missing current audio/image artifact counts before any
FFmpeg command. `execute()` computes each visual duration from actual WAV
duration and its block-to-beat mapping, renders clips, concatenates narration,
writes SRT, combines H.264 video and AAC audio, and emits artifacts for the
three durable outputs. Intermediate clips remain files but are not current
public artifacts.

`validate()` calls `ffprobe` and requires video codec `h264`, audio codec
`aac`, width `1920`, height `1080`, positive duration, both required streams
and duration difference from narration no greater than `max(0.5s, 1%)`.

- [ ] **Step 5: Verify and commit**

Run: `uv run --no-cache pytest tests/executors/test_ffmpeg.py tests/executors/test_montagem.py -q`

Expected: PASS.

```bash
git add src/forge/executors/ffmpeg.py src/forge/executors/montagem.py src/forge/infrastructure/config.py tests/executors/test_ffmpeg.py tests/executors/test_montagem.py
git diff --cached --check
git commit -m "feat(studio): compose video from cataloged media"
```

---

### Task 11: Final validation gate

**Files:**
- Create: `src/forge/executors/validacao.py`
- Create: `tests/executors/test_validacao.py`
- Add fixtures: `tests/fixtures/ffprobe/valid-video.json`, `tests/fixtures/ffmpeg/silence-ok.txt`, `tests/fixtures/ffmpeg/silence-failed.txt`

**Interfaces:**
- Produces: `video/validation.json` and sampled frames `video/validation/frame-{10,50,90}.jpg`.
- Consumes: current media plan, work items and catalog artifacts from prior stages.

- [ ] **Step 1: Write RED cross-check, silence and frame tests**

```python
def test_final_gate_cross_checks_plan_items_and_artifacts(snapshot, emit):
    snapshot = validation_snapshot(blocks=41, audio_items=41, audio_artifacts=40)
    result = ValidationExecutor(fake_ffmpeg()).run(snapshot, emit)
    assert result.gate.code == "final_validation_failed"
    assert "audio_count_mismatch" in finding_codes(result)


def test_silence_longer_than_threshold_fails(snapshot, emit):
    ffmpeg = fake_ffmpeg(silence=[Silence(start=12.0, end=18.1)])
    result = ValidationExecutor(ffmpeg, max_unplanned_silence_seconds=2.0).run(snapshot, emit)
    assert "unexpected_silence" in finding_codes(result)


def test_all_sample_frames_must_be_extractable(snapshot, emit):
    ffmpeg = fake_ffmpeg(frame_results={0.1: True, 0.5: False, 0.9: True})
    result = ValidationExecutor(ffmpeg).run(snapshot, emit)
    assert "frame_sample_failed" in finding_codes(result)


def test_valid_report_is_registered_before_worker_can_complete(snapshot, emit):
    result = ValidationExecutor(valid_fake_ffmpeg()).run(snapshot, emit)
    assert result.gate.approved
    kinds = artifact_kinds(emit)
    assert kinds.count("validation.report") == 1
    assert kinds.count("validation.frame") == 3
```

- [ ] **Step 2: Verify RED**

Run: `uv run --no-cache pytest tests/executors/test_validacao.py -q`

Expected: `forge.executors.validacao` missing.

- [ ] **Step 3: Implement all final checks in one deterministic report**

The executor records each check as `{code, approved, expected, actual}` and
calculates approval with `all(check.approved for check in checks)`. Required
checks: media-plan block/beat counts versus current items and artifacts; every
prior stage gate approved; WAV validity; image validity; final H.264/AAC probe;
1920x1080; duration coherence; no unplanned silence above configured threshold;
and successful JPEG extraction at 10%, 50% and 90% of duration.

- [ ] **Step 4: Prove completion remains behind this gate**

Extend `tests/services/test_worker.py` so `StageName.VALIDACAO` with rejected
gate leaves run `failed`, and only an approved `validation.report` event allows
the existing `validating -> completed` transition. The worker must check both
`StageResult.gate_status == "final_validation_approved"` and a current report
artifact linked to the current validation attempt.

- [ ] **Step 5: Verify and commit**

Run: `uv run --no-cache pytest tests/executors/test_validacao.py tests/services/test_worker.py -q`

Expected: PASS.

```bash
git add src/forge/executors/validacao.py tests/executors/test_validacao.py tests/fixtures/ffprobe/valid-video.json tests/fixtures/ffmpeg/silence-ok.txt tests/fixtures/ffmpeg/silence-failed.txt src/forge/services/worker.py tests/services/test_worker.py
git diff --cached --check
git commit -m "feat(studio): gate final video validation"
```

---

### Task 12: Reconcile interrupted runs without consuming orphan files

**Files:**
- Create: `src/forge/services/reconciliacao.py`
- Modify: `src/forge/repositories/operacao.py`
- Modify: `src/forge/services/worker.py`
- Create: `tests/services/test_reconciliacao.py`
- Modify: `tests/services/test_worker_acceptance.py`

**Interfaces:**
- Produces: `Reconciliador.reconcile(run_id) -> ReconciliationReport`.
- Produces repository mutations `mark_artifact_not_current`, `reset_missing_item`, `register_orphan`.
- Consumes current artifact catalog, work items and allowlisted artifact patterns only.

- [ ] **Step 1: Write RED recovery tests**

```python
def test_valid_succeeded_artifact_survives_reconciliation(tmp_path, db):
    item, artifact = succeeded_audio(tmp_path, db, present=True, matching_hash=True)
    report = Reconciliador(db, output_root(tmp_path)).reconcile(item_run_id(item))
    assert report.preserved == [artifact.id]
    assert get_item(db, item.id).status is ItemStatus.SUCCEEDED


@pytest.mark.parametrize("present,matching", [(False, False), (True, False)])
def test_missing_or_changed_file_resets_item_and_invalidates_artifact(tmp_path, db, present, matching):
    item, artifact = succeeded_audio(tmp_path, db, present=present, matching_hash=matching)
    report = Reconciliador(db, output_root(tmp_path)).reconcile(item_run_id(item))
    assert artifact.id in report.invalidated
    assert get_item(db, item.id).status is ItemStatus.FAILED
    assert not get_artifact(db, artifact.id).is_current


def test_known_unregistered_file_is_cataloged_as_noncurrent_orphan(tmp_path, db):
    path = write_known_audio_path(tmp_path, "b001.wav")
    report = Reconciliador(db, output_root(tmp_path)).reconcile(run_id(db))
    orphan = get_artifact(db, report.orphans[0])
    assert orphan.relative_path.endswith("b001.wav")
    assert orphan.kind == "orphan"
    assert orphan.is_current is False
    assert get_item(db, by_key="b001").status is ItemStatus.PENDING


def test_unknown_files_are_ignored_and_never_deleted(tmp_path, db):
    path = run_dir(tmp_path, db) / "notes.private"
    path.write_text("keep", encoding="utf-8")
    Reconciliador(db, output_root(tmp_path)).reconcile(run_id(db))
    assert path.read_text(encoding="utf-8") == "keep"
```

- [ ] **Step 2: Verify RED**

Run: `uv run --no-cache pytest tests/services/test_reconciliacao.py tests/services/test_worker_acceptance.py -q`

Expected: reconciler missing.

- [ ] **Step 3: Implement conservative reconciliation**

Known patterns are fixed in code:

```python
KNOWN_OUTPUTS = (
    "video/input.json", "video/midia.json", "video/manifesto.json",
    "video/audio/*.wav", "video/images/*.png", "video/images/*.jpg",
    "video/narration.wav", "video/subtitles.srt", "video/final.mp4",
    "video/validation.json", "video/validation/frame-*.jpg",
)
```

For every current artifact, resolve within run dir, require a regular file,
compare size and SHA-256, then preserve or invalidate. Missing/mismatched
per-item artifacts change the linked item to `failed` with stable codes
`artifact_missing` or `artifact_hash_mismatch`. Files matching `KNOWN_OUTPUTS`
without a catalog row become `orphan`, `is_current=false`, metadata
`{"discovered_during": "reconciliation"}`. Never unlink or replace a file.

- [ ] **Step 4: Wire reconciliation before an interrupted run resumes**

After `interrupt_expired()`, worker reconciles each newly interrupted run. On
resume, the next stage plan preserves only succeeded items whose current
artifact passed reconciliation; failed/pending items execute again. On a new
retry attempt, same-key/same-hash succeeded outputs are copied into new history
rows only after the same validation, while prior rows remain invalidated. Emit
one summary event with counts, not one event per preserved file. Add acceptance
proof: two valid WAVs plus one missing WAV, worker restart, retry stage; only
the missing block reaches fake audio executor.

- [ ] **Step 5: Verify and commit**

Run: `uv run --no-cache pytest tests/services/test_reconciliacao.py tests/services/test_worker_acceptance.py tests/repositories/test_operacao.py -q`

Expected: PASS.

```bash
git add src/forge/services/reconciliacao.py src/forge/repositories/operacao.py src/forge/services/worker.py tests/services/test_reconciliacao.py tests/services/test_worker_acceptance.py tests/repositories/test_operacao.py
git diff --cached --check
git commit -m "feat(studio): reconcile interrupted artifacts safely"
```

---

### Task 13: Register all executors and prove the complete fake pipeline

**Files:**
- Modify: `src/forge/services/studio.py`
- Modify: `src/forge/infrastructure/config.py`
- Create: `tests/services/test_executors_acceptance.py`
- Create: `tests/test_integration_executors.py`
- Modify: `tests/test_smoke.py`

**Interfaces:**
- Produces: `build_stage_executors(settings) -> dict[StageName, StageExecutor]` with all eight stages.
- Produces: `build_worker(settings, executors=None, worker_id="forge-worker")`; omission uses the real registry, explicit mapping remains test injection.
- Consumes: all prior tasks.

- [ ] **Step 1: Write RED registry and full-flow acceptance tests**

```python
def test_real_registry_has_exactly_the_eight_canonical_stages(settings):
    executors = build_stage_executors(settings)
    assert tuple(executors) == ETAPAS
    assert all(executor.stage is stage for stage, executor in executors.items())


def test_complete_fake_pipeline_persists_every_gate_and_completes(tmp_path):
    worker = build_worker(
        settings(tmp_path), executors=fake_process_executors(success_scenario()),
        worker_id="acceptance-worker",
    )
    run = enqueue(worker)
    for _ in ETAPAS:
        worker.run_once()
    detail = worker.control_plane.get_run(run.id)
    assert detail.run.status is RunStatus.COMPLETED
    assert [stage.gate_status for stage in detail.stages] == [
        "preparation_approved", "research_approved", "script_approved",
        "media_plan_approved", "audio_approved", "images_approved",
        "compose_approved", "final_validation_approved",
    ]


def test_partial_audio_blocks_compose_and_run_completion(tmp_path):
    scenario = success_scenario(audio_succeeded=36, audio_total=41)
    worker = build_worker(settings(tmp_path), executors=fake_process_executors(scenario), worker_id="w")
    run = drain_until_stopped(worker)
    assert run.status is RunStatus.FAILED
    assert run.failure_code == "audio_incomplete"
    assert scenario.compose_calls == 0
```

- [ ] **Step 2: Verify RED**

Run: `uv run --no-cache pytest tests/services/test_executors_acceptance.py tests/test_smoke.py -q`

Expected: real registry missing.

- [ ] **Step 3: Build the allowlisted registry from settings**

```python
def build_stage_executors(settings: Settings) -> dict[StageName, StageExecutor]:
    return {
        stage: StageProcessExecutor(
            stage=stage,
            output_root=settings.studio_runs_dir,
            timeout_seconds=settings.stage_timeout(stage),
        )
        for stage in ETAPAS
    }
```

`Settings.stage_timeout()` uses an immutable map with explicit limits per
stage; no client-controlled command or module name enters argv. `build_worker`
accepts `executors: Mapping[StageName, StageExecutor] | None`; only `None`
selects the real registry,
while `{}` continues to mean “intentionally no executors” in tests.
Pass `Redactor(settings.secret_values())` into `StudioWorker`; the returned
tuple includes generic, Anthropic and OpenAI keys after removing empty values.

- [ ] **Step 4: Add opt-in adapter smoke tests without running them by default**

`tests/test_integration_executors.py` contains one marked test each for:
research query, LM Studio short structured response, one short WAV, one 1024x576
Comfy image, one short H.264/AAC MP4, and simultaneous broker claims. Each test
calls `pytest.skip` with the missing service/path prerequisite. No integration
test is part of normal `pytest` because existing `addopts` excludes the marker.

- [ ] **Step 5: Run full verification and commit**

Run:

```bash
uv sync
uv run --no-cache pytest -q
uv run --no-cache python -m compileall -q src/forge
git diff --check
rg -n "C:\\\\dev\\\\_pipeline-poc|_pipeline-poc" src tests pyproject.toml
```

Expected: full suite PASS; compile command exits `0`; diff check exits `0`; final
`rg` exits `1` with no runtime/test references. References remain allowed only
in this plan and the design spec.

```bash
git add src/forge/services/studio.py src/forge/infrastructure/config.py tests/services/test_executors_acceptance.py tests/test_integration_executors.py tests/test_smoke.py
git diff --cached --check
git commit -m "test(studio): prove executor pipeline gates"
```

---

## Completion Evidence

Before marking Marco 3 complete, capture these outputs in the implementation
task:

```bash
git status --short
uv run --no-cache pytest -q
uv run --no-cache python -m compileall -q src/forge
git diff --check
rg -n "C:\\\\dev\\\\_pipeline-poc|_pipeline-poc" src tests pyproject.toml
```

Acceptance requires:

1. all eight stages are registered and isolated by `StageProcessExecutor`;
2. worker owns every operational SQLite mutation;
3. `manifesto.json` mirrors DB work items and never overrides them;
4. partial audio or image stages fail before composition;
5. final validation report exists and is current before run completion;
6. resume reruns only missing/invalid items;
7. GPU broker detects dead ownership and external service residency;
8. default suite uses no network/GPU/service;
9. no runtime or test path depends on `_pipeline-poc`;
10. worktree is clean after the final task commit.

## Execution Handoff

Plan complete. Recommended execution: `superpowers:subagent-driven-development`,
one task at a time, with spec-compliance review followed by code-quality review.
Alternative: `superpowers:executing-plans` in this session, in small batches with
review checkpoints after Tasks 3, 6, 9 and 13.
