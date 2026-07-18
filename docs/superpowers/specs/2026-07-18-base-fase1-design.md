# Base Fase 1 — Design

> Data: 2026-07-18
> Escopo: fundação horizontal do forge-videos (core + config + registry + tooling).

## 1. Objetivo

Estabelecer a base mínima do projeto antes de qualquer feature: gerenciamento de
ambiente/dependências, configuração, logging estruturado, interfaces base (Plugin,
Skill) e um registry tipado. Nenhuma feature de produto é implementada nesta fase.

## 2. Stack

- Python 3.12+
- uv (ambiente virtual, resolução de deps, lockfile)
- Pydantic v2 (`pydantic-settings` para configuração)
- structlog (logging estruturado)
- pytest (testes)

## 3. Ambiente e Tooling

- Ambiente virtual gerenciado por uv (`.venv/` na raiz, gitignored).
- `pyproject.toml` como fonte única de metadados e dependências.
- `uv.lock` versionado para builds reprodutíveis.
- `.env` para segredos locais (gitignored). `.env.example` versionado como template.
- `.gitignore` atualizado: `.venv/`, `.env`, caches (`__pycache__/`, `.pytest_cache/`).

## 4. Layout

```text
forge-videos/
├── pyproject.toml          # uv-managed, deps + config de ferramentas
├── uv.lock                 # lockfile versionado
├── .env                    # segredos locais (gitignored)
├── .env.example            # template versionado
├── src/forge/
│   ├── __init__.py
│   ├── config.py           # Settings (pydantic-settings, lê .env)
│   ├── logging.py          # setup_logging() structlog
│   ├── core/
│   │   ├── __init__.py
│   │   ├── plugin.py       # Plugin ABC: initialize()
│   │   ├── skill.py        # Skill ABC: execute(context)
│   │   └── registry.py     # Registry[T] genérico + instâncias
│   └── py.typed
└── tests/
    ├── test_config.py
    ├── test_registry.py
    └── test_logging.py
```

Decisão: usar src-layout com pacote `src/forge/` em vez de subpastas soltas em
`src/` (como no planning original). Motivo: pacote importável de nome estável,
testável, evita ambiguidade de path e conflito com o diretório de trabalho.

## 5. Componentes

### 5.1 config.py

- `class Settings(BaseSettings)` (pydantic-settings).
- Campos iniciais (todos com default seguro ou opcional):
  - `llm_api_key: str | None`
  - `llm_base_url: str | None`
  - `data_dir: Path` (default `./data`)
  - `log_level: str` (default `"INFO"`)
- `model_config = SettingsConfigDict(env_file=".env", env_prefix="FORGE_", extra="ignore")`.
- `get_settings() -> Settings` cacheada (`functools.lru_cache`) — instância única.

### 5.2 logging.py

- `setup_logging(level: str = "INFO") -> None` configura structlog.
- Saída console legível em dev; processadores incluem timestamp, nível, logger.
- Idempotente: chamar duas vezes não duplica handlers.
- Helper `get_logger(name)` retornando logger structlog.

### 5.3 core/plugin.py

- `class Plugin(ABC)` com método abstrato `initialize(self) -> None`.
- Base para integrações externas futuras (YouTube, FFmpeg, Whisper, ComfyUI...).
- Tipagem completa, docstring de contrato.

### 5.4 core/skill.py

- `class Skill(ABC)` com método abstrato `execute(self, context: dict) -> Any`.
- Base para conhecimento reutilizável.
- Tipagem completa, docstring de contrato.

### 5.5 core/registry.py

- `class Registry(Generic[T])`:
  - `register(name: str, obj: T) -> None` — erro (`ValueError`) se nome duplicado.
  - `get(name: str) -> T` — erro (`KeyError`) claro se ausente.
  - `all() -> dict[str, T]` — cópia do mapa nome→objeto.
  - `__contains__`, `__len__` para ergonomia.
- Instâncias exportadas: `plugin_registry: Registry[Plugin]`,
  `skill_registry: Registry[Skill]`.

## 6. Testes

- `test_config.py`: lê `.env` de teste (via monkeypatch/env), defaults corretos,
  `get_settings` cacheia mesma instância.
- `test_registry.py`: register/get feliz, duplicado levanta, ausente levanta,
  `all()` retorna cópia, `__contains__`/`__len__`.
- `test_logging.py`: `setup_logging` não quebra, idempotente, `get_logger` retorna
  logger utilizável.

## 7. Fora de Escopo

LangGraph, orquestração, agentes, memória, RAG, API, observabilidade avançada, e
qualquer plugin/skill concreto. Ficam para fases seguintes do roadmap.

## 8. Critério de Pronto

- `uv sync` cria `.venv` e instala deps sem erro.
- `uv run pytest` passa todos os testes.
- `import forge`, `from forge.core.registry import plugin_registry` funcionam.
- `.env.example` documenta todas as variáveis suportadas.
