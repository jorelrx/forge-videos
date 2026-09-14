# Forge Studio API and Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar o Marco 4 do Forge Studio: API FastAPI local e dashboard Next.js capazes de criar e acompanhar runs, comandar pausa/retomada/retry, receber eventos via SSE e visualizar artefatos com segurança.

**Architecture:** O SQLite continua fonte de verdade e nenhum handler executa a pipeline. Uma camada de leitura monta projeções próprias para UI sobre os repositórios existentes; rotas FastAPI finas usam essa camada e o `ControlPlaneService`; o frontend consome somente HTTP/SSE e atualiza sua projeção local ao receber eventos. API, worker e web permanecem processos independentes.

**Tech Stack:** Python 3.12, FastAPI 0.141.x, Uvicorn 0.52.x, Pydantic 2, sqlite3/WAL, httpx, pytest, Next.js 16.3, React 19.2, TypeScript 5, Vitest 5, Testing Library, CSS nativo, npm.

**Design spec:** `docs/superpowers/specs/2026-09-11-forge-video-studio-design.md`

## Global Constraints

- API faz bind somente em `127.0.0.1`; porta padrão `8765`.
- Frontend faz bind somente em `127.0.0.1`; porta padrão `3100`.
- CORS aceita somente `http://127.0.0.1:3100` e `http://localhost:3100`.
- Serviço local, usuário único, sem autenticação na V1.
- SQLite em `data/forge.db` permanece fonte de verdade para fila, runs, etapas, itens, comandos, eventos e catálogo.
- Handlers HTTP nunca executam pipeline, subprocesso de etapa, shell livre ou operação de GPU.
- Todos os POSTs de comando exigem `Idempotency-Key`; repetição da mesma chave e payload devolve o comando existente.
- Preview recebe apenas `artifact_id`; cliente nunca envia path de arquivo.
- Path resolvido deve permanecer dentro de `output/runs/<run-id>/`.
- MIME de preview limitado a Markdown, JSON, PNG, JPEG, WebP, WAV e MP4.
- WAV e MP4 aceitam uma única faixa HTTP `Range`; faixa inválida retorna `416` com `Content-Range: bytes */<size>`.
- SSE usa `id:` monotônico do banco, respeita `Last-Event-ID`, reproduz eventos perdidos antes do modo ao vivo e não duplica cursor.
- Segredos nunca entram em snapshot, eventos ou `GET /api/config/effective`; credenciais aparecem como `[REDACTED]` quando uma chave explícita fizer parte da resposta.
- Dashboard mostra status real ou indisponível; nunca inventa saúde de serviço ou GPU.
- Pausa continua cooperativa: texto da UI usa “pausa após o item atual”.
- Ordem visual e interna das etapas: `preparacao`, `pesquisa`, `roteiro`, `plano_midia`, `audio`, `imagens`, `montagem`, `validacao`.
- Testes Python padrão não acessam rede, serviços locais, GPU ou subprocessos reais.
- Testes web usam DOM simulado e fakes de `fetch`/`EventSource`; nenhuma suíte padrão depende da API ligada.
- Node.js mínimo `20.9`, conforme requisito do Next.js 16.
- Nenhum runtime aponta para `C:\dev\_pipeline-poc`.

---

## Scope Guard

Este plano cobre somente o **Marco 4 — API e dashboard**. Não criar os scripts
`start-studio.ps1`/`stop-studio.ps1`, importador de runs antigas, instalador,
publicação, autenticação, edição de mídia, timeline, execução multi-run ou teste
real ponta a ponta. Essas entregas pertencem ao Marco 5.

O dashboard pode criar uma run enfileirada; o worker já existente decide quando
reivindicá-la. Não adicionar comando `start` inexistente ao domínio. A ação
“iniciar” da especificação é o submit do formulário de novo vídeo.

## File Map

| File | Responsibility |
|---|---|
| `src/forge/services/studio_query.py` | Read model transacional para fila, histórico, detalhe, itens, métricas e artefatos |
| `src/forge/repositories/operacao.py` | Consultas mínimas ausentes: contagem, artefato por ID e itens correntes da run |
| `src/forge/repositories/eventos.py` | Página histórica regressiva e métricas mais recentes por etapa |
| `src/forge/services/saude.py` | Probes reais, limitadas e injetáveis de research, LM Studio, ComfyUI, TTS, FFmpeg e GPU |
| `src/forge/api/app.py` | Application factory, dependências, CORS e registro de routers |
| `src/forge/api/contracts.py` | Requests/responses públicos, sem vazar modelos internos acidentalmente |
| `src/forge/api/errors.py` | Tradução uniforme de erros de domínio para HTTP |
| `src/forge/api/routes/runs.py` | Vídeos, fila, histórico, detalhe e comandos |
| `src/forge/api/routes/events.py` | Paginação de eventos e endpoint SSE |
| `src/forge/api/routes/artifacts.py` | Catálogo e streaming seguro de artefatos |
| `src/forge/api/routes/system.py` | Saúde e configuração efetiva |
| `src/forge/api/sse.py` | Cursor, replay, keep-alive e serialização SSE |
| `src/forge/api/ranges.py` | Parser puro de uma faixa HTTP e leitor parcial |
| `src/forge/api/__main__.py` | Processo `forge-api` com host local fixo |
| `web/lib/contracts.ts` | Contratos TypeScript equivalentes às respostas públicas |
| `web/lib/api.ts` | Único cliente HTTP e gerador de URLs de preview/SSE |
| `web/hooks/use-studio-events.ts` | Ciclo de vida do `EventSource`, deduplicação e estado de conexão |
| `web/hooks/use-dashboard.ts` | Snapshot inicial, refresh dirigido por evento e comandos |
| `web/components/*` | Formulário, status, run, etapas, fila, histórico, log, preview e falhas |
| `web/app/page.tsx` | Composição da única tela V1 |
| `web/app/globals.css` | Tokens e layout responsivo sem framework visual extra |
| `tests/api/*` | Contratos HTTP, SSE, Range, segurança e aceite do backend |
| `web/**/*.test.ts(x)` | Cliente, hooks e comportamento visível do dashboard |

## Dependency Order

1. Read model público sem FastAPI.
2. Rotas REST e tratamento de erro.
3. Eventos paginados e SSE.
4. Catálogo e conteúdo de artefatos.
5. Saúde/configuração.
6. Scaffold e cliente web.
7. Estado reativo SSE.
8. Operação da run/fila.
9. Observabilidade, preview e acabamento.
10. Aceite cruzado e regressão.

---

### Task 1: Build the Studio read model

**Files:**
- Create: `src/forge/services/studio_query.py`
- Modify: `src/forge/repositories/operacao.py`
- Modify: `src/forge/repositories/eventos.py`
- Create: `tests/services/test_studio_query.py`
- Modify: `tests/repositories/test_operacao.py`
- Modify: `tests/repositories/test_eventos.py`

**Interfaces:**
- Consumes: `Database`, `OperacaoRepository`, `EventosRepository`, `ETAPAS` e modelos de `forge.domain.operacao`.
- Produces: `RunSummary`, `StageView`, `RunView`, `RunPage`, `EventPage`, `StudioQueryService`.
- Produces: `OperacaoRepository.count_runs()`, `get_artifact(artifact_id)`, `list_current_work_items(run_id)`.
- Produces: `EventosRepository.page(run_id, before_id, limit)` e `latest_stage_metrics(run_id)`.

- [ ] **Step 1: Write failing repository and read-model tests**

```python
# tests/services/test_studio_query.py
from forge.domain.operacao import RunStatus, StageName
from forge.services.studio_query import StudioQueryService


def test_queue_and_history_include_video_identity_and_stable_global_progress(db):
    # Use existing repository fixture to create two videos/runs. Mark the first
    # two current stages succeeded with progress=1 and the third at 0.5.
    queries = StudioQueryService(db)

    queue = queries.list_queue()
    assert queue[0].video.tema == "Tema prioritário"
    assert queue[0].progress == 0.0

    page = queries.list_runs(limit=1, offset=0)
    assert page.total == 2
    assert page.limit == 1
    assert page.offset == 0
    assert page.items[0].current_stage is StageName.ROTEIRO
    assert page.items[0].progress == (1 + 1 + 0.5) / 8


def test_run_view_uses_only_current_attempt_and_exposes_items_metrics_and_artifacts(db):
    queries = StudioQueryService(db)
    detail = queries.get_run("run-id")

    assert len(detail.stages) == 8
    assert detail.stages[StageName.AUDIO].attempt == 2
    assert [item.item_key for item in detail.stages[StageName.AUDIO].items] == ["b001"]
    assert detail.stages[StageName.AUDIO].metrics == {"duration_ms": 900}
    assert all(artifact.is_current for artifact in detail.artifacts)


def test_unknown_run_and_artifact_raise_key_error(db):
    queries = StudioQueryService(db)
    with pytest.raises(KeyError):
        queries.get_run("missing")
    with pytest.raises(KeyError):
        queries.get_artifact("missing")
```

Add focused repository tests proving:

```python
assert repo.count_runs() == 2
assert repo.get_artifact(artifact.id) == artifact
assert repo.list_current_work_items(run.id) == [current_attempt_item]

page = EventosRepository(conn).page(run.id, before_id=None, limit=2)
assert [event.id for event in page] == [second_last.id, last.id]
older = EventosRepository(conn).page(run.id, before_id=second_last.id, limit=2)
assert all(event.id < second_last.id for event in older)
```

- [ ] **Step 2: Run tests to verify RED**

Run: `uv run --no-cache pytest tests/repositories/test_operacao.py tests/repositories/test_eventos.py tests/services/test_studio_query.py -q`

Expected: FAIL because query methods and `forge.services.studio_query` do not exist.

- [ ] **Step 3: Add minimal repository queries**

Implement exact signatures:

```python
# src/forge/repositories/operacao.py
def count_runs(self) -> int:
    return int(self.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0])


def get_artifact(self, artifact_id: str) -> Artifact | None:
    row = self.conn.execute(
        "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
    ).fetchone()
    return _artifact_from_row(row) if row is not None else None


def list_current_work_items(self, run_id: str) -> list[WorkItem]:
    rows = self.conn.execute(
        f"""
        SELECT work_items.*
        FROM work_items
        JOIN stage_runs ON stage_runs.id = work_items.stage_run_id
        JOIN (
            SELECT stage, MAX(attempt) AS attempt
            FROM stage_runs WHERE run_id = ? GROUP BY stage
        ) current
          ON current.stage = stage_runs.stage
         AND current.attempt = stage_runs.attempt
        WHERE stage_runs.run_id = ?
        ORDER BY {_stage_order_sql('stage_runs.stage')}, work_items.item_key
        """,
        (run_id, run_id),
    ).fetchall()
    return [_work_item_from_row(row) for row in rows]

# src/forge/repositories/eventos.py
def page(
    self, run_id: str, *, before_id: int | None = None, limit: int = 100
) -> list[Event]:
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    query = "SELECT * FROM events WHERE run_id = ?"
    params: list[object] = [run_id]
    if before_id is not None:
        query += " AND id < ?"
        params.append(before_id)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    rows = self.conn.execute(query, params).fetchall()
    return list(reversed([_event_from_row(row) for row in rows]))

def latest_stage_metrics(self, run_id: str) -> dict[str, dict]:
    rows = self.conn.execute(
        """
        SELECT stage_runs.stage, events.payload_json
        FROM events
        JOIN stage_runs ON stage_runs.id = events.stage_run_id
        JOIN (
            SELECT stage, MAX(attempt) AS attempt
            FROM stage_runs WHERE run_id = ? GROUP BY stage
        ) current
          ON current.stage = stage_runs.stage
         AND current.attempt = stage_runs.attempt
        WHERE events.run_id = ? AND events.kind = 'stage.result'
        ORDER BY events.id ASC
        """,
        (run_id, run_id),
    ).fetchall()
    metrics: dict[str, dict] = {}
    for row in rows:
        payload = json.loads(row["payload_json"])
        metrics[row["stage"]] = payload.get("gate", {}).get("metrics", {})
    return metrics
```

`list_current_work_items` must join `work_items` against the maximum attempt of
each stage. `page` selects descending IDs, limits in SQL, then reverses the
result so the HTTP response is chronological. `latest_stage_metrics` reads the
latest `stage.result` per current `stage_run_id` and returns `payload.gate.metrics`
under the stage value; absent metrics become `{}`.

- [ ] **Step 4: Implement the read projection**

```python
# src/forge/services/studio_query.py
class RunSummary(BaseModel):
    run: Run
    video: Video
    progress: float = Field(ge=0, le=1)
    current_stage: StageName | None


class StageView(BaseModel):
    stage_run: StageRun
    items: list[WorkItem]
    metrics: JSON_OBJECT = Field(default_factory=dict)


class RunView(RunSummary):
    stages: dict[StageName, StageView]
    artifacts: list[Artifact]


class RunPage(BaseModel):
    items: list[RunSummary]
    total: int
    limit: int
    offset: int


class EventPage(BaseModel):
    items: list[Event]
    next_before_id: int | None


class StudioQueryService:
    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def _summary(repo: OperacaoRepository, run: Run) -> RunSummary:
        stages = repo.current_stages(run.id)
        video = repo.get_video(run.video_id)
        if video is None:
            raise KeyError(run.video_id)
        progress = sum(item.progress for item in stages) / len(ETAPAS)
        current = next(
            (item.stage for item in stages if item.status is not StageStatus.SUCCEEDED),
            StageName.VALIDACAO if run.status is RunStatus.COMPLETED else None,
        )
        return RunSummary(
            run=run, video=video, progress=progress, current_stage=current
        )

    def list_queue(self) -> list[RunSummary]:
        with self.db.connection() as conn:
            repo = OperacaoRepository(conn)
            return [self._summary(repo, run) for run in repo.list_queue()]

    def list_runs(self, *, limit: int = 50, offset: int = 0) -> RunPage:
        with self.db.connection() as conn:
            repo = OperacaoRepository(conn)
            items = [
                self._summary(repo, run)
                for run in repo.list_runs(limit=limit, offset=offset)
            ]
            return RunPage(
                items=items, total=repo.count_runs(), limit=limit, offset=offset
            )

    def get_run(self, run_id: str) -> RunView:
        with self.db.transaction() as conn:
            repo = OperacaoRepository(conn)
            run = repo.get_run(run_id)
            if run is None:
                raise KeyError(run_id)
            summary = self._summary(repo, run)
            current_stages = repo.current_stages(run_id)
            items = repo.list_current_work_items(run_id)
            metrics = EventosRepository(conn).latest_stage_metrics(run_id)
            by_stage_run = {
                stage.id: [item for item in items if item.stage_run_id == stage.id]
                for stage in current_stages
            }
            return RunView(
                **summary.model_dump(),
                stages={
                    stage.stage: StageView(
                        stage_run=stage,
                        items=by_stage_run[stage.id],
                        metrics=metrics.get(stage.stage.value, {}),
                    )
                    for stage in current_stages
                },
                artifacts=repo.list_artifacts(run_id, current_only=True),
            )

    def list_events(
        self, run_id: str, *, before_id: int | None = None, limit: int = 100
    ) -> EventPage:
        with self.db.connection() as conn:
            repo = OperacaoRepository(conn)
            if repo.get_run(run_id) is None:
                raise KeyError(run_id)
            items = EventosRepository(conn).page(
                run_id, before_id=before_id, limit=limit
            )
            return EventPage(
                items=items,
                next_before_id=items[0].id if len(items) == limit else None,
            )

    def events_after(
        self, cursor: int, *, run_id: str | None, limit: int = 200
    ) -> list[Event]:
        with self.db.connection() as conn:
            return EventosRepository(conn).after(cursor, run_id=run_id, limit=limit)

    def list_artifacts(
        self, run_id: str, *, current_only: bool = True
    ) -> list[Artifact]:
        with self.db.connection() as conn:
            repo = OperacaoRepository(conn)
            if repo.get_run(run_id) is None:
                raise KeyError(run_id)
            return repo.list_artifacts(run_id, current_only=current_only)

    def get_artifact(self, artifact_id: str) -> Artifact:
        with self.db.connection() as conn:
            artifact = OperacaoRepository(conn).get_artifact(artifact_id)
            if artifact is None:
                raise KeyError(artifact_id)
            return artifact
```

Run summary rules:

```python
progress = sum(stage.progress for stage in stages) / len(ETAPAS)
current_stage = next(
    (stage.stage for stage in stages if stage.status is not StageStatus.SUCCEEDED),
    StageName.VALIDACAO if run.status is RunStatus.COMPLETED else None,
)
```

Build every `RunView` inside one `db.transaction()` so retry cannot mix attempts
between reads.

- [ ] **Step 5: Verify GREEN and commit**

Run: `uv run --no-cache pytest tests/repositories/test_operacao.py tests/repositories/test_eventos.py tests/services/test_studio_query.py -q`

Expected: PASS.

```bash
git add src/forge/repositories/operacao.py src/forge/repositories/eventos.py src/forge/services/studio_query.py tests/repositories/test_operacao.py tests/repositories/test_eventos.py tests/services/test_studio_query.py
git commit -m "feat(studio): add dashboard read projections"
```

---

### Task 2: Expose the local REST control plane

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `src/forge/infrastructure/config.py`
- Modify: `src/forge/services/studio.py`
- Create: `src/forge/api/__init__.py`
- Create: `src/forge/api/app.py`
- Create: `src/forge/api/contracts.py`
- Create: `src/forge/api/errors.py`
- Create: `src/forge/api/routes/__init__.py`
- Create: `src/forge/api/routes/runs.py`
- Create: `src/forge/api/__main__.py`
- Create: `tests/api/__init__.py`
- Create: `tests/api/conftest.py`
- Create: `tests/api/test_runs.py`

**Interfaces:**
- Consumes: `ControlPlaneService`, `StudioQueryService`, `StudioPreset`, `Settings`.
- Produces: `create_app(services: ApiServices | None = None) -> FastAPI`, `forge-api` console script.
- Produces routes: `POST /api/videos`, `GET /api/queue`, `GET /api/runs`, `GET /api/runs/{id}`, pause, resume and stage retry.
- Produces test fixtures: `api_factory() -> FastAPI`, `control_plane -> ControlPlaneService`, and `register_wav(run_id, payload) -> Artifact` over one temporary database.

- [ ] **Step 1: Add failing HTTP contract tests**

```python
# tests/api/test_runs.py
def test_create_video_enqueues_approved_snapshot(client):
    response = client.post("/api/videos", json={
        "tema": "A coragem de permanecer",
        "tese": None,
        "priority": 50,
        "preset": "local-recomendado-v1",
    })
    assert response.status_code == 201
    body = response.json()
    assert body["video"]["tema"] == "A coragem de permanecer"
    assert body["run"]["status"] == "queued"
    assert body["run"]["config_snapshot"]["context_length"] == 16384
    assert "api_key" not in body["run"]["config_snapshot"]


def test_duplicate_pause_returns_same_command(client, running_run):
    headers = {"Idempotency-Key": "pause-r1-1"}
    first = client.post(f"/api/runs/{running_run.id}/pause", headers=headers)
    second = client.post(f"/api/runs/{running_run.id}/pause", headers=headers)
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]


def test_invalid_transition_is_409_and_unknown_run_is_404(client, queued_run):
    response = client.post(
        f"/api/runs/{queued_run.id}/resume",
        headers={"Idempotency-Key": "resume-invalid"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_transition"
    assert client.get("/api/runs/missing").status_code == 404


def test_retry_stage_is_allowlisted_by_enum(client, failed_run):
    response = client.post(
        f"/api/runs/{failed_run.id}/stages/shell/retry",
        headers={"Idempotency-Key": "bad-stage"},
    )
    assert response.status_code == 422
```

Also test missing/blank `Idempotency-Key`, queue priority ordering, paginated
history metadata, eight ordered stages in detail and exact CORS origins.

- [ ] **Step 2: Run tests to verify RED**

Run: `uv run --no-cache pytest tests/api/test_runs.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'forge.api'`.

- [ ] **Step 3: Add bounded dependencies and API settings**

Add:

```toml
# pyproject.toml
dependencies = [
    # existing entries stay unchanged
    "fastapi>=0.141,<0.142",
    "uvicorn>=0.52,<0.53",
]

[project.scripts]
forge = "forge.cli:main"
forge-api = "forge.api.__main__:main"
```

Add settings:

```python
studio_api_port: int = Field(default=8765, ge=1, le=65535)
studio_sse_poll_seconds: float = Field(default=0.25, gt=0)
studio_sse_keepalive_seconds: float = Field(default=15.0, gt=0)
```

Run `uv lock` after editing `pyproject.toml`. Host stays a constant in the
entrypoint, not an environment option.

- [ ] **Step 4: Define public contracts and dependency container**

```python
# src/forge/api/contracts.py
class CreateVideoRequest(BaseModel):
    tema: str = Field(min_length=1, max_length=500)
    tese: str | None = Field(default=None, max_length=2000)
    priority: int = Field(default=50, ge=0, le=100)
    preset: Literal["local-recomendado-v1"] = "local-recomendado-v1"


class CreateVideoResponse(BaseModel):
    video: Video
    run: Run


class ApiErrorDetail(BaseModel):
    code: str
    message: str


class ApiError(BaseModel):
    error: ApiErrorDetail
```

In `app.py`, define a frozen dependency bundle and application factory:

```python
@dataclass(frozen=True)
class ApiServices:
    settings: Settings
    commands: ControlPlaneService
    queries: StudioQueryService
    git_commit: str
    workflow_version: int = 1


def create_app(services: ApiServices | None = None) -> FastAPI:
    resolved = services or build_api_services(get_settings())
    app = FastAPI(title="Forge Video Studio", version="1")
    app.state.services = resolved
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:3100", "http://localhost:3100"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=[
            "Content-Type", "Idempotency-Key", "Last-Event-ID", "Range"
        ],
    )
    install_error_handlers(app)
    app.include_router(runs_router, prefix="/api")
    return app
```

`create_app()` constructs real services only when none are injected. Tests use
one temporary database and never patch module globals.

- [ ] **Step 5: Add REST routes and uniform errors**

Implement exact endpoints/status:

| Endpoint | Success |
|---|---|
| `POST /api/videos` | `201 CreateVideoResponse` |
| `GET /api/queue` | `200 list[RunSummary]` |
| `GET /api/runs?limit=50&offset=0` | `200 RunPage` |
| `GET /api/runs/{run_id}` | `200 RunView` |
| `POST /api/runs/{run_id}/pause` | `202 Command` |
| `POST /api/runs/{run_id}/resume` | `202 Command` |
| `POST /api/runs/{run_id}/stages/{stage}/retry` | `202 Command` |

Snapshot creation is allowlisted, never `settings.model_dump()`:

```python
def preset_from_settings(settings: Settings) -> StudioPreset:
    return StudioPreset(
        model=settings.resolved_model,
        context_length=settings.llm_context_length,
        llm_max_tokens=settings.llm_max_tokens,
        tts_backend=settings.tts_backend,
        tts_seed=settings.tts_seed,
        image_width=settings.image_width,
        image_height=settings.image_height,
        image_steps=settings.image_steps,
        image_cfg=settings.image_cfg,
    )
```

Map `KeyError` to `404 not_found`; `TransicaoInvalida` and
`IdempotencyConflict` to `409`; keep Pydantic validation as `422`. Never include
stack trace or request body in client error messages.

- [ ] **Step 6: Add fixed local entrypoint**

```python
# src/forge/api/__main__.py
def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "forge.api.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=settings.studio_api_port,
        log_level=settings.log_level.lower(),
    )
```

Configure `CORSMiddleware` with exactly the two allowed origins, credentials
disabled, methods `GET`/`POST`, headers `Content-Type`, `Idempotency-Key`,
`Last-Event-ID`, `Range`.

- [ ] **Step 7: Verify GREEN and commit**

Run: `uv run --no-cache pytest tests/api/test_runs.py tests/services/test_studio.py tests/test_config.py -q`

Expected: PASS.

```bash
git add pyproject.toml uv.lock src/forge/infrastructure/config.py src/forge/services/studio.py src/forge/api tests/api
git commit -m "feat(studio): expose local control plane api"
```

---

### Task 3: Add replayable event history and SSE

**Files:**
- Create: `src/forge/api/sse.py`
- Create: `src/forge/api/routes/events.py`
- Modify: `src/forge/api/app.py`
- Create: `tests/api/test_events.py`
- Create: `tests/api/test_sse.py`

**Interfaces:**
- Consumes: `StudioQueryService.list_events()` and `events_after()`.
- Produces: `GET /api/runs/{run_id}/events` and `GET /api/events/stream`.
- Produces: `iter_sse_events(queries, *, cursor, run_id, poll_seconds, keepalive_seconds, sleep) -> Iterator[ServerSentEvent]` for isolated testing.

- [ ] **Step 1: Write failing pagination and replay tests**

```python
def test_event_history_returns_latest_page_in_chronological_order(client, run_events):
    response = client.get(f"/api/runs/{run_events.run_id}/events?limit=2")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [2, 3]
    assert response.json()["next_before_id"] == 2


def test_sse_replays_strictly_after_last_event_id(sse_services):
    stream = iter_sse_events(
        sse_services.queries,
        cursor=1,
        run_id="r1",
        poll_seconds=0,
        keepalive_seconds=15,
        sleep=lambda _: None,
    )
    first = next(stream)
    second = next(stream)
    assert [first.id, second.id] == ["2", "3"]
    assert first.data["kind"] == "stage.started"


def test_sse_cursor_advances_without_duplicate_when_new_event_arrives(
    replay_then_live_queries,
):
    # Fake query returns [id=2], then [id=3].
    stream = iter_sse_events(
        replay_then_live_queries,
        cursor=1,
        run_id="r1",
        poll_seconds=0,
        keepalive_seconds=15,
        sleep=lambda _: None,
    )
    assert [next(stream).id, next(stream).id] == ["2", "3"]
```

Add route tests for `Last-Event-ID: 7`, optional `run_id`, negative cursor `422`,
`Content-Type: text/event-stream`, `Cache-Control: no-cache` and keep-alive
comment when no event arrives for 15 seconds.

- [ ] **Step 2: Run tests to verify RED**

Run: `uv run --no-cache pytest tests/api/test_events.py tests/api/test_sse.py -q`

Expected: FAIL because routes and generator do not exist.

- [ ] **Step 3: Implement the SSE cursor loop**

```python
# src/forge/api/sse.py
def iter_sse_events(
    queries: StudioQueryService,
    *,
    cursor: int,
    run_id: str | None,
    poll_seconds: float,
    keepalive_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[ServerSentEvent]:
    last_id = cursor
    idle_for = 0.0
    while True:
        events = queries.events_after(last_id, run_id=run_id, limit=200)
        if events:
            for event in events:
                if event.id <= last_id:
                    continue
                last_id = event.id
                yield ServerSentEvent(
                    id=str(event.id),
                    retry=1500,
                    data=event.model_dump(mode="json"),
                )
            idle_for = 0.0
            continue
        sleep(poll_seconds)
        idle_for += poll_seconds
        if idle_for >= keepalive_seconds:
            idle_for = 0.0
            yield ServerSentEvent(comment="keep-alive")
```

Do not set SSE `event:`; browser client uses generic `onmessage` and reads
`data.kind`. FastAPI's `EventSourceResponse` handles disconnect/cancellation.

- [ ] **Step 4: Implement routes and cursor precedence**

`Last-Event-ID` wins over query `after`; missing values mean `0`. Return headers:

```python
headers = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}
```

Validate referenced `run_id` before opening an infinite stream. Register router
under `/api`.

- [ ] **Step 5: Verify GREEN and commit**

Run: `uv run --no-cache pytest tests/api/test_events.py tests/api/test_sse.py -q`

Expected: PASS.

```bash
git add src/forge/api/sse.py src/forge/api/routes/events.py src/forge/api/app.py tests/api/test_events.py tests/api/test_sse.py
git commit -m "feat(studio): stream replayable sqlite events"
```

---

### Task 4: Serve artifact previews with path and Range safety

**Files:**
- Modify: `src/forge/services/catalogo.py`
- Create: `src/forge/api/ranges.py`
- Create: `src/forge/api/routes/artifacts.py`
- Modify: `src/forge/api/app.py`
- Modify: `tests/services/test_catalogo.py`
- Create: `tests/api/test_artifacts.py`
- Create: `tests/api/test_ranges.py`

**Interfaces:**
- Consumes: artifact metadata from `StudioQueryService`, `settings.studio_runs_dir`.
- Produces: `parse_range(value, size) -> ByteRange`, `iter_file_range(path, byte_range)`.
- Produces: `GET /api/runs/{id}/artifacts` and `GET /api/artifacts/{id}/content`.

- [ ] **Step 1: Write failing MIME, path and Range tests**

```python
@pytest.mark.parametrize("mime", [
    "text/markdown", "application/json", "image/png", "image/jpeg",
    "image/webp", "audio/wav", "video/mp4",
])
def test_preview_allowlist_contains_exact_v1_types(mime):
    assert mime in PREVIEW_MIME


@pytest.mark.parametrize(("header", "start", "end"), [
    ("bytes=0-3", 0, 3),
    ("bytes=4-", 4, 9),
    ("bytes=-4", 6, 9),
])
def test_single_range_forms(header, start, end):
    assert parse_range(header, 10) == ByteRange(start=start, end=end)


def test_audio_range_returns_206(client, wav_artifact):
    response = client.get(
        f"/api/artifacts/{wav_artifact.id}/content",
        headers={"Range": "bytes=4-7"},
    )
    assert response.status_code == 206
    assert response.content == b"4567"
    assert response.headers["content-range"] == "bytes 4-7/10"
    assert response.headers["accept-ranges"] == "bytes"


def test_traversal_record_and_unknown_mime_are_rejected(client, artifact_factory):
    assert client.get("/api/artifacts/traversal/content").status_code == 404
    assert client.get("/api/artifacts/executable/content").status_code == 415
```

Test multiple ranges, start beyond EOF, malformed unit and zero-byte file as
`416`; missing catalog file as `404`; full image/Markdown as `200`; catalog
query defaults to current artifacts and `?current_only=false` exposes history.

- [ ] **Step 2: Run tests to verify RED**

Run: `uv run --no-cache pytest tests/services/test_catalogo.py tests/api/test_ranges.py tests/api/test_artifacts.py -q`

Expected: FAIL because image MIME, Range parser and routes are absent.

- [ ] **Step 3: Align catalog and preview MIME allowlists**

```python
PREVIEW_MIME = frozenset({
    "text/markdown",
    "application/json",
    "image/png",
    "image/jpeg",
    "image/webp",
    "audio/wav",
    "video/mp4",
})
```

Add PNG/JPEG/WebP to `services.catalogo.ALLOWED_MIME` so valid image executor
artifacts can enter the catalog before preview. Preview stays narrower than the
catalog; do not expose MP3/OGG/FLAC/QuickTime/AVI in V1.

- [ ] **Step 4: Implement strict single-range parsing**

```python
@dataclass(frozen=True)
class ByteRange:
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1


class RangeNotSatisfiable(ValueError):
    pass


def parse_range(value: str, size: int) -> ByteRange:
    if size <= 0 or not value.startswith("bytes=") or "," in value:
        raise RangeNotSatisfiable(value)
    spec = value.removeprefix("bytes=")
    if "-" not in spec:
        raise RangeNotSatisfiable(value)
    start_text, end_text = spec.split("-", 1)
    if not start_text:
        if not end_text.isdecimal() or int(end_text) <= 0:
            raise RangeNotSatisfiable(value)
        length = min(int(end_text), size)
        return ByteRange(start=size - length, end=size - 1)
    if not start_text.isdecimal() or (end_text and not end_text.isdecimal()):
        raise RangeNotSatisfiable(value)
    start = int(start_text)
    end = min(int(end_text), size - 1) if end_text else size - 1
    if start >= size or end < start:
        raise RangeNotSatisfiable(value)
    return ByteRange(start=start, end=end)


def iter_file_range(path: Path, selected: ByteRange, chunk_size: int = 64 * 1024):
    with path.open("rb") as source:
        source.seek(selected.start)
        remaining = selected.length
        while remaining:
            chunk = source.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
```

Reject commas, units other than `bytes`, negative values, empty bounds, `size <=
0`, `start >= size` and `end < start`. Clamp a valid oversized end to `size-1`.

- [ ] **Step 5: Resolve server-owned artifact paths and stream content**

Resolution algorithm:

```python
artifact = queries.get_artifact(artifact_id)
run_root = (settings.studio_runs_dir / artifact.run_id).resolve(strict=True)
path = (run_root / artifact.relative_path).resolve(strict=True)
path.relative_to(run_root)
if not path.is_file():
    raise HTTPException(status_code=404)
```

Never accept `relative_path` from route/query/body. Full responses use
`FileResponse` with `Accept-Ranges: bytes`; partial responses use
`StreamingResponse`, exact `Content-Length`, `Content-Range` and status `206`.
Translate `RangeNotSatisfiable` to `416` and include total size.

- [ ] **Step 6: Verify GREEN and commit**

Run: `uv run --no-cache pytest tests/services/test_catalogo.py tests/api/test_ranges.py tests/api/test_artifacts.py -q`

Expected: PASS.

```bash
git add src/forge/services/catalogo.py src/forge/api/ranges.py src/forge/api/routes/artifacts.py src/forge/api/app.py tests/services/test_catalogo.py tests/api/test_ranges.py tests/api/test_artifacts.py
git commit -m "feat(studio): serve safe ranged artifact previews"
```

---

### Task 5: Report real service health and redacted effective config

**Files:**
- Create: `src/forge/services/saude.py`
- Create: `src/forge/api/routes/system.py`
- Modify: `src/forge/api/app.py`
- Modify: `src/forge/api/contracts.py`
- Create: `tests/services/test_saude.py`
- Create: `tests/api/test_system.py`

**Interfaces:**
- Consumes: `Settings`, `Broker.residente()`, fixed HTTP probes and local executable checks.
- Produces: `ServiceState`, `ServiceHealth`, `StudioHealthService.check_all()`.
- Produces: `GET /api/services` and `GET /api/config/effective`.

- [ ] **Step 1: Write failing health and redaction tests**

```python
def test_health_reports_each_required_dependency_without_guessing(health_service):
    result = health_service.check_all()
    assert set(result) == {"research", "lm_studio", "comfyui", "tts", "ffmpeg", "gpu"}
    assert result["research"].state == "available"
    assert result["comfyui"].state == "unavailable"
    assert result["comfyui"].message == "ComfyUI não respondeu"
    assert result["gpu"].details["resident"] == "llm"


def test_probe_exception_becomes_unavailable_instead_of_500(
    health_service, fake_probes
):
    fake_probes.research.side_effect = TimeoutError("offline")
    assert health_service.check_all()["research"].state == "unavailable"


def test_effective_config_contains_operational_values_and_no_secret(client, secret_settings):
    body = client.get("/api/config/effective").json()
    serialized = json.dumps(body)
    assert body["preset"]["model"] == "google/gemma-4-e4b"
    assert body["api"]["port"] == 8765
    assert "real-secret" not in serialized
    assert "api_key" not in serialized
```

- [ ] **Step 2: Run tests to verify RED**

Run: `uv run --no-cache pytest tests/services/test_saude.py tests/api/test_system.py -q`

Expected: FAIL because health service and routes do not exist.

- [ ] **Step 3: Implement explicit probes with short deadlines**

```python
class ServiceState(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    DEGRADED = "degraded"


class ServiceHealth(BaseModel):
    name: str
    state: ServiceState
    message: str
    latency_ms: int | None = None
    details: JSON_OBJECT = Field(default_factory=dict)


@dataclass(frozen=True)
class HealthProbes:
    research: Callable[[], bool]
    lm_studio: Callable[[], bool]
    comfyui: Callable[[], bool]
    tts: Callable[[], bool]
    ffmpeg: Callable[[], bool]
    gpu: Callable[[], str | None]
```

Real defaults:

- research: `GET {acervo_url}/health`, timeout 2 s;
- LM Studio: `GET {lm_studio_base_url}/models`, timeout 2 s;
- ComfyUI: `GET {comfy_url}/system_stats`, timeout 2 s;
- TTS: binary, model and voice reference all exist as files;
- FFmpeg: both `ffmpeg` and `ffprobe` resolve with `shutil.which`;
- GPU: `montar_broker(settings).residente()`; unreadable state is `degraded`, not free.

Each probe catches its own exception, records bounded operator text and never
returns raw response bodies, argv, credentials or stack traces.

- [ ] **Step 4: Return an allowlisted effective configuration**

```python
def effective_config(settings: Settings) -> dict:
    return {
        "preset": preset_from_settings(settings).model_dump(mode="json"),
        "api": {"host": "127.0.0.1", "port": settings.studio_api_port},
        "web": {"host": "127.0.0.1", "port": 3100},
        "worker": {
            "lease_seconds": settings.worker_lease_seconds,
            "heartbeat_seconds": settings.worker_heartbeat_seconds,
        },
        "services": {
            "research_url": settings.acervo_url,
            "lm_studio_url": settings.lm_studio_base_url,
            "comfyui_url": settings.comfy_url,
        },
    }
```

Do not serialize the complete `Settings`; future credential fields must remain
private by default.

- [ ] **Step 5: Verify GREEN and commit**

Run: `uv run --no-cache pytest tests/services/test_saude.py tests/api/test_system.py -q`

Expected: PASS.

```bash
git add src/forge/services/saude.py src/forge/api/routes/system.py src/forge/api/app.py src/forge/api/contracts.py tests/services/test_saude.py tests/api/test_system.py
git commit -m "feat(studio): expose real local service health"
```

---

### Task 6: Scaffold the typed Next.js client

**Files:**
- Create: `web/package.json`
- Create: `web/package-lock.json`
- Create: `web/tsconfig.json`
- Create: `web/next.config.ts`
- Create: `web/eslint.config.mjs`
- Create: `web/vitest.config.ts`
- Create: `web/vitest.setup.ts`
- Create: `web/app/layout.tsx`
- Create: `web/app/page.tsx`
- Create: `web/app/globals.css`
- Create: `web/lib/contracts.ts`
- Create: `web/lib/api.ts`
- Create: `web/lib/api.test.ts`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: HTTP contracts from Tasks 2–5.
- Produces: `createStudioApi(baseUrl?: string) -> StudioApi` with typed read and command methods.
- Produces: `artifactContentUrl(id: string) -> string` and `eventsUrl(runId?: string | null) -> string`.

- [ ] **Step 1: Create the package manifest and lockfile**

Use Node `>=20.9` and fixed major/minor compatibility:

```json
{
  "name": "forge-studio-web",
  "private": true,
  "engines": {"node": ">=20.9"},
  "scripts": {
    "dev": "next dev --hostname 127.0.0.1 --port 3100",
    "build": "next build",
    "start": "next start --hostname 127.0.0.1 --port 3100",
    "lint": "eslint .",
    "test": "vitest run"
  },
  "dependencies": {
    "next": "16.3.4",
    "react": "19.2.0",
    "react-dom": "19.2.0"
  },
  "devDependencies": {
    "@testing-library/dom": "^10.4.1",
    "@testing-library/jest-dom": "^6.9.1",
    "@testing-library/react": "^16.3.3",
    "@testing-library/user-event": "^14.6.1",
    "@types/node": "^24.0.0",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "eslint": "^9.0.0",
    "eslint-config-next": "16.3.4",
    "jsdom": "^27.0.0",
    "typescript": "^5.1.0",
    "vitest": "^5.0.0"
  }
}
```

Run: `npm install --prefix web`

Expected: `web/package-lock.json` created. Add `web/.next/`, `web/node_modules/`
and `web/coverage/` to `.gitignore`.

- [ ] **Step 2: Write failing API-client tests**

```typescript
// web/lib/api.test.ts
it("sends one caller-owned idempotency key", async () => {
  global.fetch = vi.fn().mockResolvedValue(jsonResponse(command));
  await api.pauseRun("r1", "pause-r1-click-1");
  expect(fetch).toHaveBeenCalledWith(
    "http://127.0.0.1:8765/api/runs/r1/pause",
    expect.objectContaining({
      method: "POST",
      headers: expect.objectContaining({"Idempotency-Key": "pause-r1-click-1"}),
    }),
  );
});

it("surfaces the stable API error", async () => {
  global.fetch = vi.fn().mockResolvedValue(
    jsonResponse({error: {code: "invalid_transition", message: "Run não pode retomar"}}, 409),
  );
  await expect(api.resumeRun("r1", "resume-1")).rejects.toMatchObject({
    code: "invalid_transition",
    status: 409,
  });
});
```

- [ ] **Step 3: Run tests to verify RED**

Run: `npm test --prefix web -- lib/api.test.ts`

Expected: FAIL because contracts/client do not exist.

- [ ] **Step 4: Define exact TypeScript contracts**

Mirror snake_case JSON names and string unions:

```typescript
export type RunStatus =
  | "queued" | "preparing" | "running" | "pausing" | "paused"
  | "validating" | "completed" | "failed" | "interrupted" | "cancelled";

export type StageName =
  | "preparacao" | "pesquisa" | "roteiro" | "plano_midia"
  | "audio" | "imagens" | "montagem" | "validacao";

export interface RunSummary {
  run: Run;
  video: Video;
  progress: number;
  current_stage: StageName | null;
}

export interface StageView {
  stage_run: StageRun;
  items: WorkItem[];
  metrics: Record<string, unknown>;
}

export interface RunView extends RunSummary {
  stages: Record<StageName, StageView>;
  artifacts: Artifact[];
}
```

Also define `RunPage`, `EventPage`, `StudioEvent`, `Command`, `ServiceHealth`,
`EffectiveConfig`, `CreateVideoInput` and `ApiErrorBody` with every field from
the Pydantic public response.

- [ ] **Step 5: Implement the only HTTP client**

```typescript
const API_BASE = process.env.NEXT_PUBLIC_FORGE_API_URL ?? "http://127.0.0.1:8765";

export class ApiFailure extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) { super(message); }
}

export interface StudioApi {
  createVideo(input: CreateVideoInput): Promise<CreateVideoResponse>;
  getQueue(): Promise<RunSummary[]>;
  getRuns(limit?: number, offset?: number): Promise<RunPage>;
  getRun(id: string): Promise<RunView>;
  getEvents(id: string, beforeId?: number): Promise<EventPage>;
  getServices(): Promise<Record<string, ServiceHealth>>;
  getEffectiveConfig(): Promise<EffectiveConfig>;
  pauseRun(id: string, key: string): Promise<Command>;
  resumeRun(id: string, key: string): Promise<Command>;
  retryStage(id: string, stage: StageName, key: string): Promise<Command>;
}
```

Use `encodeURIComponent` for IDs/stage, `cache: "no-store"`, JSON content type
only when a body exists and caller-provided idempotency key unchanged. No
automatic retry for POST.

- [ ] **Step 6: Add minimal App Router shell and verify**

`layout.tsx` sets Portuguese metadata and imports `globals.css`. `page.tsx`
temporarily renders `<main><h1>Forge Video Studio</h1></main>`.

Run:

```bash
npm test --prefix web
npm run lint --prefix web
npm run build --prefix web
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add .gitignore web
git commit -m "feat(studio): scaffold typed next dashboard"
```

---

### Task 7: Synchronize dashboard state through SSE

**Files:**
- Create: `web/hooks/use-studio-events.ts`
- Create: `web/hooks/use-studio-events.test.tsx`
- Create: `web/hooks/use-dashboard.ts`
- Create: `web/hooks/use-dashboard.test.tsx`
- Create: `web/test/fixtures.ts`

**Interfaces:**
- Consumes: `StudioApi`, browser `EventSource`, `StudioEvent`.
- Produces: `useStudioEvents(runId, dependencies)` and `useDashboard(api, dependencies)`.
- Produces connection states: `connecting | live | reconnecting | offline`.

- [ ] **Step 1: Write failing hook tests**

```typescript
it("deduplicates replayed events by monotonic id", () => {
  const {result} = renderHook(() => useStudioEvents("r1", {EventSource: FakeEventSource}));
  act(() => source.open());
  act(() => source.message(event({id: 41})));
  act(() => source.message(event({id: 41})));
  act(() => source.message(event({id: 42})));
  expect(result.current.events.map((item) => item.id)).toEqual([41, 42]);
  expect(result.current.connection).toBe("live");
});

it("refreshes projections once for an event burst", async () => {
  vi.useFakeTimers();
  const {result} = renderHook(() =>
    useDashboard(api, {EventSource: FakeEventSource}),
  );
  await initialLoad();
  act(() => emitEvents(threeEvents));
  await vi.advanceTimersByTimeAsync(150);
  expect(api.getQueue).toHaveBeenCalledTimes(2);
  expect(api.getRuns).toHaveBeenCalledTimes(2);
});
```

Test source close on unmount, parse failure ignored with connection retained,
API failure preserved as visible error, latest 200 events kept, and focus choice
order: active run, then paused/failed/interrupted, then none.

- [ ] **Step 2: Run tests to verify RED**

Run: `npm test --prefix web -- hooks`

Expected: FAIL because hooks do not exist.

- [ ] **Step 3: Implement EventSource lifecycle**

```typescript
export interface StudioEventsState {
  connection: "connecting" | "live" | "reconnecting" | "offline";
  events: StudioEvent[];
}

export function useStudioEvents(
  runId: string | null,
  dependencies: {EventSource?: typeof EventSource} = {},
): StudioEventsState {
  const [connection, setConnection] = useState<StudioEventsState["connection"]>("connecting");
  const [events, setEvents] = useState<StudioEvent[]>([]);
  const opened = useRef(false);

  useEffect(() => {
    const Source = dependencies.EventSource ?? window.EventSource;
    const source = new Source(eventsUrl(runId));
    source.onopen = () => {
      opened.current = true;
      setConnection("live");
    };
    source.onerror = () => setConnection(opened.current ? "reconnecting" : "offline");
    source.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data) as StudioEvent;
        setEvents((current) => {
          const byId = new Map(current.map((item) => [item.id, item]));
          byId.set(event.id, event);
          return [...byId.values()].sort((a, b) => a.id - b.id).slice(-200);
        });
      } catch {
        // Malformed public data is ignored; connection remains observable.
      }
    };
    return () => source.close();
  }, [runId, dependencies.EventSource]);

  return {connection, events};
}
```

The dashboard opens `/api/events/stream` globally so queue, history and focused
run stay synchronized. Keep the nullable `runId` parameter for a future
run-detail consumer that needs `?run_id=` filtering. On `open`, mark `live`; after a prior open, `error` means
`reconnecting`; before any successful open, `error` means `offline`. Do not
manually recreate on error: native `EventSource` preserves `Last-Event-ID` and
reconnects. Merge by numeric ID, sort ascending, cap at 200.

- [ ] **Step 4: Implement dashboard orchestration**

```typescript
export interface DashboardState {
  queue: RunSummary[];
  runs: RunSummary[];
  focusRun: RunView | null;
  services: Record<string, ServiceHealth>;
  events: StudioEvent[];
  connection: StudioEventsState["connection"];
  loading: boolean;
  error: ApiFailure | null;
  refresh(): Promise<void>;
  createVideo(input: CreateVideoInput): Promise<void>;
  pause(): Promise<void>;
  resume(): Promise<void>;
  retry(stage: StageName): Promise<void>;
}

export function useDashboard(
  api: StudioApi,
  dependencies: {EventSource?: typeof EventSource} = {},
): DashboardState {
  const {connection, events} = useStudioEvents(null, dependencies);
  const [queue, setQueue] = useState<RunSummary[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [focusRun, setFocusRun] = useState<RunView | null>(null);
  const [services, setServices] = useState<Record<string, ServiceHealth>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiFailure | null>(null);

  const captureFailure = useCallback((reason: unknown) => {
    setError(reason instanceof ApiFailure
      ? reason
      : new ApiFailure(0, "network_error", reason instanceof Error ? reason.message : "Falha desconhecida"));
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [nextQueue, page, nextServices] = await Promise.all([
        api.getQueue(),
        api.getRuns(50, 0),
        api.getServices(),
      ]);
      const focus = page.items.find((item) =>
        ["preparing", "running", "pausing", "validating"].includes(item.run.status),
      ) ?? page.items.find((item) =>
        ["paused", "failed", "interrupted"].includes(item.run.status),
      ) ?? null;
      const nextFocus = focus ? await api.getRun(focus.run.id) : null;
      setQueue(nextQueue);
      setRuns(page.items);
      setFocusRun(nextFocus);
      setServices(nextServices);
      setError(null);
    } catch (reason) {
      captureFailure(reason);
    } finally {
      setLoading(false);
    }
  }, [api, captureFailure]);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (events.length === 0) return;
    const timer = window.setTimeout(() => { void refresh(); }, 100);
    return () => window.clearTimeout(timer);
  }, [events, refresh]);

  const runCommand = useCallback(async (
    command: (runId: string, key: string) => Promise<Command>,
  ) => {
    if (!focusRun) {
      captureFailure(new ApiFailure(409, "no_focus_run", "Nenhuma run selecionada"));
      return;
    }
    setLoading(true);
    try {
      await command(focusRun.run.id, crypto.randomUUID());
      await refresh();
    } catch (reason) {
      captureFailure(reason);
    } finally {
      setLoading(false);
    }
  }, [captureFailure, focusRun, refresh]);

  return {
    queue,
    runs,
    focusRun,
    services,
    events,
    connection,
    loading,
    error,
    refresh,
    async createVideo(input) {
      setLoading(true);
      try {
        await api.createVideo(input);
        await refresh();
      } catch (reason) {
        captureFailure(reason);
      } finally {
        setLoading(false);
      }
    },
    pause: () => runCommand((runId, key) => api.pauseRun(runId, key)),
    resume: () => runCommand((runId, key) => api.resumeRun(runId, key)),
    retry: (stage) => runCommand((runId, key) => api.retryStage(runId, stage, key)),
  };
}
```

Initial `refresh` uses `Promise.all(getQueue, getRuns, getServices)`, then one
`getRun` for the chosen focus. Commands create exactly one `crypto.randomUUID()`
per user action, await API response, then refresh. Event bursts debounce one
refresh at 100 ms. Failed refresh keeps last good snapshot and exposes error.

- [ ] **Step 5: Verify GREEN and commit**

Run: `npm test --prefix web -- hooks`

Expected: PASS.

```bash
git add web/hooks web/test
git commit -m "feat(studio): synchronize dashboard over sse"
```

---

### Task 8: Build run creation, queue and controls

**Files:**
- Create: `web/components/new-video-form.tsx`
- Create: `web/components/new-video-form.test.tsx`
- Create: `web/components/run-progress.tsx`
- Create: `web/components/run-actions.tsx`
- Create: `web/components/run-actions.test.tsx`
- Create: `web/components/active-run.tsx`
- Create: `web/components/queue.tsx`
- Create: `web/components/dashboard.tsx`
- Modify: `web/app/page.tsx`

**Interfaces:**
- Consumes: `DashboardState` from Task 7.
- Produces: accessible form and state-aware pause/resume/retry controls.
- Produces: active-run stage rail and ordered queue.
- Produces: injectable `DashboardProps` seam for browser-independent behavior tests.
- Produces: `NewVideoFormProps` with `onSubmit` and optional `disabled`, `QueueProps.runs: RunSummary[]`, and `ActiveRunProps` with `run`, `disabled`, `onPause`, `onResume`, and `onRetry`.

- [ ] **Step 1: Write failing operator-flow tests**

```typescript
it("creates a queued video with only approved public fields", async () => {
  render(<NewVideoForm onSubmit={onSubmit} />);
  await user.type(screen.getByLabelText("Tema"), "O peso do silêncio");
  await user.type(screen.getByLabelText("Tese opcional"), "Silêncio também decide");
  await user.click(screen.getByRole("button", {name: "Enfileirar vídeo"}));
  expect(onSubmit).toHaveBeenCalledWith({
    tema: "O peso do silêncio",
    tese: "Silêncio também decide",
    priority: 50,
    preset: "local-recomendado-v1",
  });
});

it.each([
  ["running", "Solicitar pausa"],
  ["pausing", "Pausa após o item atual"],
  ["paused", "Retomar"],
  ["failed", "Retomar"],
  ["interrupted", "Retomar"],
])("shows the valid action for %s", (status, label) => {
  render(<RunActions run={runWithStatus(status)} {...callbacks} />);
  expect(screen.getByText(label)).toBeInTheDocument();
});
```

Test retry selector only for `paused`, `failed` or `completed`; all eight stage
options use Portuguese labels; queued priority order is preserved; submit and
commands disable during request; failures remain visible.

- [ ] **Step 2: Run tests to verify RED**

Run: `npm test --prefix web -- components/new-video-form.test.tsx components/run-actions.test.tsx`

Expected: FAIL because components do not exist.

- [ ] **Step 3: Implement form and command policy**

Form fields:

```typescript
const initialForm: CreateVideoInput = {
  tema: "",
  tese: null,
  priority: 50,
  preset: "local-recomendado-v1",
};
```

Priority is an integer input `0..100`; preset is a disabled/read-only select
with the one approved option. Trim theme/thesis before submit; empty thesis
becomes `null`; theme is required. No advanced model/TTS/image controls.

Action policy:

```typescript
const canPause = ["preparing", "running", "validating"].includes(run.status);
const pausePending = run.status === "pausing";
const canResume = ["paused", "failed", "interrupted"].includes(run.status);
const canRetry = ["paused", "failed", "completed"].includes(run.status);
```

- [ ] **Step 4: Implement active run and queue composition**

`RunProgress` renders global percentage and eight ordered stage rows using
`stage_run.progress`, item fraction, gate status and failure code. Use native
`<progress max={1}>`. `Queue` renders theme, priority and ordinal position; empty
state reads “Nenhum vídeo aguardando”. `ActiveRun` renders theme, thesis,
current stage, timestamps and actions.

`page.tsx` remains a Server Component that returns `<Dashboard />`; only
`dashboard.tsx` has `"use client"` and owns hooks.

```tsx
export interface DashboardProps {
  api?: StudioApi;
  eventSource?: typeof EventSource;
}

const defaultApi = createStudioApi();

interface DashboardViewProps {
  state: DashboardState;
}

export function DashboardView({state}: DashboardViewProps) {
  return (
    <main>
      <h1>Forge Video Studio</h1>
      <NewVideoForm onSubmit={state.createVideo} disabled={state.loading} />
      {state.focusRun ? (
        <ActiveRun
          run={state.focusRun}
          onPause={state.pause}
          onResume={state.resume}
          onRetry={state.retry}
          disabled={state.loading}
        />
      ) : <p>Nenhuma run ativa.</p>}
      <Queue runs={state.queue} />
    </main>
  );
}

export function Dashboard({
  api = defaultApi,
  eventSource,
}: DashboardProps) {
  const state = useDashboard(api, {EventSource: eventSource});
  return <DashboardView state={state} />;
}
```

- [ ] **Step 5: Verify GREEN and commit**

Run:

```bash
npm test --prefix web -- components
npm run lint --prefix web
```

Expected: PASS.

```bash
git add web/components web/app/page.tsx
git commit -m "feat(studio): add run controls and persistent queue ui"
```

---

### Task 9: Add history, live log, service strip and artifact preview

**Files:**
- Create: `web/components/service-strip.tsx`
- Create: `web/components/service-strip.test.tsx`
- Create: `web/components/live-log.tsx`
- Create: `web/components/history.tsx`
- Create: `web/components/artifact-preview.tsx`
- Create: `web/components/artifact-preview.test.tsx`
- Create: `web/components/failure-drawer.tsx`
- Create: `web/components/failure-drawer.test.tsx`
- Modify: `web/components/dashboard.tsx`
- Modify: `web/app/globals.css`

**Interfaces:**
- Consumes: health map, `RunView.artifacts`, events and failure fields.
- Produces: MIME-specific preview and technical evidence drawer.
- Produces: responsive single-screen control-room layout.

- [ ] **Step 1: Write failing observability tests**

```typescript
it("never renders unavailable service as healthy", () => {
  render(<ServiceStrip services={{comfyui: unavailableComfy}} connection="live" />);
  expect(screen.getByText("ComfyUI").closest("li")).toHaveAttribute("data-state", "unavailable");
  expect(screen.getByText("ComfyUI não respondeu")).toBeInTheDocument();
});

it.each([
  ["text/markdown", "article"],
  ["image/png", "img"],
  ["audio/wav", "audio"],
  ["video/mp4", "video"],
])("renders %s with the correct preview element", (mime, role) => {
  render(<ArtifactPreview artifact={artifactWithMime(mime)} />);
  expect(screen.getByRole(role)).toHaveAttribute(
    "src",
    "http://127.0.0.1:8765/api/artifacts/a1/content",
  );
});

it("shows short failure first and full evidence only in drawer", async () => {
  render(<FailureDrawer run={failedRun} failureEvent={failureEvent} />);
  expect(screen.getByText("Falha ao sintetizar bloco")).toBeVisible();
  expect(screen.queryByText("stack_trace")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", {name: "Ver detalhes técnicos"}));
  expect(screen.getByText(/recommended_action/)).toBeVisible();
});
```

Test JSON pretty-print, Markdown fetched as text (not `dangerouslySetInnerHTML`),
latest current artifact selected, invalidated artifact visibly labeled in
history, empty log state, event level markers and 200-event cap.

- [ ] **Step 2: Run tests to verify RED**

Run: `npm test --prefix web -- components/service-strip.test.tsx components/artifact-preview.test.tsx components/failure-drawer.test.tsx`

Expected: FAIL because components do not exist.

- [ ] **Step 3: Implement safe observability components**

Preview behavior:

- Markdown: fetch text and render inside `<pre>`/`<article>`; never inject HTML.
- JSON: fetch, `JSON.parse`, render `JSON.stringify(value, null, 2)`; malformed
  JSON becomes a visible preview error.
- PNG/JPEG/WebP: `<img>` with artifact kind as alt.
- WAV: `<audio controls preload="metadata">`.
- MP4: `<video controls preload="metadata">`.
- Unsupported MIME: metadata only, no request.

`History` shows newest runs with theme, status, duration, preset/model and global
progress. Selecting a run requests its detail without mutating it. `LiveLog`
shows time, level, message, stage/item and maintains chronological order.

- [ ] **Step 4: Apply a deliberate responsive control-room layout**

Use CSS custom properties and no UI dependency:

```css
:root {
  --bg: #0b0d10;
  --panel: #14181d;
  --panel-raised: #1b2027;
  --text: #f2f0e9;
  --muted: #929aa5;
  --signal: #e5ff52;
  --ok: #61d095;
  --warn: #f2b84b;
  --danger: #ff6b5f;
  --line: #2b323b;
  --radius: 14px;
}
```

Desktop: 12-column grid; active run occupies 8 columns, preview 4, queue/history
6 each, log full width. Under `900px`, one column. Keep focus outlines, 44px
minimum command targets, textual status alongside color, tabular numerals for
progress and `prefers-reduced-motion` disabling transitions.

- [ ] **Step 5: Compose all first-screen requirements**

Order in `Dashboard`:

1. title + SSE connection state;
2. service/GPU strip;
3. new-video form;
4. active/focus run and stage progress;
5. latest artifact preview;
6. queue;
7. history;
8. live log;
9. visible failure summary and technical drawer.

Every fetch/command error gets `role="alert"`; empty states remain explicit.

- [ ] **Step 6: Verify GREEN and commit**

Run:

```bash
npm test --prefix web
npm run lint --prefix web
npm run build --prefix web
```

Expected: PASS.

```bash
git add web/components web/app/globals.css
git commit -m "feat(studio): complete operator dashboard observability"
```

---

### Task 10: Prove the Marco 4 acceptance boundary

**Files:**
- Create: `tests/api/test_acceptance.py`
- Create: `web/components/dashboard.test.tsx`
- Modify: `README.md`
- Create: `docs/2026-09-13-marco4-status.md`

**Interfaces:**
- Consumes: complete API and dashboard.
- Produces: regression proof for API restart, replay, command idempotency, safe preview and full first-screen behavior.
- Preserves: CLI `forge roteiro`, worker and eight executor registrations.

- [ ] **Step 1: Write the cross-backend acceptance test**

```python
def test_api_restart_preserves_queue_history_commands_events_and_previews(
    api_factory, control_plane, register_wav
):
    first = TestClient(api_factory())
    created = [
        first.post("/api/videos", json={"tema": tema, "priority": priority}).json()
        for tema, priority in [("A", 10), ("B", 90), ("C", 50)]
    ]
    assert [item["video"]["tema"] for item in first.get("/api/queue").json()] == [
        "B", "C", "A"
    ]

    claimed = control_plane.claim_next("acceptance-worker", lease_seconds=15)
    assert claimed is not None
    run_id = claimed.id
    key = {"Idempotency-Key": "pause-acceptance-1"}
    command = first.post(f"/api/runs/{run_id}/pause", headers=key).json()
    assert first.post(f"/api/runs/{run_id}/pause", headers=key).json()["id"] == command["id"]
    artifact = register_wav(run_id, b"0123456789")

    restarted = TestClient(api_factory())
    assert restarted.get(f"/api/runs/{run_id}").status_code == 200
    events = restarted.get(f"/api/runs/{run_id}/events").json()["items"]
    assert [event["id"] for event in events] == sorted(event["id"] for event in events)
    partial = restarted.get(
        f"/api/artifacts/{artifact.id}/content",
        headers={"Range": "bytes=4-7"},
    )
    assert partial.status_code == 206
    assert partial.content == b"4567"
```

Keep the scenario in one test because restart continuity is the behavior under
proof. Add independent tests for CORS rejection, config secret scan and missing
artifact file.

- [ ] **Step 2: Write the full dashboard behavior test**

```typescript
it("renders and operates the complete V1 first screen", async () => {
  render(<Dashboard api={fakeApi} eventSource={FakeEventSource} />);

  expect(await screen.findByText("Forge Video Studio")).toBeVisible();
  expect(screen.getByText("Research")).toBeVisible();
  expect(screen.getByText("Run ativa")).toBeVisible();
  expect(screen.getByText("Fila")).toBeVisible();
  expect(screen.getByText("Histórico")).toBeVisible();
  expect(screen.getByText("Log ao vivo")).toBeVisible();
  expect(screen.getByText("Preview")).toBeVisible();

  await user.click(screen.getByRole("button", {name: "Solicitar pausa"}));
  expect(fakeApi.pauseRun).toHaveBeenCalledTimes(1);

  act(() => source.message(stageProgressEvent));
  expect(await screen.findByText("36 / 41")).toBeVisible();
});
```

- [ ] **Step 3: Run focused acceptance suites**

Run:

```bash
uv run --no-cache pytest tests/api -q
npm test --prefix web
```

Expected: PASS.

- [ ] **Step 4: Run complete regression and static gates**

Run:

```bash
uv run --no-cache pytest -q
uv run --no-cache python -m compileall -q src/forge
npm run lint --prefix web
npm run build --prefix web
git diff --check
rg -n "_pipeline-poc|C:\\dev\\_pipeline-poc" src web tests
```

Expected:

- Python suite PASS; integration-marked tests remain excluded by project config.
- compileall, lint, Next build and diff check exit `0`.
- final `rg` returns no runtime/test match.

- [ ] **Step 5: Document the completed boundary**

Update README with exact local development commands:

```powershell
uv run forge-api
npm run dev --prefix web
```

Create `docs/2026-09-13-marco4-status.md` only after every gate above passes.
Record commit range, Python test count, web test count, build result and explicit
deferred Marco 5 items: launcher, importer, real integration suite and complete
video.

- [ ] **Step 6: Commit**

```bash
git add tests/api/test_acceptance.py web/components/dashboard.test.tsx README.md docs/2026-09-13-marco4-status.md
git commit -m "test(studio): prove api and dashboard milestone"
```

---

## Spec Coverage Matrix

| Marco 4 requirement | Task |
|---|---|
| Create video and persistent queue | 1, 2, 8, 10 |
| Queue and paginated run history | 1, 2, 8, 9 |
| Run detail, stages, items, metrics and progress | 1, 2, 8 |
| Pause, resume and retry with idempotency | 2, 8, 10 |
| Invalid transition `409`; stage allowlist | 2 |
| Event history and SSE replay with `Last-Event-ID` | 3, 7, 10 |
| Artifact catalog and preview by ID | 4, 9 |
| MIME allowlist, path containment and HTTP Range | 4, 10 |
| Real service/GPU state | 5, 9 |
| Effective config without secrets | 5, 10 |
| First screen: active run, queue, history, log, preview, failures | 8, 9, 10 |
| Local-only bind and CORS | 2, 10 |
| API/frontend restart does not affect worker state | 2, 10 |
| CLI and executors remain available | 10 |
| No runtime POC dependency | Global constraints, 10 |

## References

- FastAPI native SSE (`ServerSentEvent`, `EventSourceResponse`): https://fastapi.tiangolo.com/tutorial/server-sent-events/
- Next.js 16 installation and Node.js `20.9+`: https://nextjs.org/docs/app/getting-started/installation
- Browser `EventSource` reconnection semantics: https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events

## Handoff

Marco 4 termina com API/dashboard locais testados contra SQLite e serviços
falsos. Marco 5 inicia somente após esses gates: scripts PowerShell de start/stop,
importador de runs legadas, validação de ferramentas instaladas, testes reais
marcados e um vídeo completo.
