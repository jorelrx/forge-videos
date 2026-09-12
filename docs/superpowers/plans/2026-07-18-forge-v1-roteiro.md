# Forge V1 — Gerador de Roteiro — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task and use caveman. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CLI `forge roteiro` que gera um roteiro de vídeo (9 seções, PT-BR) via pipeline LangGraph e grava em Markdown.

**Architecture:** Duas features. `writer` = funções puras de produção textual sobre um `BaseChatModel` (LangChain), sem LangGraph. `orchestrator` = grafo LangGraph que adapta cada estágio como nó, sequencia `tema→research→plan→write→review` e gerencia o loop de review com disjuntor. `output.storage` grava o resultado.

**Tech Stack:** Python 3.12+, uv, LangGraph, LangChain (`langchain-core`, `langchain-anthropic`), Pydantic v2 + pydantic-settings, structlog, pytest.

## Global Constraints

- Python 3.12+ ; ambiente/deps por uv ; `uv.lock` versionado.
- Pacote importável: `forge` (distribuição `forge-videos`), src-layout em `src/forge/`.
- Modelo LLM padrão: `claude-opus-4-8`. Adaptive thinking. `effort` default `high`.
- **Tools e structured output nunca na mesma chamada.** `research` usa `web_search` (tools). Extração de fontes, plan, write, review usam `with_structured_output` (sem tools). Mitiga incompatibilidade `ChatAnthropic` (risco §10 do spec).
- Nove seções, ordem fixa: Hook, Problema, História, Explicação, Filósofo, Psicologia, Aplicação, Resumo, Conclusão.
- Dependência de sentido único: `orchestrator` → `writer`. `writer` nunca importa LangGraph.
- Regra de citação (research): padrão zero aspas; aspa só com frase + autor + obra confirmados por busca. Fonte a copiar: `.pi/skills/ensaio-filosofico/SKILL.md` seção "Regra de citação".
- Testes unitários sem rede (model falso injetado). Commits frequentes.

---

## File Structure

```text
src/forge/
├── __init__.py
├── config.py
├── logging.py
├── cli.py
├── llm/{__init__.py, model.py}
├── writer/
│   ├── __init__.py
│   ├── models.py
│   ├── _prompts.py
│   ├── tema.py, research.py, plan.py, write.py, review.py
│   └── prompts/{tema,research,fontes,plan,write,review}.md
├── orchestrator/{__init__.py, state.py, graph.py}
├── output/{__init__.py, storage.py}
└── py.typed
tests/
├── conftest.py
├── test_config.py
├── writer/{test_tema,test_research,test_plan,test_write,test_review}.py
├── orchestrator/test_graph.py
├── test_storage.py
└── test_integration.py
```

---

### Task 1: Scaffolding uv + esqueleto do pacote

**Files:**
- Create: `pyproject.toml`, `.env.example`, `src/forge/__init__.py`, `src/forge/py.typed`, `src/forge/llm/__init__.py`, `src/forge/writer/__init__.py`, `src/forge/orchestrator/__init__.py`, `src/forge/output/__init__.py`
- Modify: `.gitignore`
- Test: `tests/test_smoke.py`

**Interfaces:**
- Produces: pacote importável `forge`; `forge.__version__: str`.

- [ ] **Step 1: Write the failing test**

`tests/test_smoke.py`:
```python
def test_import_forge():
    import forge
    assert isinstance(forge.__version__, str)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_smoke.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'forge'`).

- [ ] **Step 3: Create pyproject.toml**

`pyproject.toml`:
```toml
[project]
name = "forge-videos"
version = "0.1.0"
description = "CreatorBrain — gerador de roteiro de vídeo"
requires-python = ">=3.12"
dependencies = [
    "langgraph>=0.2",
    "langchain-core>=0.3",
    "langchain-anthropic>=0.3",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "structlog>=24.1",
]

[project.scripts]
forge = "forge.cli:main"

[dependency-groups]
dev = ["pytest>=8"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/forge"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 4: Create package skeleton**

`src/forge/__init__.py`:
```python
__version__ = "0.1.0"
```

Create empty files: `src/forge/py.typed`, `src/forge/llm/__init__.py`, `src/forge/writer/__init__.py`, `src/forge/orchestrator/__init__.py`, `src/forge/output/__init__.py`.

`.env.example`:
```dotenv
# API key Anthropic (ou use ANTHROPIC_API_KEY)
FORGE_ANTHROPIC_API_KEY=
# Overrides opcionais:
# FORGE_MODEL=claude-opus-4-8
# FORGE_EFFORT=high
# FORGE_OUTPUT_DIR=output/roteiros
# FORGE_LOG_LEVEL=INFO
# FORGE_MAX_REVIEW_ROUNDS=8
```

Append to `.gitignore`:
```gitignore
.venv
.env
__pycache__/
.pytest_cache/
output/
```

- [ ] **Step 5: Sync and run test**

Run: `uv sync && uv run pytest tests/test_smoke.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock .env.example .gitignore src/forge tests/test_smoke.py
git commit -m "feat: scaffold forge package with uv and deps"
```

---

### Task 2: config.py — Settings

**Files:**
- Create: `src/forge/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings` (pydantic-settings) com campos `anthropic_api_key: str | None`, `model: str`, `effort: str`, `output_dir: Path`, `log_level: str`, `max_review_rounds: int`; `get_settings() -> Settings` (cacheada).

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:
```python
from pathlib import Path
from forge.config import Settings, get_settings

def test_defaults():
    s = Settings(_env_file=None)
    assert s.model == "claude-opus-4-8"
    assert s.effort == "high"
    assert s.max_review_rounds == 8
    assert s.output_dir == Path("output/roteiros")

def test_env_prefix(monkeypatch):
    monkeypatch.setenv("FORGE_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("FORGE_MAX_REVIEW_ROUNDS", "3")
    s = Settings(_env_file=None)
    assert s.model == "claude-sonnet-5"
    assert s.max_review_rounds == 3

def test_api_key_fallback(monkeypatch):
    monkeypatch.delenv("FORGE_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    s = Settings(_env_file=None)
    assert s.anthropic_api_key == "sk-test"

def test_get_settings_cached():
    assert get_settings() is get_settings()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL (`ModuleNotFoundError` / `forge.config`).

- [ ] **Step 3: Write minimal implementation**

`src/forge/config.py`:
```python
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FORGE_", env_file=".env", extra="ignore"
    )

    anthropic_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("FORGE_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
    )
    model: str = "claude-opus-4-8"
    effort: str = "high"
    output_dir: Path = Path("output/roteiros")
    log_level: str = "INFO"
    max_review_rounds: int = 8


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/forge/config.py tests/test_config.py
git commit -m "feat: add Settings config"
```

---

### Task 3: logging.py — structlog

**Files:**
- Create: `src/forge/logging.py`
- Test: `tests/test_logging.py`

**Interfaces:**
- Produces: `setup_logging(level: str = "INFO") -> None` (idempotente); `get_logger(name: str)`.

- [ ] **Step 1: Write the failing test**

`tests/test_logging.py`:
```python
from forge.logging import setup_logging, get_logger

def test_setup_idempotent_and_logger_usable():
    setup_logging("INFO")
    setup_logging("INFO")  # segunda chamada não quebra
    log = get_logger("test")
    log.info("ok", campo=1)  # não levanta
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_logging.py -v`
Expected: FAIL (`forge.logging` inexistente).

- [ ] **Step 3: Write minimal implementation**

`src/forge/logging.py`:
```python
import logging

import structlog

_CONFIGURED = False


def setup_logging(level: str = "INFO") -> None:
    global _CONFIGURED
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO))
    if _CONFIGURED:
        return
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )
    _CONFIGURED = True


def get_logger(name: str):
    return structlog.get_logger(name)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_logging.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/forge/logging.py tests/test_logging.py
git commit -m "feat: add structlog setup"
```

---

### Task 4: writer/models.py — modelos de domínio

**Files:**
- Create: `src/forge/writer/models.py`
- Test: `tests/writer/test_models.py`, `tests/writer/__init__.py`

**Interfaces:**
- Produces: `Fonte`, `Secao`, `Roteiro`, `Nota`, `ReviewResult`, `FonteList`, `Plano`, `RoteiroDraft` (pydantic v2); `SECOES_NOMES: list[str]` (as nove partes, em ordem).

- [ ] **Step 1: Write the failing test**

`tests/writer/__init__.py`: (arquivo vazio)

`tests/writer/test_models.py`:
```python
from forge.writer.models import (
    Fonte, Secao, Roteiro, Nota, ReviewResult, SECOES_NOMES,
)

def test_secoes_nomes_ordem():
    assert SECOES_NOMES == [
        "Hook", "Problema", "História", "Explicação", "Filósofo",
        "Psicologia", "Aplicação", "Resumo", "Conclusão",
    ]

def test_roteiro_defaults():
    r = Roteiro(tema="T", tese="Te", secoes=[Secao(nome="Hook", conteudo="c")])
    assert r.fontes == []
    assert r.secoes[0].nome == "Hook"

def test_review_result():
    rr = ReviewResult(aprovado=False, notas=[Nota(dimensao="clareza", problema="p", sugestao="s")])
    assert rr.aprovado is False
    assert rr.notas[0].dimensao == "clareza"

def test_fonte_optional_fields():
    f = Fonte(titulo="Livro")
    assert f.autor is None and f.frase is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/writer/test_models.py -v`
Expected: FAIL (`forge.writer.models` inexistente).

- [ ] **Step 3: Write minimal implementation**

`src/forge/writer/models.py`:
```python
from pydantic import BaseModel, Field

SECOES_NOMES: list[str] = [
    "Hook", "Problema", "História", "Explicação", "Filósofo",
    "Psicologia", "Aplicação", "Resumo", "Conclusão",
]


class Fonte(BaseModel):
    titulo: str
    autor: str | None = None
    url: str | None = None
    frase: str | None = None


class Secao(BaseModel):
    nome: str
    conteudo: str


class Roteiro(BaseModel):
    tema: str
    tese: str
    secoes: list[Secao]
    fontes: list[Fonte] = Field(default_factory=list)


class Nota(BaseModel):
    dimensao: str
    problema: str
    sugestao: str


class ReviewResult(BaseModel):
    aprovado: bool
    notas: list[Nota] = Field(default_factory=list)


class FonteList(BaseModel):
    fontes: list[Fonte] = Field(default_factory=list)


class Plano(BaseModel):
    tese: str
    esboco: str


class RoteiroDraft(BaseModel):
    secoes: list[Secao]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/writer/test_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/forge/writer/models.py tests/writer/__init__.py tests/writer/test_models.py
git commit -m "feat: add writer domain models"
```

---

### Task 5: llm/model.py — fábrica do chat model

**Files:**
- Create: `src/forge/llm/model.py`
- Test: `tests/test_llm_model.py`

**Interfaces:**
- Consumes: `Settings` (Task 2).
- Produces: `build_chat_model(settings: Settings) -> BaseChatModel`.

Nota de implementação: `thinking`/`effort` podem exigir ajuste conforme a versão do `langchain-anthropic`. Se `ChatAnthropic(...)` rejeitar `thinking=` ou o `effort`, mover para `model_kwargs`. O teste só checa o id do modelo, então essa afinação não bloqueia a task.

- [ ] **Step 1: Write the failing test**

`tests/test_llm_model.py`:
```python
from langchain_core.language_models import BaseChatModel
from forge.config import Settings
from forge.llm.model import build_chat_model

def test_builds_chat_model():
    s = Settings(_env_file=None, anthropic_api_key="sk-test")
    m = build_chat_model(s)
    assert isinstance(m, BaseChatModel)
    assert s.model in m.model
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_llm_model.py -v`
Expected: FAIL (`forge.llm.model` inexistente).

- [ ] **Step 3: Write minimal implementation**

`src/forge/llm/model.py`:
```python
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel

from forge.config import Settings


def build_chat_model(settings: Settings) -> BaseChatModel:
    return ChatAnthropic(
        model=settings.model,
        api_key=settings.anthropic_api_key,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        model_kwargs={"output_config": {"effort": settings.effort}},
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_llm_model.py -v`
Expected: PASS. (Se falhar por `thinking`/`model_kwargs`, aplicar a nota de implementação acima e reexecutar.)

- [ ] **Step 5: Commit**

```bash
git add src/forge/llm/model.py tests/test_llm_model.py
git commit -m "feat: add chat model factory"
```

---

### Task 6: writer/_prompts.py + arquivos de prompt

**Files:**
- Create: `src/forge/writer/_prompts.py`, `src/forge/writer/prompts/tema.md`, `.../research.md`, `.../fontes.md`, `.../plan.md`, `.../write.md`, `.../review.md`
- Test: `tests/writer/test_prompts.py`

**Interfaces:**
- Produces: `load_prompt(name: str) -> str` (lê `src/forge/writer/prompts/{name}.md` empacotado).

- [ ] **Step 1: Write the failing test**

`tests/writer/test_prompts.py`:
```python
import pytest
from forge.writer._prompts import load_prompt

@pytest.mark.parametrize("name", ["tema", "research", "fontes", "plan", "write", "review"])
def test_load_prompt(name):
    text = load_prompt(name)
    assert isinstance(text, str) and text.strip()

def test_research_prompt_tem_placeholder_tema():
    assert "{tema}" in load_prompt("research")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/writer/test_prompts.py -v`
Expected: FAIL (`forge.writer._prompts` inexistente).

- [ ] **Step 3: Write loader + prompts**

`src/forge/writer/_prompts.py`:
```python
from importlib.resources import files


def load_prompt(name: str) -> str:
    return (files("forge.writer") / "prompts" / f"{name}.md").read_text(encoding="utf-8")
```

`src/forge/writer/prompts/tema.md`:
```markdown
Gere um único tema para um vídeo no nicho de filosofia, desenvolvimento pessoal
e psicologia. O tema deve permitir uma tese discutível — alguém razoável precisa
poder discordar. Responda só com o tema, uma frase, sem aspas nem preâmbulo.
```

`src/forge/writer/prompts/research.md`:
```markdown
Pesquise na web material sólido para um roteiro sobre: {tema}

Confirme fatos, escolas e ideias em fontes primárias. Use a ferramenta de busca.

Regra de citação (dura):
- Padrão é ZERO aspas. Um roteiro forte sem nenhuma citação literal é o normal.
- Só use aspas se frase + autor + obra estiverem confirmados por busca nesta
  sessão. Site de coletânea de frases não confirma nada.
- Ideias amplamente conhecidas (dicotomia do controle estoica, má-fé sartriana,
  eterno retorno) dispensam busca — explique e atribua sem aspas.
- Na dúvida, parafraseie e nomeie o autor, sem aspas.

Produza notas de pesquisa densas: ideias-chave, filósofos e escolas relevantes,
exemplos concretos e, quando confirmadas, referências com autor e obra.
```

`src/forge/writer/prompts/fontes.md`:
```markdown
Extraia as fontes citáveis destas notas de pesquisa. Inclua apenas fontes com
título e autor identificáveis. Não invente. Se as notas não trazem fontes
confirmadas, retorne lista vazia.

Notas:
{notes}
```

`src/forge/writer/prompts/plan.md`:
```markdown
Tema: {tema}

Notas de pesquisa:
{research}

Produza:
1. tese — uma afirmação discutível sobre o tema (não é paráfrase do tema).
2. esboco — como cada uma das nove partes do roteiro (Hook, Problema, História,
   Explicação, Filósofo, Psicologia, Aplicação, Resumo, Conclusão) avança a tese.
   Cada movimento precisa empurrar a tese adiante; nada apenas reformula o anterior.
```

`src/forge/writer/prompts/write.md`:
```markdown
Escreva o roteiro completo de um vídeo em PT-BR, com exatamente nove seções,
nesta ordem: Hook, Problema, História, Explicação, Filósofo, Psicologia,
Aplicação, Resumo, Conclusão.

Tese: {tese}

Esboço: {esboco}

Material de pesquisa: {research}

Voz: primeira pessoa, acessível, sem jargão não explicado; concreto antes de
abstrato; uma posição clara; um contra-argumento honesto em algum ponto.
Padrão ZERO aspas — só cite se frase, autor e obra vierem confirmados da pesquisa.

Notas de revisão a corrigir nesta versão (se houver):
{notas}
```

`src/forge/writer/prompts/review.md`:
```markdown
Revise este roteiro nas dimensões: fato, clareza, retenção, coesão, repetição.

Aprove (aprovado=true) somente se o roteiro passa em todas. Caso contrário,
aprovado=false e liste notas objetivas: dimensão, problema, sugestão.
Rejeite qualquer aspa sem autor e obra confirmados.

Roteiro:
{roteiro}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/writer/test_prompts.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/forge/writer/_prompts.py src/forge/writer/prompts
git add tests/writer/test_prompts.py
git commit -m "feat: add prompt loader and stage prompts"
```

---

### Task 7: conftest (model roteirizado) + writer/tema.py + writer/research.py

**Files:**
- Create: `tests/conftest.py`, `src/forge/writer/tema.py`, `src/forge/writer/research.py`
- Test: `tests/writer/test_tema.py`, `tests/writer/test_research.py`

**Interfaces:**
- Consumes: `load_prompt` (Task 6); `Fonte`, `FonteList` (Task 4).
- Produces:
  - `ScriptedModel` (test fixture) com `bind_tools(tools) -> self`, `invoke(messages) -> AIMessage`, `with_structured_output(schema) -> obj com .invoke(messages) -> próximo item da fila`.
  - `gerar_tema(model, tema: str | None = None) -> str`.
  - `pesquisar(model, tema: str) -> tuple[str, list[Fonte]]`.
  - `WEB_SEARCH_TOOL: dict` (definição da ferramenta server-side).

- [ ] **Step 1: Write the failing tests + conftest**

`tests/conftest.py`:
```python
import pytest
from langchain_core.messages import AIMessage


class ScriptedModel:
    """Model falso: entrega respostas pré-roteirizadas, sem rede."""

    def __init__(self, *, invoke_texts=None, structured=None):
        self.invoke_texts = list(invoke_texts or [])
        self.structured = list(structured or [])
        self.bound_tools = None

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    def invoke(self, messages):
        return AIMessage(content=self.invoke_texts.pop(0))

    def with_structured_output(self, schema):
        queue = self.structured

        class _Structured:
            def invoke(self, messages):
                return queue.pop(0)

        return _Structured()


@pytest.fixture
def scripted():
    return ScriptedModel
```

`tests/writer/test_tema.py`:
```python
from forge.writer.tema import gerar_tema

def test_tema_fornecido_nao_chama_modelo():
    assert gerar_tema(None, "Sobre o tédio") == "Sobre o tédio"

def test_tema_gerado(scripted):
    model = scripted(invoke_texts=["O tédio é um alarme"])
    assert gerar_tema(model) == "O tédio é um alarme"
```

`tests/writer/test_research.py`:
```python
from forge.writer.models import Fonte, FonteList
from forge.writer.research import pesquisar, WEB_SEARCH_TOOL

def test_pesquisar_retorna_notas_e_fontes(scripted):
    model = scripted(
        invoke_texts=["notas densas sobre o tema"],
        structured=[FonteList(fontes=[Fonte(titulo="Ética a Nicômaco", autor="Aristóteles")])],
    )
    notes, fontes = pesquisar(model, "virtude")
    assert notes == "notas densas sobre o tema"
    assert fontes[0].autor == "Aristóteles"
    assert model.bound_tools == [WEB_SEARCH_TOOL]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/writer/test_tema.py tests/writer/test_research.py -v`
Expected: FAIL (`forge.writer.tema` / `forge.writer.research` inexistentes).

- [ ] **Step 3: Write implementations**

`src/forge/writer/tema.py`:
```python
from langchain_core.messages import HumanMessage

from forge.writer._prompts import load_prompt


def gerar_tema(model, tema: str | None = None) -> str:
    if tema:
        return tema
    resp = model.invoke([HumanMessage(content=load_prompt("tema"))])
    return _texto(resp).strip()


def _texto(resp) -> str:
    content = resp.content
    if isinstance(content, str):
        return content
    return "".join(
        b.get("text", "") for b in content if isinstance(b, dict)
    )
```

`src/forge/writer/research.py`:
```python
from langchain_core.messages import HumanMessage

from forge.writer._prompts import load_prompt
from forge.writer.models import Fonte, FonteList
from forge.writer.tema import _texto

WEB_SEARCH_TOOL: dict = {"type": "web_search_20260209", "name": "web_search"}


def pesquisar(model, tema: str) -> tuple[str, list[Fonte]]:
    search = model.bind_tools([WEB_SEARCH_TOOL])
    resp = search.invoke([HumanMessage(content=load_prompt("research").format(tema=tema))])
    notes = _texto(resp)
    fontes = _extrair_fontes(model, notes)
    return notes, fontes


def _extrair_fontes(model, notes: str) -> list[Fonte]:
    prompt = load_prompt("fontes").format(notes=notes)
    result = model.with_structured_output(FonteList).invoke([HumanMessage(content=prompt)])
    return result.fontes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/writer/test_tema.py tests/writer/test_research.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py src/forge/writer/tema.py src/forge/writer/research.py
git add tests/writer/test_tema.py tests/writer/test_research.py
git commit -m "feat: add tema and research stages"
```

---

### Task 8: writer/plan.py + writer/write.py

**Files:**
- Create: `src/forge/writer/plan.py`, `src/forge/writer/write.py`
- Test: `tests/writer/test_plan.py`, `tests/writer/test_write.py`

**Interfaces:**
- Consumes: `ScriptedModel` (Task 7); `Plano`, `RoteiroDraft`, `Secao`, `Roteiro`, `Fonte` (Task 4).
- Produces:
  - `planejar(model, tema: str, research: str) -> tuple[str, str]` (tese, esboco).
  - `escrever(model, tema: str, tese: str, esboco: str, research: str, fontes: list[Fonte], notas=None) -> Roteiro`.

- [ ] **Step 1: Write the failing tests**

`tests/writer/test_plan.py`:
```python
from forge.writer.models import Plano
from forge.writer.plan import planejar

def test_planejar(scripted):
    model = scripted(structured=[Plano(tese="tese X", esboco="esboço Y")])
    tese, esboco = planejar(model, "tema", "notas")
    assert tese == "tese X"
    assert esboco == "esboço Y"
```

`tests/writer/test_write.py`:
```python
from forge.writer.models import RoteiroDraft, Secao, Fonte
from forge.writer.write import escrever

def _draft():
    return RoteiroDraft(secoes=[Secao(nome="Hook", conteudo="c")])

def test_escrever_monta_roteiro(scripted):
    model = scripted(structured=[_draft()])
    fontes = [Fonte(titulo="Obra", autor="Autor")]
    r = escrever(model, "tema", "tese", "esboço", "notas", fontes)
    assert r.tema == "tema" and r.tese == "tese"
    assert r.secoes[0].nome == "Hook"
    assert r.fontes == fontes

def test_escrever_aceita_notas(scripted):
    model = scripted(structured=[_draft()])
    from forge.writer.models import Nota
    r = escrever(model, "t", "te", "e", "n", [], notas=[Nota(dimensao="clareza", problema="p", sugestao="s")])
    assert r.secoes  # não quebra com notas
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/writer/test_plan.py tests/writer/test_write.py -v`
Expected: FAIL (módulos inexistentes).

- [ ] **Step 3: Write implementations**

`src/forge/writer/plan.py`:
```python
from langchain_core.messages import HumanMessage

from forge.writer._prompts import load_prompt
from forge.writer.models import Plano


def planejar(model, tema: str, research: str) -> tuple[str, str]:
    prompt = load_prompt("plan").format(tema=tema, research=research)
    plano = model.with_structured_output(Plano).invoke([HumanMessage(content=prompt)])
    return plano.tese, plano.esboco
```

`src/forge/writer/write.py`:
```python
from langchain_core.messages import HumanMessage

from forge.writer._prompts import load_prompt
from forge.writer.models import Fonte, Nota, Roteiro, RoteiroDraft


def escrever(
    model,
    tema: str,
    tese: str,
    esboco: str,
    research: str,
    fontes: list[Fonte],
    notas: list[Nota] | None = None,
) -> Roteiro:
    prompt = load_prompt("write").format(
        tese=tese, esboco=esboco, research=research, notas=_fmt_notas(notas)
    )
    draft = model.with_structured_output(RoteiroDraft).invoke([HumanMessage(content=prompt)])
    return Roteiro(tema=tema, tese=tese, secoes=draft.secoes, fontes=fontes)


def _fmt_notas(notas: list[Nota] | None) -> str:
    if not notas:
        return "(nenhuma — primeira versão)"
    return "\n".join(f"- [{n.dimensao}] {n.problema} → {n.sugestao}" for n in notas)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/writer/test_plan.py tests/writer/test_write.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/forge/writer/plan.py src/forge/writer/write.py
git add tests/writer/test_plan.py tests/writer/test_write.py
git commit -m "feat: add plan and write stages"
```

---

### Task 9: writer/review.py

**Files:**
- Create: `src/forge/writer/review.py`
- Test: `tests/writer/test_review.py`

**Interfaces:**
- Consumes: `ScriptedModel` (Task 7); `ReviewResult`, `Roteiro`, `Secao` (Task 4).
- Produces: `revisar(model, roteiro: Roteiro) -> ReviewResult`.

- [ ] **Step 1: Write the failing test**

`tests/writer/test_review.py`:
```python
from forge.writer.models import ReviewResult, Nota, Roteiro, Secao
from forge.writer.review import revisar

def _roteiro():
    return Roteiro(tema="t", tese="te", secoes=[Secao(nome="Hook", conteudo="c")])

def test_revisar_aprovado(scripted):
    model = scripted(structured=[ReviewResult(aprovado=True)])
    rr = revisar(model, _roteiro())
    assert rr.aprovado is True

def test_revisar_reprovado_com_notas(scripted):
    model = scripted(structured=[ReviewResult(aprovado=False, notas=[Nota(dimensao="fato", problema="p", sugestao="s")])])
    rr = revisar(model, _roteiro())
    assert rr.aprovado is False and rr.notas[0].dimensao == "fato"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/writer/test_review.py -v`
Expected: FAIL (`forge.writer.review` inexistente).

- [ ] **Step 3: Write implementation**

`src/forge/writer/review.py`:
```python
from langchain_core.messages import HumanMessage

from forge.writer._prompts import load_prompt
from forge.writer.models import ReviewResult, Roteiro


def revisar(model, roteiro: Roteiro) -> ReviewResult:
    prompt = load_prompt("review").format(roteiro=_render(roteiro))
    return model.with_structured_output(ReviewResult).invoke([HumanMessage(content=prompt)])


def _render(roteiro: Roteiro) -> str:
    partes = [f"Tese: {roteiro.tese}", ""]
    for s in roteiro.secoes:
        partes.append(f"## {s.nome}\n{s.conteudo}\n")
    return "\n".join(partes)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/writer/test_review.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/forge/writer/review.py tests/writer/test_review.py
git commit -m "feat: add review stage"
```

---

### Task 10: orchestrator — state + graph (loop de review)

**Files:**
- Create: `src/forge/orchestrator/state.py`, `src/forge/orchestrator/graph.py`, `tests/orchestrator/__init__.py`
- Test: `tests/orchestrator/test_graph.py`

**Interfaces:**
- Consumes: todos os estágios `writer.*` (Tasks 7–9); `Settings` (Task 2); `Roteiro`, `ReviewResult` (Task 4).
- Produces:
  - `RoteiroState` (TypedDict, `total=False`) com chaves `tema`, `research_notes`, `fontes`, `tese`, `esboco`, `roteiro`, `review`, `rounds`.
  - `should_continue(state: dict, max_rounds: int) -> str` (retorna `"write"` ou `langgraph.graph.END`).
  - `build_graph(model, settings) -> CompiledGraph`.

- [ ] **Step 1: Write the failing tests**

`tests/orchestrator/__init__.py`: (arquivo vazio)

`tests/orchestrator/test_graph.py`:
```python
from langgraph.graph import END
from forge.config import Settings
from forge.orchestrator.graph import should_continue, build_graph
from forge.writer.models import (
    ReviewResult, Nota, Plano, RoteiroDraft, Secao, FonteList, Fonte,
)

# --- should_continue (puro) ---

def test_should_continue_aprovado():
    state = {"review": ReviewResult(aprovado=True), "rounds": 1}
    assert should_continue(state, max_rounds=8) == END

def test_should_continue_reprovado_volta_para_write():
    state = {"review": ReviewResult(aprovado=False, notas=[]), "rounds": 1}
    assert should_continue(state, max_rounds=8) == "write"

def test_should_continue_bate_teto():
    state = {"review": ReviewResult(aprovado=False), "rounds": 8}
    assert should_continue(state, max_rounds=8) == END

# --- grafo completo com model roteirizado ---

def _draft():
    return RoteiroDraft(secoes=[Secao(nome="Hook", conteudo="c")])

def test_grafo_aprova_apos_uma_reprovacao(scripted):
    # sequência de structured: fontes, plano, draft(v1), review(reprovado),
    #                          draft(v2), review(aprovado)
    model = scripted(
        invoke_texts=["tema gerado", "notas de pesquisa"],
        structured=[
            FonteList(fontes=[Fonte(titulo="Obra", autor="Autor")]),
            Plano(tese="tese", esboco="esboço"),
            _draft(),
            ReviewResult(aprovado=False, notas=[Nota(dimensao="clareza", problema="p", sugestao="s")]),
            _draft(),
            ReviewResult(aprovado=True),
        ],
    )
    settings = Settings(_env_file=None, max_review_rounds=8)
    graph = build_graph(model, settings)
    final = graph.invoke({"tema": None, "rounds": 0})
    assert final["review"].aprovado is True
    assert final["rounds"] == 2
    assert final["roteiro"].secoes[0].nome == "Hook"

def test_grafo_para_no_teto(scripted):
    model = scripted(
        invoke_texts=["tema", "notas"],
        structured=[
            FonteList(),
            Plano(tese="t", esboco="e"),
            _draft(), ReviewResult(aprovado=False),
            _draft(), ReviewResult(aprovado=False),
        ],
    )
    settings = Settings(_env_file=None, max_review_rounds=2)
    graph = build_graph(model, settings)
    final = graph.invoke({"tema": None, "rounds": 0})
    assert final["rounds"] == 2
    assert final["review"].aprovado is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_graph.py -v`
Expected: FAIL (`forge.orchestrator.graph` inexistente).

- [ ] **Step 3: Write implementations**

`src/forge/orchestrator/state.py`:
```python
from typing import TypedDict

from forge.writer.models import Fonte, ReviewResult, Roteiro


class RoteiroState(TypedDict, total=False):
    tema: str | None
    research_notes: str
    fontes: list[Fonte]
    tese: str
    esboco: str
    roteiro: Roteiro | None
    review: ReviewResult | None
    rounds: int
```

`src/forge/orchestrator/graph.py`:
```python
from langgraph.graph import END, StateGraph

from forge.orchestrator.state import RoteiroState
from forge.writer import plan as plan_stage
from forge.writer import research as research_stage
from forge.writer import review as review_stage
from forge.writer import tema as tema_stage
from forge.writer import write as write_stage


def should_continue(state: dict, max_rounds: int) -> str:
    review = state.get("review")
    if review is not None and review.aprovado:
        return END
    if state.get("rounds", 0) >= max_rounds:
        return END
    return "write"


def build_graph(model, settings):
    def node_tema(state):
        return {"tema": tema_stage.gerar_tema(model, state.get("tema"))}

    def node_research(state):
        notes, fontes = research_stage.pesquisar(model, state["tema"])
        return {"research_notes": notes, "fontes": fontes}

    def node_plan(state):
        tese, esboco = plan_stage.planejar(model, state["tema"], state["research_notes"])
        return {"tese": tese, "esboco": esboco}

    def node_write(state):
        review = state.get("review")
        notas = review.notas if review is not None else None
        roteiro = write_stage.escrever(
            model,
            state["tema"],
            state["tese"],
            state["esboco"],
            state["research_notes"],
            state["fontes"],
            notas,
        )
        return {"roteiro": roteiro}

    def node_review(state):
        result = review_stage.revisar(model, state["roteiro"])
        return {"review": result, "rounds": state.get("rounds", 0) + 1}

    g = StateGraph(RoteiroState)
    g.add_node("tema", node_tema)
    g.add_node("research", node_research)
    g.add_node("plan", node_plan)
    g.add_node("write", node_write)
    g.add_node("review", node_review)

    g.set_entry_point("tema")
    g.add_edge("tema", "research")
    g.add_edge("research", "plan")
    g.add_edge("plan", "write")
    g.add_edge("write", "review")
    g.add_conditional_edges(
        "review",
        lambda s: should_continue(s, settings.max_review_rounds),
        {"write": "write", END: END},
    )
    return g.compile()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_graph.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/forge/orchestrator tests/orchestrator
git commit -m "feat: add LangGraph orchestrator with review loop"
```

---

### Task 11: output/storage.py — gravação em Markdown

**Files:**
- Create: `src/forge/output/storage.py`
- Test: `tests/test_storage.py`

**Interfaces:**
- Consumes: `Roteiro`, `Secao`, `Fonte` (Task 4); `Settings` (Task 2).
- Produces: `gravar_roteiro(roteiro: Roteiro, settings: Settings, rounds: int | None = None) -> Path`.

- [ ] **Step 1: Write the failing test**

`tests/test_storage.py`:
```python
from forge.config import Settings
from forge.output.storage import gravar_roteiro
from forge.writer.models import Roteiro, Secao, Fonte

def _roteiro():
    return Roteiro(
        tema="O tédio como alarme",
        tese="O tédio informa",
        secoes=[Secao(nome=n, conteudo=f"conteúdo {n}") for n in
                ["Hook", "Problema", "História", "Explicação", "Filósofo",
                 "Psicologia", "Aplicação", "Resumo", "Conclusão"]],
        fontes=[Fonte(titulo="Obra", autor="Autor")],
    )

def test_grava_arquivo_com_secoes_e_frontmatter(tmp_path):
    settings = Settings(_env_file=None, output_dir=tmp_path)
    path = gravar_roteiro(_roteiro(), settings, rounds=2)
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---")            # frontmatter
    assert "tema: O tédio como alarme" in text
    assert "rounds: 2" in text
    for nome in ["Hook", "Conclusão"]:
        assert f"## {nome}" in text
    # ordem: Hook antes de Conclusão
    assert text.index("## Hook") < text.index("## Conclusão")

def test_slug_no_nome_do_arquivo(tmp_path):
    settings = Settings(_env_file=None, output_dir=tmp_path)
    path = gravar_roteiro(_roteiro(), settings)
    assert path.suffix == ".md"
    assert "o-tedio" in path.name
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_storage.py -v`
Expected: FAIL (`forge.output.storage` inexistente).

- [ ] **Step 3: Write implementation**

`src/forge/output/storage.py`:
```python
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from forge.config import Settings
from forge.writer.models import Roteiro


def gravar_roteiro(roteiro: Roteiro, settings: Settings, rounds: int | None = None) -> Path:
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = settings.output_dir / f"{_slug(roteiro.tema)}-{ts}.md"
    path.write_text(_render(roteiro, settings, rounds, ts), encoding="utf-8")
    return path


def _render(roteiro: Roteiro, settings: Settings, rounds: int | None, ts: str) -> str:
    linhas = [
        "---",
        f"tema: {roteiro.tema}",
        f"tese: {roteiro.tese}",
        f"modelo: {settings.model}",
        f"timestamp: {ts}",
        f"rounds: {rounds if rounds is not None else 0}",
        "---",
        "",
    ]
    for s in roteiro.secoes:
        linhas.append(f"## {s.nome}")
        linhas.append("")
        linhas.append(s.conteudo)
        linhas.append("")
    if roteiro.fontes:
        linhas.append("## Fontes")
        linhas.append("")
        for f in roteiro.fontes:
            autor = f" — {f.autor}" if f.autor else ""
            linhas.append(f"- {f.titulo}{autor}")
    return "\n".join(linhas) + "\n"


def _slug(texto: str) -> str:
    norm = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    norm = re.sub(r"[^a-zA-Z0-9]+", "-", norm).strip("-").lower()
    return (norm or "roteiro")[:60]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_storage.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/forge/output/storage.py tests/test_storage.py
git commit -m "feat: add markdown storage"
```

---

### Task 12: cli.py — wiring do comando `roteiro`

**Files:**
- Create: `src/forge/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `get_settings` (Task 2), `setup_logging` (Task 3), `build_chat_model` (Task 5), `build_graph` (Task 10), `gravar_roteiro` (Task 11).
- Produces: `main(argv: list[str] | None = None) -> int`; entrypoint `forge` (já em `pyproject.toml`).

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:
```python
from pathlib import Path

import forge.cli as cli
from forge.config import Settings
from forge.writer.models import Roteiro, Secao


def test_main_roteiro(monkeypatch, tmp_path, capsys):
    settings = Settings(_env_file=None, output_dir=tmp_path, anthropic_api_key="sk-test")
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "build_chat_model", lambda s: object())

    roteiro = Roteiro(tema="tema", tese="tese",
                      secoes=[Secao(nome="Hook", conteudo="c")])

    class FakeGraph:
        def invoke(self, state):
            assert state["tema"] == "meu tema"
            return {"roteiro": roteiro, "rounds": 1, "review": None}

    monkeypatch.setattr(cli, "build_graph", lambda model, s: FakeGraph())

    rc = cli.main(["roteiro", "--tema", "meu tema"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert Path(out).exists()
    assert out.endswith(".md")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL (`forge.cli` inexistente / `main`).

- [ ] **Step 3: Write implementation**

`src/forge/cli.py`:
```python
import argparse

from forge.config import get_settings
from forge.llm.model import build_chat_model
from forge.logging import setup_logging
from forge.orchestrator.graph import build_graph
from forge.output.storage import gravar_roteiro


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="forge")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("roteiro", help="Gera um roteiro de vídeo")
    r.add_argument("--tema", default=None, help="Tema (opcional; gerado se ausente)")
    args = parser.parse_args(argv)

    settings = get_settings()
    setup_logging(settings.log_level)
    model = build_chat_model(settings)
    graph = build_graph(model, settings)

    final = graph.invoke({"tema": args.tema, "rounds": 0})
    path = gravar_roteiro(final["roteiro"], settings, rounds=final.get("rounds"))
    print(path)
    return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Full suite + commit**

Run: `uv run pytest -v`
Expected: todos PASS.

```bash
git add src/forge/cli.py tests/test_cli.py
git commit -m "feat: wire forge roteiro CLI"
```

---

### Task 13: Teste de integração (opcional, atrás de env var)

**Files:**
- Create: `tests/test_integration.py`

**Interfaces:**
- Consumes: `get_settings`, `build_chat_model`, `build_graph`. Roda a API real; pulado sem chave.

- [ ] **Step 1: Write the gated test**

`tests/test_integration.py`:
```python
import os

import pytest

from forge.config import Settings
from forge.llm.model import build_chat_model
from forge.orchestrator.graph import build_graph

pytestmark = pytest.mark.skipif(
    not (os.getenv("FORGE_ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY")),
    reason="sem API key — pula integração",
)


def test_pipeline_real(tmp_path):
    settings = Settings(_env_file=None, output_dir=tmp_path, max_review_rounds=2)
    graph = build_graph(build_chat_model(settings), settings)
    final = graph.invoke({"tema": "O papel do tédio na vida moderna", "rounds": 0})
    roteiro = final["roteiro"]
    assert len(roteiro.secoes) == 9
    assert final["review"] is not None
```

- [ ] **Step 2: Run (skipped without key)**

Run: `uv run pytest tests/test_integration.py -v`
Expected: SKIPPED (sem chave) — ou PASS se `FORGE_ANTHROPIC_API_KEY` setada.

- [ ] **Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add gated integration test"
```

---

## Notas finais

- Após Task 12, rodar `uv run pytest -v` deve dar tudo verde sem rede.
- Validação end-to-end real (Task 13 ou `forge roteiro --tema "..."` com chave)
  confirma o combo `ChatAnthropic` + adaptive thinking + `web_search` +
  `with_structured_output`. Se algum combo falhar, ver §10 do spec: isolar as
  chamadas (já está — tools e structured nunca juntos).
