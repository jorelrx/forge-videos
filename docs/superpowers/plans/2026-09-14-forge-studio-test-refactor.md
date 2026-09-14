# Forge Studio M1–M4 Test Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Substituir testes RED, fixtures divergentes e streams infinitos por testes determinísticos de comportamento que provem os critérios M1–M4 sem rede, GPU ou diretórios reais.

**Architecture:** `tests/api/conftest.py` passa a montar o mesmo `ApiServices` usado pelo runtime, sobre SQLite e diretório de runs temporários. Testes HTTP cobrem apenas borda HTTP; estado e SSE são produzidos por serviços e repositórios reais. O endpoint de saúde/configuração recebe dependências injetadas e expõe somente uma visão allowlisted, sem serializar `Settings`.

**Tech Stack:** Python 3.13, pytest, FastAPI TestClient, SQLite temporário, Pydantic 2.

---

### Task 1: Consolidar fixture API e helpers de cenário

**Files:**
- Modify: `tests/api/conftest.py`
- Modify: `tests/api/test_runs.py`
- Modify: `tests/api/test_artifacts.py`
- Test: `tests/api/test_runs.py`

- [ ] **Step 1: Montar o ambiente somente em `tmp_path` com os contratos reais**

```python
@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        studio_db_path=tmp_path / "forge.db",
        studio_runs_dir=tmp_path / "runs",
    )

@pytest.fixture
def services(settings: Settings) -> ApiServices:
    db = Database(settings.studio_db_path)
    init_db(db)
    return ApiServices(
        settings=settings,
        commands=ControlPlaneService(db),
        queries=StudioQueryService(db),
        health=StudioHealthService(probes=fake_health_probes()),
        git_commit="test-sha",
    )
```

- [ ] **Step 2: Fornecer uma única fixture para criação de run e uma para artefato catalogado**

```python
@pytest.fixture
def create_video(client: TestClient):
    def _create(*, tema: str = "Tema", priority: int = 50) -> dict:
        response = client.post("/api/videos", json={"tema": tema, "priority": priority})
        assert response.status_code == 201, response.text
        return response.json()
    return _create
```

A fixture de artefato deve criar o arquivo sob `settings.studio_runs_dir / run_id`, usar o `StageRun` atual e `OperacaoRepository.register_artifact(Artifact(...))`; não inserir SQL de schema dentro do teste.

- [ ] **Step 3: Remover helpers locais duplicados e imports não usados dos testes API**

`test_runs.py`, `test_artifacts.py`, `test_events.py` e `test_acceptance.py` usam `create_video` e `register_artifact` da fixture. Nenhum teste instancia `Settings()` sem `tmp_path`.

- [ ] **Step 4: Executar o recorte de fixture**

Run: `uv run pytest tests/api/test_runs.py tests/api/test_artifacts.py -q`

Expected: todos os testes passam sem gravar em `output/runs` nem `data/forge.db`.

### Task 2: Reescrever aceite backend como cenário único persistente

**Files:**
- Modify: `tests/api/test_acceptance.py`
- Test: `tests/api/test_acceptance.py`

- [ ] **Step 1: Substituir os cinco testes fragmentados por uma prova de continuidade ponta a ponta**

```python
def test_api_restart_preserves_queue_command_events_and_preview(
    api_factory, services, create_video, register_artifact,
):
    first = TestClient(api_factory(services))
    created = [
        create_video(tema=tema, priority=priority)
        for tema, priority in [("A", 10), ("B", 90), ("C", 50)]
    ]
    assert [item["video"]["tema"] for item in first.get("/api/queue").json()] == ["B", "C", "A"]
    run_id = created[1]["run"]["id"]
    command = first.post(f"/api/runs/{run_id}/pause", headers={"Idempotency-Key": "pause-1"})
    assert command.status_code == 200
    assert first.post(f"/api/runs/{run_id}/pause", headers={"Idempotency-Key": "pause-1"}).json()["id"] == command.json()["id"]
    artifact = register_artifact(run_id, content=b"0123456789", mime_type="audio/wav")
    restarted = TestClient(api_factory(services))
    assert restarted.get(f"/api/runs/{run_id}").status_code == 200
    assert restarted.get(f"/api/artifacts/{artifact.id}/content", headers={"Range": "bytes=4-7"}).content == b"4567"
```

- [ ] **Step 2: Executar RED por motivo comportamental**

Run: `uv run pytest tests/api/test_acceptance.py -q`

Expected: falha somente se fila, persistência, idempotência ou preview não obedecerem ao cenário; nunca por tupla usada como ID, fixture diferente ou `NameError`.

- [ ] **Step 3: Corrigir somente implementação que o cenário provar ausente**

O teste deve usar `run_id = created[n]["run"]["id"]`; não aceitar a tupla retornada por helper antigo como ID. Não inserir dados em tabelas por SQL cru.

- [ ] **Step 4: Executar GREEN**

Run: `uv run pytest tests/api/test_acceptance.py -q`

Expected: 1 passed.

### Task 3: Tornar SSE finito e verificável

**Files:**
- Modify: `tests/api/test_sse.py`
- Modify: `tests/api/test_events.py`
- Test: `tests/api/test_sse.py`
- Test: `tests/api/test_events.py`

- [ ] **Step 1: Testar `iter_sse_events` com eventos persistidos e cursor explícito**

```python
def test_sse_replays_only_events_after_cursor(services, create_video):
    run_id = create_video(tema="SSE")["run"]["id"]
    existing = services.queries.events_after(0, run_id=run_id)
    stream = iter_sse_events(
        services.queries,
        cursor=existing[0].id - 1,
        run_id=run_id,
        poll_seconds=0.01,
        keepalive_seconds=0.02,
        sleep=lambda _: None,
    )
    event = next(stream)
    assert event.id == str(existing[0].id)
    assert event.data["kind"] == "run.queued"
```

- [ ] **Step 2: Testar keep-alive com consulta vazia e ciclo finito controlado**

```python
class EmptyQueries:
    def events_after(self, *_args, **_kwargs):
        return []

stream = iter_sse_events(EmptyQueries(), cursor=0, run_id=None,
                         poll_seconds=0.01, keepalive_seconds=0.01,
                         sleep=lambda _: None)
assert next(stream).comment == "keep-alive"
```

- [ ] **Step 3: Não consumir endpoint SSE infinito por `TestClient.get()`**

O contrato HTTP é verificado chamando a função de rota com `Request` mínimo ou testando `_encode_event`; a resposta deve declarar `text/event-stream`, `Cache-Control: no-cache` e o evento deve ser serializado em linhas `id:`, `retry:` e `data:`. Não chamar `b"".join()` sobre resposta SSE aberta.

- [ ] **Step 4: Executar GREEN**

Run: `uv run pytest tests/api/test_sse.py tests/api/test_events.py -q`

Expected: PASS sem timeout.

### Task 4: Implementar e provar saúde/configuração reais sem segredos

**Files:**
- Modify: `src/forge/services/saude.py`
- Modify: `src/forge/api/app.py`
- Modify: `src/forge/api/routes/system.py`
- Modify: `src/forge/api/contracts.py`
- Modify: `tests/api/test_system.py`
- Modify: `tests/services/test_saude.py`
- Test: `tests/api/test_system.py`

- [ ] **Step 1: Reescrever os três `assert False` como contratos HTTP executáveis**

```python
def test_services_exposes_injected_required_dependencies(client):
    response = client.get("/api/services")
    assert response.status_code == 200
    body = response.json()
    assert {item["name"] for item in body["items"]} == REQUIRED_SERVICES
    assert next(item for item in body["items"] if item["name"] == "comfyui")["state"] == "unavailable"


def test_effective_config_is_allowlisted_and_redacts_credentials(client):
    body = client.get("/api/config/effective").json()
    serialized = json.dumps(body)
    assert body["api"] == {"host": "127.0.0.1", "port": 8765}
    assert "real-secret" not in serialized
    assert "api_key" not in serialized
```

- [ ] **Step 2: Executar RED**

Run: `uv run pytest tests/api/test_system.py tests/services/test_saude.py -q`

Expected: falhas de rota ausente/stub ou contrato, nunca `assert False` deliberado.

- [ ] **Step 3: Injetar `StudioHealthService` em `ApiServices` e registrar o router uma vez**

```python
@dataclass(frozen=True)
class ApiServices:
    settings: Settings
    commands: ControlPlaneService
    queries: StudioQueryService
    health: StudioHealthService
    git_commit: str
    workflow_version: int = 1

app.include_router(system.system_router, prefix="/api")
```

- [ ] **Step 4: Retornar config allowlisted e saúde serializável**

```python
@system_router.get("/services")
def list_services(request: Request) -> ServiceHealthPage:
    items = request.app.state.services.health.check_all().values()
    return ServiceHealthPage(items=list(items))

@system_router.get("/config/effective")
def effective_config(request: Request) -> EffectiveConfig:
    settings = request.app.state.services.settings
    return EffectiveConfig(
        api={"host": "127.0.0.1", "port": settings.studio_api_port},
        worker={"lease_seconds": settings.worker_lease_seconds,
                "heartbeat_seconds": settings.worker_heartbeat_seconds},
        services={"research_url": settings.acervo_url,
                  "lm_studio_url": settings.lm_studio_base_url,
                  "comfyui_url": settings.comfy_url},
    )
```

Não serializar `settings.model_dump()`. Defaults de probe recebem `Settings` explicitamente; GPU lê o estado configurado pelo broker, não arquivos temporários globais.

- [ ] **Step 5: Executar GREEN**

Run: `uv run pytest tests/api/test_system.py tests/services/test_saude.py -q`

Expected: PASS, sem rede real porque as probes são injetadas na fixture.

### Task 5: Remover testes artificiais e executar a regressão M1–M4

**Files:**
- Modify: `tests/test_artifacts.py`
- Modify: `tests/api/test_artifacts.py`
- Modify: `docs/2026-09-13-marco4-status.md`
- Test: `tests/`

- [ ] **Step 1: Substituir `try/except + assert False` por `pytest.raises`**

```python
def test_range_invalid_size_raises():
    with pytest.raises(RangeNotSatisfiable):
        parse_range("bytes=0-", 0)
```

Manter uma única fonte de teste de Range em `tests/api/test_ranges.py`; apagar a duplicata de `tests/test_artifacts.py` quando não cobrir comportamento adicional.

- [ ] **Step 2: Corrigir o teste de rota que nunca alcança o handler**

A URL percent-encoded com barra é resolvida pelo roteador antes de `artifact_content`; a prova é `404` e conteúdo ausente. A validação interna de ID, se extraída, recebe teste unitário separado para retorno 400.

- [ ] **Step 3: Confirmar ausência de sentinelas RED no backend**

Run: `rg -n "assert False|RED —|falha esperada" tests -g "*.py"`

Expected: apenas usos legítimos dentro de branches de controle devem ser eliminados; resultado vazio para `tests/api` e `tests/test_artifacts.py`.

- [ ] **Step 4: Rodar regressões e estáticos**

Run:

```bash
uv run pytest tests/api -q
uv run pytest -q
uv run python -m compileall -q src/forge
git diff --check
```

Expected: saída 0; nenhuma execução abre rede, GPU ou diretório fora de `tmp_path`.

- [ ] **Step 5: Atualizar o status somente com evidência fresca**

Registrar contagem e comandos que passarem em `docs/2026-09-13-marco4-status.md`. Não declarar o gate pronto enquanto os gates Python e web ainda falharem.
