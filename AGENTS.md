# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

**CreatorBrain / forge-videos** — a LangGraph pipeline that generates Portuguese video scripts (roteiros). From a theme (or none — it invents one), it researches the web, plans a thesis, writes a 9-section script, and iterates with a reviewer agent until approved.

> Note: `README.md` describes an older module layout (`writer/`, `orchestrator/`, `llm/`, `output/`). The current tree is `agents/`, `orchestration/`, `llms/`, `services/`, `prompts/`, plus `knowledge/`. Trust the code, not the README, for structure.

## Commands

```bash
uv sync                                  # core deps
uv sync --extra knowledge                # RAG stores client libs + embeddings
uv sync --extra books --extra ocr        # book parsing (pypdf/ebooklib) + OCR (tesseract)

uv run forge roteiro                     # theme invented by LLM
uv run forge roteiro --tema "..."        # fixed theme
uv run forge roteiro --provider lm-studio
uv run forge roteiro --retomar output/runs/<ts>-<slug>   # resume a prior run from disk

uv run forge ingest --path <file|dir>    # ingest books into the knowledge base
uv run forge ingest --status             # count what is indexed
uv run forge ingest --reset              # WIPES all three stores and recreates the schema

docker compose up -d                     # bring up Qdrant/Neo4j/Postgres for knowledge layer

uv run pytest                            # full suite (model mocked, no network)
uv run pytest -k research                # one module
uv run pytest tests/agents/test_write.py::test_name   # single test
```

`roteiro` prints the output path to stdout and per-node progress (`[tema]`, `[research]`, ...) plus the run dir to stderr. Config comes from `FORGE_`-prefixed env vars / `.env` (see `infrastructure/config.py`). Minimum to run anthropic: `FORGE_ANTHROPIC_API_KEY`.

## Architecture

### The graph ([orchestration/graph.py](src/forge/orchestration/graph.py))

A LangGraph `StateGraph` over shared `RoteiroState` (a `TypedDict`, [orchestration/state.py](src/forge/orchestration/state.py)):

```
tema → research → plan → write → review → (conditional)
```

`rotear()` decides after each review:
- `review.verificar` non-empty → **research** (fact-check handoff: reviewer flagged claims needing verification)
- `review.aprovado` → END
- else, under `max_review_rounds` → **write** (revise using review notes)
- `passos >= max_passos` → END (hard budget cap on total steps, independent of the review-round cap)

`write` can *also* jump straight back to research via `Command(goto="research")` when the model sets `falta_pesquisa` — the material doesn't support a section. So research is re-entered from two places, and it merges directed follow-up briefs into the accumulated `research_notes` rather than replacing them.

**Two counters, two limits:** `rounds` counts review iterations (`max_review_rounds`, default 8); `passos` counts every node execution (`max_passos`, default 20) and is the backstop against runaway loops.

### Agent contract ([agents/](src/forge/agents/))

Each stage module (`tema`, `research`, `plan`, `write`, `review`) exports:
- `LE` — the list of state keys the agent reads. `com_wrapper` in graph.py narrows the full state down to `LE` before calling the node, so agents can't accidentally depend on unlisted state.
- a pure function doing the LLM work.

`com_wrapper` also writes the stage's artifact to disk and increments `passos`. A node returning a dict with `_raw` gets that written as a `.raw.md` sidecar (unparsed model output).

### Run artifacts & resume ([services/artefatos.py](src/forge/services/artefatos.py))

Every stage writes a numbered markdown file (`00-tema.md`, `01-research.md`, `03-write-r1.md`, ...) into `output/runs/<ts>-<slug>/`. `--retomar` reconstructs `RoteiroState` by parsing these back and returns the first pending stage. Subtleties encoded here (with comments explaining why): write/review files are numbered by counting existing files, not by `rounds`; `-r10` sorts after `-r2` by parsed round number, not lexically; section parsing is restricted to the closed set `SECOES_NOMES` so a stray `##` in prose can't create a phantom section. The final approved script is rendered separately by [services/storage.py](src/forge/services/storage.py) into `output/roteiros/`.

### Providers ([llms/model.py](src/forge/llms/model.py), [infrastructure/config.py](src/forge/infrastructure/config.py))

Three providers: `anthropic`, `openai`, `lm-studio`. `settings.resolved_model` / `settings.resolved_api_key` pick model + key for the *active* provider. Keys never cross providers — a missing key fails with an explicit `API key ausente para o provider '<name>'` instead of an opaque 401 downstream. Research adapts to the provider: anthropic uses the server-side `web_search` tool; openai/lm-studio use client-side tool-calling over DuckDuckGo (`ddgs`), up to 5 rounds.

### Prompts & skills

- **Prompts** ([prompts/](src/forge/prompts/)) are markdown loaded by name via `load_prompt()`. Editing a prompt needs no Python change.
- **Skills** ([skills/](src/forge/skills/)) are markdown with frontmatter (`nome`, `dono`, `dominio`) and sections `Critérios` / `Anti-padrões` / `Procedimento`. `load_skills()` injects them into prompts. Key rule: the **`Procedimento` section is only shown to the owning agent** (`dono`) — it's the boundary between what a *producer* agent sees and what a *reviewer* must not. An unrecognized section title raises rather than passing silently.

### Knowledge layer ([knowledge/](src/forge/knowledge/), optional, off by default)

Fonte de verdade do design: [docs/knowledge.md](docs/knowledge.md). Seis níveis,
implementados como seis sub-projetos K1-K6.

**Duas árvores que nunca se misturam.** A estrutural (Postgres) é imutável,
derivada só do texto, sem LLM: Livro > Capítulo > Subcapítulo > Seção > Parágrafo
> Sentença, com `pai_id` e caminho materializado. O grafo semântico (Neo4j) é
evolutivo, referencia `chunk_id` e é escrito a partir de K3. Regenerar a camada
semântica nunca exige reingerir a estrutural.

- **Identidade de chunk vem do conteúdo**, não da posição:
  `id_deterministico(documento_id, sha256(texto), ocorrencia)`. A camada semântica
  acumula anotações sobre `chunk_id`; id posicional invalidaria tudo a cada
  reingestão.
- **Texto nunca é alterado.** `documentos.texto` é a extração crua; o texto de um
  chunk é fatia por offset. Normalização só como entrada transitória de tsvector e
  embedding.
- **Só a folha-parágrafo é embedada** (small-to-big): vetor preciso, entrega sobe
  pelo `pai_id`. Só ela tem coluna `texto`; os outros níveis derivam por offset.
- **Ingestão de K1 não faz nenhuma chamada de LLM.** A única que resta na camada é
  a tradução do termo de busca em fontes remotas, que não toca o conteúdo.
- **Retriever dormente até K5.** `retriever/hybrid.py` não tem chamador; o comando
  `forge buscar` não existe; o fluxo de roteiro não toca a camada.
- Testabilidade: `embed_fn` e `stores` entram por injeção — o pipeline roda com
  fakes, sem Docker. `_montar()` monta as reais a partir de `Settings`.

## Response style

- **Always keep caveman mode active** in your responses to the user (terse, drop articles/filler/pleasantries/hedging; fragments OK). This holds even while a Superpowers skill (brainstorming, systematic-debugging, TDD, etc.) is driving the workflow — run the skill's process *and* keep the caveman voice; they stack, one does not disable the other.
- Caveman applies only to prose addressed to the user. Code, commits, PRs, docs (like this file), and security/destructive-action warnings stay written normally.
- Preserve the user's dominant language: user writes Portuguese → reply Portuguese caveman.

## Conventions

- Domain/state names and log messages are Portuguese; code identifiers mix Portuguese and English. Match the surrounding file.
- Structured logging via `structlog` — `get_logger(__name__)`, key=value fields, never f-strings in log calls.
- Tests mock the model and hit no network; `tests/test_integration.py` is gated on real credentials being present.
