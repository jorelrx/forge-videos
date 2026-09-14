# Forge Studio Marco 5 — Integração Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar o Marco 5 do Forge Studio: operação local iniciável/parável por scripts, importação somente-leitura de runs legadas, verificações reais das dependências e uma execução integrada que só conclui após produzir e validar um vídeo completo.

**Architecture:** O SQLite permanece a fonte operacional e recebe uma migração versionada mínima para distinguir runs históricas, imutáveis, de runs executáveis. Um processo `forge-worker` dedicado executa o laço já implementado; o launcher PowerShell apenas valida a máquina, aplica a migração, inicia os três processos e registra seus PIDs fora dos artefatos. Testes reais continuam opt-in, usam os adaptadores e executores de produção, e deixam a suíte padrão inteiramente offline.

**Tech Stack:** Python 3.12, sqlite3/WAL, Pydantic 2, FastAPI/Uvicorn, pytest 8, PowerShell 7+/Windows PowerShell 5.1, Node.js 20.9+, Next.js 16.3, FFmpeg/ffprobe, LM Studio, research, audio-generate, ComfyUI.

**Design specs:** `docs/superpowers/specs/2026-09-11-forge-video-studio-design.md`; `docs/superpowers/specs/2026-09-13-forge-studio-marcos1-4-release-design.md`

## Global Constraints

- Este plano só inicia depois de a Entrega técnica M1–M4 passar todos os critérios de aceite do design de 2026-09-13; falha nesse gate encerra a execução deste plano, sem correções de Marco 5 misturadas a ela.
- O Studio permanece local, de usuário único, com API em `127.0.0.1:8765` e web em `127.0.0.1:3100`; não iniciar Docker Desktop, serviços externos ou navegador de forma implícita fora de `start-studio.ps1`.
- `data/forge.db` é a fonte de verdade. Migrações são incrementais, transacionais, idempotentes e preservam bancos v1 existentes; nunca recriar ou apagar o banco para “migrar”.
- O worker executa no máximo uma run; não introduzir execução distribuída, múltiplos workers concorrentes, autenticação, Gateway Central, editor de mídia ou timeline.
- Todo artefato persistido continua relativo a `output/runs/<run-id>/`; importação copia, nunca move nem apaga, uma run legada antes de catalogá-la.
- Runs importadas são imutáveis: não entram na fila, não recebem pause/resume/retry e não têm artefatos invalidados ou sobrescritos.
- Scripts registram PIDs e logs sob `data/studio/`, nunca em `output/runs/`. O stop só finaliza árvores de processo cujos PIDs e linhas de comando pertençam ao próprio Studio.
- Pré-requisitos de binário/configuração são falhas legíveis; research, LM Studio, TTS e ComfyUI indisponíveis são reportados com ação concreta, sem inventar saúde e sem fallback web.
- Integrações reais usam `@pytest.mark.integration`, exigem `FORGE_RUN_INTEGRATION=1` e nunca rodam com `uv run pytest`, que mantém `-m not integration`.
- O teste ponta a ponta adicional exige `FORGE_RUN_STUDIO_E2E=1`; ele não aceita mocks de LLM, research, TTS, ComfyUI, FFmpeg, broker ou subprocessos.
- Snapshot, eventos, logs, relatório de doctor e documentação não podem expor segredos. Valores de chave devem aparecer apenas como `[REDACTED]`.
- Nenhum runtime, script ou teste pode referenciar `C:\dev\_pipeline-poc`.

---

## Scope Gate — Entrega M1–M4

O status atual em `docs/2026-09-13-marco4-status.md` registra aceitação parcial e
testes RED. Isso contradiz a dependência declarada na seção 20 do design: Marco 5
é posterior a um Marco 4 validado. Portanto esta primeira tarefa é bloqueante. Se
qualquer comando abaixo falhar, registrar a evidência no status M1–M4 e executar
`docs/superpowers/plans/2026-09-13-forge-studio-api-dashboard.md`; não implementar
nenhuma tarefa 1–8 deste plano nessa árvore até o gate ficar verde.

### Task 0: Provar a base M1–M4 antes de iniciar integração

**Files:**
- Modify: `docs/2026-09-13-marco4-status.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: os comandos Python, API, web e browser definidos no plano do Marco 4.
- Produces: evidência datada de que a Entrega técnica M1–M4 está aprovada, com comandos, contagens e commit; esse é o único insumo de início das tarefas seguintes.

- [ ] **Step 1: Executar os gates offline já contratados**

Run:

```powershell
uv run pytest -q
uv run python -m compileall -q src/forge
npm test --prefix web
npm run lint --prefix web
npm run build --prefix web
rg -n '_pipeline-poc|C:\\dev\\_pipeline-poc' src tests web scripts
```

Expected: todos os comandos saem `0`; a busca não encontra ocorrência. O primeiro
comando continua excluindo marker `integration` por `pyproject.toml`.

- [ ] **Step 2: Executar os aceites HTTP/SSE/dashboard do Marco 4**

Run:

```powershell
uv run pytest tests/api/test_acceptance.py tests/api/test_sse.py tests/api/test_artifacts.py -q
npm test --prefix web -- dashboard use-dashboard use-studio-events
```

Expected: PASS; `tests/api/test_acceptance.py` não pode mais conter expectativa RED
nem endpoint placeholder.

- [ ] **Step 3: Registrar resultado ou encerrar pelo bloqueio**

Acrescentar ao status, somente se todos os comandos passarem:

```markdown
## Gate M1–M4 para Marco 5

- Data: `YYYY-MM-DD`
- Commit: `<git rev-parse --short HEAD>`
- Python/API: `<contagem pytest>`
- Web: Vitest, lint e build aprovados
- Browser: aceite aprovado
- Integrações externas: deliberadamente excluídas por `-m not integration`
```

Se qualquer comando falhar, registrar o comando, saída resumida e link para o plano
do Marco 4; encerrar a execução aqui.

- [ ] **Step 4: Commit do gate de pré-requisito**

```powershell
git add docs/2026-09-13-marco4-status.md README.md
git commit -m "docs: record m1-m4 release gate"
```

---

## File Map

| File | Responsibility |
|---|---|
| `src/forge/repositories/migrations.py` | Descobre versão atual e aplica migrações SQLite dentro de uma transação exclusiva. |
| `src/forge/repositories/schema.py` | Delega inicialização à cadeia de migrações, incluindo v1→v2. |
| `src/forge/domain/operacao.py` | Expõe `Run.is_read_only` no contrato do domínio. |
| `src/forge/repositories/operacao.py` | Persiste/lê `is_read_only`; cria run importada sem enfileirá-la. |
| `src/forge/services/control_plane.py` | Rejeita comandos mutáveis contra histórico somente-leitura. |
| `src/forge/services/preflight.py` | Modelos e probes determinísticos de pré-requisitos locais, sem iniciar serviços. |
| `src/forge/studio/doctor.py` | CLI `forge-studio-doctor` para preflight humano/JSON e migração explícita. |
| `src/forge/worker/__main__.py` | CLI `forge-worker`, loop com shutdown por sinal e modo `--once`. |
| `src/forge/services/importador.py` | Copia e cataloga uma run legada com ID determinístico e proveniência. |
| `src/forge/studio/import_runs.py` | CLI `forge-import-runs` para importar um diretório ou todos os filhos diretos. |
| `scripts/studio-common.ps1` | Funções compartilhadas de estado de PID, porta, log e validação de processo. |
| `scripts/start-studio.ps1` | Pré-flight, migração, início de API/worker/web e browser opcional. |
| `scripts/stop-studio.ps1` | Pausa cooperativa, espera limitada e encerramento seguro/idempotente dos processos registrados. |
| `tests/repositories/test_migrations.py` | Upgrade v1→v2, segunda execução idempotente e preservação de dados. |
| `tests/services/test_preflight.py` | Classificação de pré-requisitos, redaction e nenhum side effect. |
| `tests/services/test_importador.py` | Importação, cópia segura, catálogo, idempotência e imutabilidade. |
| `tests/worker/test_main.py` | Loop do worker, `--once` e desligamento sem nova claim. |
| `tests/scripts/test_studio_scripts.ps1` | Exercita funções PowerShell com processos/portas falsos; não abre navegador nem inicia serviços. |
| `tests/integration/conftest.py` | Opt-in explícito, paths isolados, verificação de endpoints e limpeza segura. |
| `tests/integration/test_services_real.py` | Pesquisa, LM Studio, TTS, ComfyUI, FFmpeg e exclusão do broker contra dependências reais. |
| `tests/integration/test_studio_e2e.py` | Uma run Studio real, catálogo, gates e MP4 final. |
| `.env.example` | Configura Studio/launcher e documenta caminhos sem colocar segredos. |
| `README.md` | Instalação, doctor, start/stop, importação, comandos de integração e exclusões. |
| `docs/2026-09-14-marco5-status.md` | Evidência final, versões/ferramentas, artefato da run real e falhas conhecidas. |

## Dependency Order

1. Migrar o banco e tornar histórico realmente imutável.
2. Implementar preflight e processo worker invocável.
3. Importar runs legadas sobre o contrato já migrado.
4. Construir e testar start/stop a partir desses CLIs.
5. Trocar stubs de integração por testes reais isolados.
6. Rodar o vídeo completo e registrar evidência operacional.

---

### Task 1: Migrar banco v1→v2 e impedir mutação de histórico

**Files:**
- Create: `src/forge/repositories/migrations.py`
- Modify: `src/forge/repositories/schema.py`
- Modify: `src/forge/domain/operacao.py`
- Modify: `src/forge/repositories/operacao.py`
- Modify: `src/forge/services/control_plane.py`
- Create: `tests/repositories/test_migrations.py`
- Modify: `tests/repositories/test_operacao.py`
- Modify: `tests/services/test_control_plane.py`

**Interfaces:**
- Consumes: banco v1 criado pelo `SCHEMA_SQL` atual e `Database.transaction(immediate=True)`.
- Produces: `migrate(db: Database) -> int`, `LATEST_SCHEMA_VERSION = 2`, `Run.is_read_only: bool`, `OperacaoRepository.create_imported_video_and_run(...) -> tuple[Video, Run]`.
- Produces: `HistoricoSomenteLeitura`, erro de domínio convertido pela camada API existente em HTTP 409.

- [ ] **Step 1: Escrever testes RED de upgrade e read-only**

```python
def test_migrate_v1_to_v2_preserves_existing_run_and_adds_read_only(tmp_path):
    db = create_v1_database(tmp_path / "forge.db")
    with db.transaction(immediate=True) as conn:
        run_id = insert_v1_video_and_run(conn)

    assert migrate(db) == 2
    assert migrate(db) == 2

    with db.connection() as conn:
        row = conn.execute(
            "SELECT id, is_read_only FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
    assert dict(row) == {"id": run_id, "is_read_only": 0}


def test_read_only_run_cannot_pause_resume_or_retry(db):
    service = ControlPlaneService(db)
    _, run = create_imported_run(service, db)

    with pytest.raises(HistoricoSomenteLeitura):
        service.request_pause(run.id, idempotency_key="pause-legacy")
    with pytest.raises(HistoricoSomenteLeitura):
        service.request_resume(run.id, idempotency_key="resume-legacy")
    with pytest.raises(HistoricoSomenteLeitura):
        service.request_retry_stage(
            run.id, StageName.ROTEIRO, idempotency_key="retry-legacy"
        )
```

`create_v1_database` deve executar apenas o SQL da versão 1 salvo na fixture,
inserir um vídeo/run/artifact e escrever `schema_version=1`; não pode chamar
`init_db`, pois isso esconderia a migração.

- [ ] **Step 2: Confirmar RED**

Run:

```powershell
uv run pytest tests/repositories/test_migrations.py tests/services/test_control_plane.py -q
```

Expected: FAIL por ausência de `migrate`, coluna `is_read_only` e
`HistoricoSomenteLeitura`.

- [ ] **Step 3: Implementar cadeia de migrações transacional**

Usar exatamente esta forma: versão 1 é o esquema atual, e v2 adiciona somente a
coluna necessária. Não editar bancos antigos com `DROP TABLE`.

```python
# src/forge/repositories/migrations.py
LATEST_SCHEMA_VERSION = 2


def _upgrade_v1_to_v2(conn: sqlite3.Connection) -> None:
    conn.execute(
        "ALTER TABLE runs ADD COLUMN is_read_only "
        "INTEGER NOT NULL DEFAULT 0 CHECK(is_read_only IN (0, 1))"
    )


MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    1: _upgrade_v1_to_v2,
}


def migrate(db: Database) -> int:
    with db.transaction(immediate=True) as conn:
        _create_v1_if_absent(conn)
        version = _read_schema_version(conn)
        while version < LATEST_SCHEMA_VERSION:
            MIGRATIONS[version](conn)
            version += 1
            conn.execute("UPDATE schema_version SET version = ? WHERE id = 1", (version,))
        if version != LATEST_SCHEMA_VERSION:
            raise RuntimeError(f"schema version unsupported: {version}")
    return LATEST_SCHEMA_VERSION
```

`_create_v1_if_absent` deve executar os atuais `SCHEMA_SQL` somente quando
`schema_version` não existir; depois chama a validação física já existente. Mover
`SCHEMA_SQL`, `_validate_schema_version_table` e a validação de singleton para o
módulo de migrações ou importá-los sem duplicar definição. `init_db(db)` passa a
ser um alias fino de `migrate(db)` para manter os callers existentes.

Adicionar ao modelo e serialização:

```python
# domain/operacao.py
class Run(BaseModel):
    # campos atuais
    is_read_only: bool = False

# repositories/operacao.py, em INSERT/UPDATE/_run_from_row
int(run.is_read_only)
is_read_only=bool(row["is_read_only"])
```

`create_video_and_run` sempre grava `is_read_only=0`. O novo
`create_imported_video_and_run` cria `RunStatus.COMPLETED`, `finished_at=now`,
`is_read_only=True`, `priority=0`, `queue_position` novo e não emite stages
executáveis; ele cria as oito `stage_runs` uma vez, para que os artefatos possam
cumprir as foreign keys.

Antes de criar um comando em cada método mutável, chamar:

```python
def _require_mutable_run(self, operacao: OperacaoRepository, run_id: str) -> Run:
    run = self._require_run(operacao, run_id)
    if run.is_read_only:
        raise HistoricoSomenteLeitura(
            "run importada é histórico somente-leitura e não aceita comandos"
        )
    return run
```

- [ ] **Step 4: Confirmar GREEN e compatibilidade do esquema**

Run:

```powershell
uv run pytest tests/repositories/test_schema.py tests/repositories/test_migrations.py tests/repositories/test_operacao.py tests/services/test_control_plane.py -q
```

Expected: PASS. Inspecionar também que `schema_version` vale `2` e que a segunda
chamada de `init_db` não muda `runs`, `artifacts` nem `events`.

- [ ] **Step 5: Commit da migração**

```powershell
git add src/forge/repositories/migrations.py src/forge/repositories/schema.py src/forge/domain/operacao.py src/forge/repositories/operacao.py src/forge/services/control_plane.py tests/repositories/test_migrations.py tests/repositories/test_operacao.py tests/services/test_control_plane.py
git commit -m "feat: migrate studio history to read only"
```

---

### Task 2: Criar doctor de pré-requisitos e processo worker persistente

**Files:**
- Create: `src/forge/services/preflight.py`
- Create: `src/forge/studio/__init__.py`
- Create: `src/forge/studio/doctor.py`
- Create: `src/forge/worker/__init__.py`
- Create: `src/forge/worker/__main__.py`
- Modify: `src/forge/infrastructure/config.py`
- Modify: `pyproject.toml`
- Create: `tests/services/test_preflight.py`
- Create: `tests/worker/test_main.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Consumes: `Settings`, `build_worker(settings)`, `init_db`, `StudioHealthService` e paths configurados.
- Produces: `PreflightCheck(name, state, message, action)`, `PreflightReport.ok`, `check_preflight(settings, runner=...)`, `forge-studio-doctor`, `forge-worker`.
- Produces: `FORGE_STUDIO_WORKER_POLL_SECONDS`, default `1.0`, estritamente positivo.

- [ ] **Step 1: Escrever testes RED para doctor e loop**

```python
def test_preflight_marks_missing_ffmpeg_fatal_and_masks_secret(settings):
    report = check_preflight(
        settings,
        runner=lambda argv: CompletedProcess(argv, 1, "token=abc", ""),
        which=lambda name: None,
        path_exists=lambda path: True,
    )
    ffmpeg = next(check for check in report.checks if check.name == "ffmpeg")
    assert ffmpeg.state is CheckState.FAILED
    assert ffmpeg.action == "Instale FFmpeg e deixe ffmpeg/ffprobe no PATH."
    assert "abc" not in report.model_dump_json()


def test_worker_once_executes_one_claim_and_returns_zero(monkeypatch):
    calls = []
    monkeypatch.setattr("forge.worker.__main__.build_worker", lambda settings, worker_id: FakeWorker(calls))
    assert main(["--once", "--worker-id", "test-worker"]) == 0
    assert calls == ["run_once"]


def test_worker_stops_before_second_claim_after_shutdown(monkeypatch):
    stopped = Event()
    worker = FakeWorker([stopped.set])
    monkeypatch.setattr("forge.worker.__main__.build_worker", lambda *_: worker)
    assert run_loop(worker, poll_seconds=0.001, stopped=stopped) == 0
    assert worker.calls == 1
```

- [ ] **Step 2: Confirmar RED**

Run:

```powershell
uv run pytest tests/services/test_preflight.py tests/worker/test_main.py tests/test_config.py -q
```

Expected: FAIL por módulos/entry points inexistentes.

- [ ] **Step 3: Implementar checks puros e CLIs explícitos**

Implementar os modelos com estados `passed`, `warning` e `failed`. O report só é
`ok` quando nenhum check `failed`; warning não bloqueia o launcher.

```python
# src/forge/services/preflight.py
def check_preflight(settings: Settings, *, runner: Runner = subprocess.run,
                    which: Callable[[str], str | None] = shutil.which,
                    path_exists: Callable[[Path], bool] = Path.exists) -> PreflightReport:
    return PreflightReport(checks=[
        _version_check("python", [sys.executable, "--version"], (3, 12), runner),
        _version_check("node", ["node", "--version"], (20, 9), runner),
        _command_check("uv", ["uv", "--version"], runner),
        _ffmpeg_check(which),
        _path_check("tts_binary", settings.resolved_tts_binary),
        _path_check("tts_model", settings.resolved_tts_model),
        _path_check("tts_voice_reference", settings.resolved_tts_voice_reference),
        _directory_check("web_node_modules", Path("web/node_modules")),
        _external_service_check("research", settings.acervo_url),
        _external_service_check("lm_studio", settings.lm_studio_base_url),
        _external_service_check("comfyui", settings.comfy_url),
    ])
```

Checks HTTP têm timeout de 2 segundos e são `warning`, com ações respectivamente
“Inicie research em …”, “Inicie o servidor LM Studio em …” e “Inicie ComfyUI em …”.
Não usar URL retornada pelo serviço como comando shell. O redactor deve receber
`settings.secret_values()` antes de serializar stdout/stderr.

`forge-studio-doctor` aceita `--json` e `--migrate`. Com `--migrate`, chamar
`init_db(Database(settings.studio_db_path))` antes do report e imprimir
`SQLite schema 2 aplicado`; sem a flag não cria `data/` nem escreve banco.

```toml
[project.scripts]
forge-worker = "forge.worker.__main__:main"
forge-studio-doctor = "forge.studio.doctor:main"
forge-import-runs = "forge.studio.import_runs:main"
```

O worker instala handlers apenas para `SIGINT`/`SIGTERM` quando disponíveis,
chama `build_worker(settings, worker_id=...)`, e usa este loop:

```python
def run_loop(worker: StudioWorker, *, poll_seconds: float, stopped: Event) -> int:
    while not stopped.is_set():
        worker.run_once()
        stopped.wait(poll_seconds)
    return 0
```

`--once` chama `run_once` uma única vez e retorna 0 mesmo se não houver run.
Adicionar `studio_worker_poll_seconds: float = Field(default=1.0, gt=0)` a
`Settings`.

- [ ] **Step 4: Confirmar GREEN e CLIs**

Run:

```powershell
uv run pytest tests/services/test_preflight.py tests/worker/test_main.py tests/test_config.py -q
uv run forge-studio-doctor --help
uv run forge-worker --help
```

Expected: todos PASS/saem 0; `--help` não inicializa serviço, banco ou browser.

- [ ] **Step 5: Commit do runtime local**

```powershell
git add src/forge/services/preflight.py src/forge/studio src/forge/worker src/forge/infrastructure/config.py pyproject.toml tests/services/test_preflight.py tests/worker/test_main.py tests/test_config.py
git commit -m "feat: add studio doctor and worker process"
```

---

### Task 3: Importar runs legadas como cópias catalogadas e imutáveis

**Files:**
- Create: `src/forge/services/importador.py`
- Create: `src/forge/studio/import_runs.py`
- Create: `tests/services/test_importador.py`
- Modify: `src/forge/services/catalogo.py`
- Modify: `src/forge/api/contracts.py`
- Modify: `src/forge/api/routes/runs.py`

**Interfaces:**
- Consumes: diretório legado de `criar_run_dir` contendo Markdown numerado e/ou `video/`, `ControlPlaneService`, `OperacaoRepository`, `CatalogoArtefatos`.
- Produces: `LegacyRunImporter.import_one(source: Path) -> ImportedRun`, `ImportedRun(run_id: str, copied_files: int, skipped_files: int, already_imported: bool)`.
- Produces: resposta pública de run com `is_read_only: true` e erro HTTP 409 para comandos contra ela.

- [ ] **Step 1: Escrever fixture e testes RED de importação**

Criar em `tmp_path/legacy/20260913-liberdade/`:

```text
00-tema.md
01-research.md
03-write-r1.md
04-review-r1.md
video/midia.json
video/audio/b001.wav
video/images/beat-001.png
video/final.mp4
video/validation.json
```

Usar bytes mínimos válidos apenas para MIME/hash no teste; o importador não deve
tentar validar mídia nem chamar FFmpeg. Cobrir:

```python
def test_import_copies_known_files_under_uuid_run_and_registers_history(db, tmp_path):
    imported = LegacyRunImporter(db, output_root=tmp_path / "runs").import_one(legacy)

    assert (tmp_path / "runs" / imported.run_id / "video" / "midia.json").is_file()
    assert source_final.read_bytes() == copied_final.read_bytes()
    detail = StudioQueryService(db).get_run(imported.run_id)
    assert detail.run.status is RunStatus.COMPLETED
    assert detail.run.is_read_only is True
    assert {artifact.relative_path for artifact in detail.artifacts} >= {
        "00-tema.md", "video/midia.json", "video/final.mp4"
    }


def test_import_same_resolved_source_is_idempotent(db, tmp_path):
    first = importer.import_one(legacy)
    second = importer.import_one(legacy)
    assert second == first.model_copy(update={"already_imported": True})
    assert OperacaoRepository(...).count_runs() == 1


def test_import_rejects_symlink_and_leaves_database_and_output_unchanged(db, tmp_path):
    (legacy / "video" / "escape.mp4").symlink_to(tmp_path / "outside.mp4")
    with pytest.raises(LegacyImportError, match="symlink"):
        importer.import_one(legacy)
    assert not list((tmp_path / "runs").glob("*"))
```

- [ ] **Step 2: Confirmar RED**

Run:

```powershell
uv run pytest tests/services/test_importador.py tests/api/test_runs.py -q
```

Expected: FAIL porque importador e flag pública ainda não existem.

- [ ] **Step 3: Implementar cópia, mapeamento e proveniência**

O ID deve ser estável para impedir duplicação no mesmo source, mas não pode usar o
path como ID exposto:

```python
LEGACY_NAMESPACE = UUID("fd455955-b4e7-4b1d-a816-a30a6bc443e1")

def legacy_run_id(source: Path) -> str:
    return str(uuid5(LEGACY_NAMESPACE, str(source.resolve(strict=True)).casefold()))
```

Validar que `source` é diretório, não é symlink, e que cada arquivo encontrado é
regular e resolve dentro de `source.resolve()`. Recusar todo o import antes de
copiar se encontrar symlink. Ignorar `.stage-*.json`, `*.tmp`, `*.raw.md` e
`parcial.json`; catalogar arquivos regulares restantes. Copiar para
`output/runs/<run-id>` via `shutil.copy2`, criando o destino somente depois de
validar toda a árvore; se cópia ou catalogação falhar, remover somente esse destino
novo e fazer rollback da transação do banco. Nunca tocar no source.

Determinar artefato/stage por regra fechada:

| Path | Stage | kind |
|---|---|---|
| `00-tema.md`, `02-plan.md` | `preparacao` | `legacy.markdown` |
| `01-research*.md`, `video/research.json` | `pesquisa` | `research` |
| `03-write*.md`, `04-review*.md`, `roteiro.md`, `video/roteiro.*` | `roteiro` | `roteiro_markdown` ou `roteiro` |
| `video/midia.json` | `plano_midia` | `media_plan` |
| `video/audio/*.wav`, `video/narration.wav` | `audio` | `audio.wav` |
| `video/images/*.{png,jpg,jpeg,webp}` | `imagens` | `image.png`/`image.jpeg`/`image.webp` |
| `video/final.mp4` | `montagem` | `video/final.mp4` |
| `video/validation.json`, `video/validation/*` | `validacao` | `validation.report`/`validation.frame` |

Arquivos não mapeados recebem stage `preparacao`, kind `legacy.unknown` e MIME
obtido por `mimetypes.guess_type`, com fallback `application/octet-stream`; eles
continuam não-previewáveis. Para cada arquivo, usar o hash/size/MIME da mesma
função de `CatalogoArtefatos`, não reimplementar SHA-256.

O `config_snapshot` importado é somente:

```python
{
    "legacy_import": True,
    "legacy_source_name": source.name,
    "imported_at": now.isoformat(),
    "workflow_version": 1,
}
```

Não armazenar path absoluto do source. Marcar `is_read_only=True`; stages que
receberam arquivos ficam `SUCCEEDED` com `gate_status="imported_unverified"`;
demais ficam `INVALIDATED`. A run fica `COMPLETED`, `failure_code=None`, sem lease
e sem evento que alegue validação de produção. Adicionar só o evento
`run.imported` com contagens, sem paths absolutos.

CLI aceita exatamente:

```text
forge-import-runs C:\caminho\para\uma-run
forge-import-runs C:\caminho\para\output\runs --children
```

Sem `--children`, o argumento é uma única run. Com `--children`, iterar apenas
filhos diretos diretórios em ordem de nome e retornar exit 1 se qualquer filho
falhar; imprimir por linha `run_id copied_files skipped_files already_imported`.

- [ ] **Step 4: Confirmar GREEN e rota read-only**

Run:

```powershell
uv run pytest tests/services/test_importador.py tests/api/test_runs.py tests/api/test_artifacts.py -q
uv run forge-import-runs --help
```

Expected: PASS; a listagem/detalhe mostra `is_read_only=true`, preview usa a cópia
canônica `output/runs/<run-id>/`, e POST pause/resume/retry retorna 409.

- [ ] **Step 5: Commit do importador**

```powershell
git add src/forge/services/importador.py src/forge/studio/import_runs.py src/forge/services/catalogo.py src/forge/api/contracts.py src/forge/api/routes/runs.py tests/services/test_importador.py
git commit -m "feat: import legacy runs as read only history"
```

---

### Task 4: Implementar launcher e stop PowerShell idempotentes

**Files:**
- Create: `scripts/studio-common.ps1`
- Create: `scripts/start-studio.ps1`
- Create: `scripts/stop-studio.ps1`
- Create: `tests/scripts/test_studio_scripts.ps1`
- Modify: `.gitignore`
- Modify: `.env.example`

**Interfaces:**
- Consumes: `forge-studio-doctor --migrate`, `forge-api`, `forge-worker`, npm/web, portas 8765/3100.
- Produces: `data/studio/processes.json`, `data/studio/logs/api.log`, `worker.log`, `web.log`.
- Produces: parâmetros `-NoBrowser`, `-WebMode dev|production`, `-GraceSeconds <1..300>`, `-Force`.

- [ ] **Step 1: Escrever testes RED de funções de processo**

No teste PowerShell, dot-source somente `studio-common.ps1`, substitua
`Get-Process`, `Get-CimInstance`, `Start-Process`, `taskkill.exe` e
`Test-NetConnection` por funções locais. Cobrir:

```powershell
It 'grava e lê somente PIDs inteiros de API worker e web' {
  Save-StudioState -Root $TestDrive -Processes @{
    api = @{ pid = 1001; command = 'forge-api' }
    worker = @{ pid = 1002; command = 'forge-worker' }
    web = @{ pid = 1003; command = 'next' }
  }
  (Read-StudioState -Root $TestDrive).api.pid | Should -Be 1001
}

It 'recusa encerrar PID cuja linha de comando não pertence ao Studio' {
  { Stop-RegisteredStudioProcess -ProcessInfo @{ pid = 77; command = 'powershell' } } |
    Should -Throw '*não pertence ao Forge Studio*'
}
```

Se Pester não estiver instalado, o próprio arquivo deve detectar isso e sair 0 com
mensagem explícita “Pester não instalado; execute o teste unitário Python de parser
de estado”; adicionar então `tests/scripts/test_state_parser.py` com os mesmos JSONs.
Não adicionar Pester à instalação de produção.

- [ ] **Step 2: Confirmar RED**

Run:

```powershell
pwsh -NoProfile -File tests/scripts/test_studio_scripts.ps1
uv run pytest tests/scripts -q
```

Expected: FAIL por scripts/funções ausentes; se só Windows PowerShell existir, usar
`powershell.exe -NoProfile -ExecutionPolicy Bypass -File ...` e registrar isso no
README.

- [ ] **Step 3: Implementar estado, start e stop**

`studio-common.ps1` define `$StudioRoot = Resolve-Path (Join-Path $PSScriptRoot '..')`
e `$StudioStatePath = Join-Path $StudioRoot 'data/studio/processes.json'`. Serializar
JSON com esta forma exata:

```json
{
  "version": 1,
  "startedAt": "2026-09-14T00:00:00Z",
  "processes": {
    "api": {"pid": 1001, "command": "forge-api", "log": "data/studio/logs/api.log"},
    "worker": {"pid": 1002, "command": "forge-worker", "log": "data/studio/logs/worker.log"},
    "web": {"pid": 1003, "command": "next", "log": "data/studio/logs/web.log"}
  }
}
```

`Read-StudioState` valida `version -eq 1`, os três nomes fixos, PID inteiro
positivo e paths de log relativos a `data/studio/logs`; estado malformado é tratado
como stale, renomeado para `processes.invalid-<UTC>.json`, nunca usado para matar
processo. Antes de matar, `Stop-RegisteredStudioProcess` lê a CommandLine via
`Get-CimInstance Win32_Process` e exige respectivamente `forge-api`,
`forge-worker` ou `next`; caso contrário lança o erro acima e preserva o PID.

`start-studio.ps1` deve:

1. importar `studio-common.ps1`, criar `data/studio/logs`, e se o estado válido
   tiver os três processos vivos, imprimir URLs/logs e sair 0 sem duplicar processos;
2. chamar `uv run forge-studio-doctor --migrate`; se falhar, sair com o mesmo exit
   code sem iniciar nada; warnings de serviços externos permanecem visíveis;
3. se o estado for stale, chamar `stop-studio.ps1 -Force` somente para PIDs validados;
4. iniciar ocultamente, com diretório de trabalho raiz e arquivos de log separados:

```powershell
$api = Start-Process -FilePath 'uv' -ArgumentList @('run','forge-api') -WorkingDirectory $StudioRoot -WindowStyle Hidden -RedirectStandardOutput $apiLog -RedirectStandardError $apiLog -PassThru
$worker = Start-Process -FilePath 'uv' -ArgumentList @('run','forge-worker') -WorkingDirectory $StudioRoot -WindowStyle Hidden -RedirectStandardOutput $workerLog -RedirectStandardError $workerLog -PassThru
$web = Start-Process -FilePath 'npm.cmd' -ArgumentList @('--prefix','web','run',$webScript,'--','-H','127.0.0.1','-p','3100') -WorkingDirectory $StudioRoot -WindowStyle Hidden -RedirectStandardOutput $webLog -RedirectStandardError $webLog -PassThru
```

`$webScript` é `dev` por padrão e `start` para `-WebMode production`. Esperar cada
porta por até 30 segundos em polling de 250 ms; se uma não abrir ou processo morrer,
executar `stop-studio.ps1 -Force`, mostrar os últimos 40 lines dos três logs e sair 1.
Só depois de ambas abrirem gravar `processes.json`; sem `-NoBrowser`, executar
`Start-Process 'http://127.0.0.1:3100'`.

`stop-studio.ps1` tenta antes uma pausa cooperativa: `GET /api/runs?limit=100`, para
cada status `preparing`, `running` ou `pausing` envia `POST /api/runs/<id>/pause`
com `Idempotency-Key: stop-<run-id>`, e espera no máximo `-GraceSeconds` pelo status
`paused`, `failed`, `interrupted` ou `completed`. Não há chamada se API estiver fora.
Depois disso, para cada PID validado ainda vivo chama
`taskkill.exe /PID <pid> /T /F`, apagando `processes.json` apenas depois de todos os
PIDs terem terminado ou não existirem. Sem arquivo de estado, imprimir
“Forge Studio não está em execução” e sair 0. `-Force` pula a espera, mas nunca a
validação de command line.

Adicionar a `.gitignore`:

```gitignore
data/studio/
data/forge.db
data/forge.db-shm
data/forge.db-wal
```

Acrescentar a `.env.example` as variáveis `FORGE_STUDIO_DB_PATH`,
`FORGE_STUDIO_RUNS_DIR`, `FORGE_STUDIO_API_PORT`, `FORGE_STUDIO_WORKER_POLL_SECONDS`,
paths TTS/Comfy e aviso de que credenciais não entram no launcher.

- [ ] **Step 4: Confirmar GREEN sem iniciar infraestrutura externa**

Run:

```powershell
pwsh -NoProfile -File tests/scripts/test_studio_scripts.ps1
uv run pytest tests/scripts tests/services/test_preflight.py tests/worker/test_main.py -q
.\scripts\start-studio.ps1 -NoBrowser
.\scripts\stop-studio.ps1 -GraceSeconds 1
```

Expected: testes PASS; último par inicia API/worker/web local e então deixa as portas
8765/3100 livres, sem criar run. Esse smoke requer somente dependências locais do
projeto; `research`, LM Studio, TTS e ComfyUI podem aparecer como warnings no doctor.

- [ ] **Step 5: Commit dos scripts**

```powershell
git add scripts/studio-common.ps1 scripts/start-studio.ps1 scripts/stop-studio.ps1 tests/scripts .gitignore .env.example
git commit -m "feat: add local studio launcher scripts"
```

---

### Task 5: Substituir marcadores de integração por verificações reais e opt-in

**Files:**
- Delete: `tests/test_integration_executors.py`
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/conftest.py`
- Create: `tests/integration/test_services_real.py`
- Modify: `tests/test_integration_acervo.py`
- Modify: `pyproject.toml`
- Modify: `.env.example`

**Interfaces:**
- Consumes: `FORGE_RUN_INTEGRATION=1`, `Settings`, `Acervo`, `build_chat_model`, `AudioExecutor`, `ImageExecutor`, `ComposeExecutor`, `ValidationExecutor`, `Broker`.
- Produces: seis testes reais individuais, todos com diagnóstico de skip preciso quando o operador escolheu não disponibilizar uma dependência.
- Produces: marker documentado `integration: exige serviços externos e FORGE_RUN_INTEGRATION=1`.

- [ ] **Step 1: Escrever o gate comum e testes RED sem `pytest.skip` incondicional**

No `conftest.py`, implementar:

```python
def require_integration_opt_in() -> None:
    if os.getenv("FORGE_RUN_INTEGRATION") != "1":
        pytest.skip("defina FORGE_RUN_INTEGRATION=1 para habilitar integração real")


@pytest.fixture(autouse=True)
def integration_opt_in():
    require_integration_opt_in()
```

Cada teste chama um adaptador real e faz uma prova observável. Exemplos mínimos:

```python
@pytest.mark.integration
def test_research_returns_citable_passages(real_settings):
    passages = Acervo(real_settings.acervo_url, timeout=10).buscar(
        "livre-arbítrio e determinismo", top=3
    )
    assert passages
    assert all(item.path and item.book_title for item in passages)


@pytest.mark.integration
def test_lm_studio_returns_content(real_settings):
    response = build_chat_model(real_settings).invoke("Responda somente: FORGE_OK")
    assert getattr(response, "content", "").strip()
```

Nenhum desses testes pode ter `pytest.skip("...não disponível...")` como corpo.
Checagem de serviço ausente deve ocorrer antes da chamada e informar endpoint/path
exato no motivo de skip.

- [ ] **Step 2: Confirmar RED selecionando marker**

Run:

```powershell
$env:FORGE_RUN_INTEGRATION='1'
uv run pytest tests/integration tests/test_integration_acervo.py -m integration -q
```

Expected: FAIL até a implementação dos testes; em máquina sem serviço, os testes
implementados depois devem SKIP com motivo específico, nunca PASS fictício.

- [ ] **Step 3: Implementar as seis provas reais**

`test_services_real.py` contém exatamente estes cenários:

1. research: busca três passagens e valida `path`, `book_title`, `book_id`;
2. LM Studio: `GET /models` e uma inferência curta, preservando `content` separado
   de `reasoning_content` quando presente;
3. TTS: `AudioGenerateAdapter` sintetiza “O Forge verifica uma frase curta.” em
   `tmp_path/audio.wav`; `wave.open` confirma mono, 24000 Hz e `nframes > 0`;
4. ComfyUI: `ImageExecutor` gera uma imagem de um único beat sob `tmp_path`; Pillow
   confirma `1024x576`, e o teste registra o prompt/metadados no artefato;
5. FFmpeg: `ComposeExecutor` recebe WAV e PNG reais, produz MP4, e `ffprobe` prova
   H.264, AAC, 1920×1080 e duração positiva;
6. broker: um subprocesso filho mantém `montar_broker(settings).exclusivo("tts")`
   por 2 s após criar um arquivo ready; o processo-pai tenta
   `.exclusivo("imagem")` com timeout 0.2 e recebe `GPUOcupada`; após o filho sair,
   a claim de `imagem` passa. Usar o lock/estado de `tmp_path`, nunca `output/.gpu.lock`.

Todos os testes passam `Settings(_env_file=None, ...)` com DB/output/gaps sob
`tmp_path`. O TTS e Comfy só são elegíveis se os paths/endpoints reais do Settings
existirem/responderem. O teste FFmpeg não pode usar fixture textual em vez de
executar `ffmpeg`/`ffprobe`. O teste broker não encerra LM Studio, ComfyUI ou TTS
manualmente iniciados: ele usa liberadores no-op locais.

Remover o arquivo antigo de skips incondicionais. Atualizar o teste de acervo
existente para importar o fixture/gate novo ou mover seu conteúdo para
`test_services_real.py`; não manter dois testes que fazem a mesma busca.

- [ ] **Step 4: Confirmar comportamento offline e real**

Run:

```powershell
Remove-Item Env:FORGE_RUN_INTEGRATION -ErrorAction SilentlyContinue
uv run pytest -q
$env:FORGE_RUN_INTEGRATION='1'
uv run pytest tests/integration -m integration -ra
```

Expected: suíte padrão PASS sem rede/GPU. Na segunda execução, cada serviço
indisponível é SKIPPED com endpoint/path e ação; cada serviço disponível passa uma
chamada real. Nenhum teste fica verde sem chamada por causa de `skip` incondicional.

- [ ] **Step 5: Commit dos checks reais**

```powershell
git add tests/integration tests/test_integration_acervo.py pyproject.toml .env.example
git rm tests/test_integration_executors.py
git commit -m "test: add opt in studio integration checks"
```

---

### Task 6: Executar a run real completa e preservar evidência

**Files:**
- Create: `tests/integration/test_studio_e2e.py`
- Create: `tests/integration/support.py`
- Modify: `README.md`
- Create: `docs/2026-09-14-marco5-status.md`

**Interfaces:**
- Consumes: todos os serviços da tarefa 5, `build_worker`, `build_stage_executors`, `ControlPlaneService`, `StudioPreset`, API e catálogo de artefatos.
- Produces: um teste que prova `RunStatus.COMPLETED` somente com os oito gates aprovados e um MP4 real; documentação aponta para o diretório de evidências, sem segredos.

- [ ] **Step 1: Escrever teste RED ponta a ponta, inteiramente real**

```python
@pytest.mark.integration
def test_studio_completes_real_video(real_settings, tmp_path):
    require_studio_e2e_opt_in()
    settings = real_settings.model_copy(update={
        "studio_db_path": tmp_path / "forge.db",
        "studio_runs_dir": tmp_path / "runs",
        "output_dir": tmp_path / "roteiros",
        "gaps_file": tmp_path / "gaps.txt",
        "respostas_ruins_file": tmp_path / "bad.jsonl",
    })
    control = build_control_plane(settings)
    _, run = control.enqueue_video(
        tema="Por que a liberdade exige limites?",
        tese="", priority=50,
        config_snapshot=StudioPreset().model_dump(mode="json"),
        workflow_version=1, git_commit="integration",
    )
    worker = build_worker(settings, worker_id="integration-worker")

    for _ in range(32):
        worker.run_once()
        detail = control.get_run(run.id)
        if detail.run.status in {RunStatus.COMPLETED, RunStatus.FAILED}:
            break

    assert detail.run.status is RunStatus.COMPLETED
    assert all(stage.status is StageStatus.SUCCEEDED for stage in detail.stages)
    assert (settings.studio_runs_dir / run.id / "video" / "final.mp4").is_file()
```

- [ ] **Step 2: Confirmar RED**

Run:

```powershell
$env:FORGE_RUN_INTEGRATION='1'
$env:FORGE_RUN_STUDIO_E2E='1'
uv run pytest tests/integration/test_studio_e2e.py -m integration -q
```

Expected: FAIL enquanto não houver helpers que chequem pré-requisitos completos e
não houver assert de artefatos/gates suficientemente forte.

- [ ] **Step 3: Implementar isolamento, limites e asserts de produto**

`require_studio_e2e_opt_in()` exige simultaneamente as duas flags e chama o doctor
programaticamente. Se qualquer requisito faltar, fazer SKIP com uma lista única de
checks falhos, por exemplo `tts_model: configure FORGE_TTS_MODEL`; não começar run
parcial. Nunca reusar `data/forge.db`, `output/runs`, lock de GPU ou arquivos de
gaps de produção.

Após o loop, substituir os asserts genéricos pelos seguintes:

```python
assert detail.run.status is RunStatus.COMPLETED
assert [stage.stage for stage in detail.stages] == list(ETAPAS)
assert all(stage.status is StageStatus.SUCCEEDED for stage in detail.stages)
assert all(stage.gate_status for stage in detail.stages)

artifacts = {artifact.relative_path: artifact for artifact in detail.artifacts}
assert "video/midia.json" in artifacts
assert "video/final.mp4" in artifacts
assert "video/validation.json" in artifacts
assert all(artifact.is_current for artifact in artifacts.values())

report = json.loads((run_dir / "video" / "validation.json").read_text("utf-8"))
assert report["approved"] is True
assert not report["findings"]
probe = probe_media(str(run_dir / "video" / "final.mp4"))
assert (probe.codec, probe.audio_codec, probe.width, probe.height) == ("h264", "aac", 1920, 1080)
assert probe.duration and probe.duration > 0
```

Também consultar `GET /api/runs/{run_id}`, `GET /api/runs/{run_id}/artifacts` e um
Range `bytes=0-1023` em `/api/artifacts/{id}/content` via `TestClient(create_app(...))`;
provar que o dashboard/control plane pode observar a mesma run sem inferir o estado
do disco. Não iniciar Next.js no teste E2E; a composição web já é responsabilidade
do aceite M4.

O limite de 32 `run_once` é deliberado: oito stages mais no máximo 24 passos de
retry explícito. Ao esgotar, falhar com a lista de `stage/status/failure_code` para
diagnóstico, nunca fazer loop infinito.

- [ ] **Step 4: Executar e registrar evidência**

Run:

```powershell
$env:FORGE_RUN_INTEGRATION='1'
$env:FORGE_RUN_STUDIO_E2E='1'
uv run pytest tests/integration/test_studio_e2e.py -m integration -ra
```

Expected: PASS com uma run contendo roteiro, fontes, `video/midia.json`, 100% WAVs,
100% imagens obrigatórias, `video/final.mp4` 1080p H.264/AAC e
`video/validation.json` aprovado. Se falhar, preservar `tmp_path` quando
`FORGE_KEEP_INTEGRATION_OUTPUT=1`; do contrário pytest limpa apenas seu diretório
temporário, sem apagar produção.

Preencher `docs/2026-09-14-marco5-status.md` com data, commit, versões de Python,
Node, FFmpeg, modelo LM Studio, contagens de áudio/imagens, duração MP4, caminho
relativo da evidência preservada quando houver, e checks indisponíveis. Não incluir
tokens, API keys, paths de credencial ou output bruto do modelo.

- [ ] **Step 5: Commit do E2E e evidência**

```powershell
git add tests/integration/test_studio_e2e.py tests/integration/support.py README.md docs/2026-09-14-marco5-status.md
git commit -m "test: verify complete studio video run"
```

---

### Task 7: Documentar operação e rodar regressão de release

**Files:**
- Modify: `README.md`
- Modify: `.env.example`
- Modify: `docs/2026-09-14-marco5-status.md`

**Interfaces:**
- Consumes: comandos entregues nas tarefas 1–6 e resultados reais da máquina.
- Produces: runbook curto, reproduzível, sem segredos, para iniciar/parar/importar/testar o Studio.

- [ ] **Step 1: Escrever testes/documentação verificáveis antes da edição**

Adicionar em teste Python de documentação ou no teste de scripts asserts que o README
contém exatamente as chamadas abaixo e que cada path existe:

```python
for command in (
    ".\\scripts\\start-studio.ps1",
    ".\\scripts\\stop-studio.ps1",
    "uv run forge-studio-doctor --migrate",
    "uv run forge-import-runs",
    "FORGE_RUN_INTEGRATION=1",
    "FORGE_RUN_STUDIO_E2E=1",
):
    assert command in Path("README.md").read_text(encoding="utf-8")
```

- [ ] **Step 2: Confirmar RED**

Run:

```powershell
uv run pytest tests -k documentation -q
```

Expected: FAIL até a seção operacional existir; se não houver suite de docs, criar
`tests/test_documentation.py` com o snippet acima em vez de depender de `-k` vazio.

- [ ] **Step 3: Atualizar runbook e limites**

No README, adicionar seções curtas e exatas:

```powershell
# verifica máquina e aplica migração SQLite
uv run forge-studio-doctor --migrate

# inicia API, worker e web; abre o dashboard
.\scripts\start-studio.ps1

# encerra, solicitando pausa antes de matar processos restantes
.\scripts\stop-studio.ps1 -GraceSeconds 30

# importa apenas histórico; a origem é preservada
uv run forge-import-runs C:\caminho\output\runs --children
```

Documentar `-NoBrowser`, `-WebMode production`, `-Force`, arquivo de PIDs/logs e
que doctor não inicia Docker. Explicar separadamente os dois comandos de integração,
as flags exigidas e que a suíte padrão não toca rede/GPU. Declarar que runs legadas
são cópias somente-leitura e que importação não atesta gates de qualidade antigos.
Atualizar `.env.example` para coincidir precisamente com os nomes em `Settings`.

- [ ] **Step 4: Rodar release gates finais**

Run:

```powershell
uv run pytest -q
uv run python -m compileall -q src/forge
npm test --prefix web
npm run lint --prefix web
npm run build --prefix web
git diff --check
rg -n '_pipeline-poc|C:\\dev\\_pipeline-poc' src tests web scripts docs
```

Expected: todos os comandos saem 0; integrations continuam excluídas no primeiro
pytest. Depois, em máquina preparada, rodar Tasks 5 e 6 e anexar seus resultados ao
status Marco 5.

- [ ] **Step 5: Commit de documentação/release**

```powershell
git add README.md .env.example docs/2026-09-14-marco5-status.md tests/test_documentation.py
git commit -m "docs: document studio local operation"
```

## Self-Review

### Spec coverage

- Launcher/stop, validação de Python/Node/FFmpeg/caminhos, API/worker/web, browser,
  PIDs fora de runs e Docker não automático: Tasks 2 and 4.
- Importador de runs antigas como histórico somente leitura: Tasks 1 and 3.
- Testes reais research, LM Studio, WAV, ComfyUI, MP4 e broker: Task 5.
- Run real com roteiro, fontes, áudio/imagens completos, MP4 e validação: Task 6.
- Persistência WAL/migração idempotente, sem apagar banco/artefatos, segredo
  mascarado, paths canônicos e sem POC runtime: Constraints and Tasks 1–7.
- Aceites de continuidade/restart, SSE, preview, fila e dashboard: Task 0 exige-os
  no Marco 4 antes de qualquer trabalho de integração; eles não são reimplementados
  em Marco 5.

### Placeholder scan

Nenhuma tarefa usa TBD/TODO, “tratamento apropriado”, “testar o acima” ou
“semelhante à tarefa anterior”. Os paths, interfaces, comandos, flags, outputs e
critérios de skip/falha foram definidos neste documento.

### Type consistency

- Banco v2 e `Run.is_read_only` são criados na Task 1 antes do importador/API da
  Task 3.
- `forge-studio-doctor`, `forge-worker` e `FORGE_STUDIO_WORKER_POLL_SECONDS` são
  criados na Task 2 antes de os scripts da Task 4 os consumirem.
- `LegacyRunImporter.import_one()` produz `ImportedRun` e usa run roots UUID antes
  de preview/API tentar resolver `output/runs/<run-id>`.
- `FORGE_RUN_INTEGRATION` controla todos os checks reais; o E2E adiciona, sem
  substituir, `FORGE_RUN_STUDIO_E2E`.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-13-forge-studio-integracao.md`. Two execution options:

1. **Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
