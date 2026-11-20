# Provider Claude por assinatura (fase A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `FORGE_PROVIDER=claude` runs the whole pipeline on the Claude subscription through the official `claude -p`, and `FORGE_REVIEW_PROVIDER` lets the reviewer run on a different provider than the writer.

**Architecture:** A subprocess service (`ClaudeCLI`) mirrors `CodexCLI`: isolated argv, stripped environment, evidence on disk, fail-closed parsing of the CLI's JSON result. A LangChain adapter (`ClaudeChatModel`) mirrors `CodexChatModel`. The graph receives an optional second model for the `review` node.

**Tech Stack:** Python 3.12, LangChain core, pydantic-settings, pytest (no network; the CLI is faked).

**Spec:** `docs/superpowers/specs/2026-11-16-providers-assinatura-design.md`

## Global Constraints

- Never use the Claude OAuth token directly; only `claude -p`.
- argv always carries: `-p --output-format json --model <m> --effort <e> --safe-mode --strict-mcp-config --tools "" --no-session-persistence --exclude-dynamic-system-prompt-sections --system-prompt-file <path>`; `--json-schema <json>` only with a schema.
- Child environment drops every `*_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`.
- Error decided by `is_error`, never by `subtype` (measured: auth failure arrives as `subtype: "success"`, `is_error: true`, exit 1).
- `MODELO_PADRAO["claude"] = "claude-opus-5-5"`; `claude_effort` default `"high"`.
- No silent fallback between providers.
- No commits (branch carries unrelated Codex WIP).
- Logs: structlog key=value, Portuguese messages.

## Review Focus

- System prompt larger than the Windows command-line limit (~32 K chars): goes by file, never argv. Test asserts no prompt text in argv.
- Usage-limit text from the CLI (`usage limit`, `hit your limit`, HTTP 429) must raise `ClaudeUsageLimitError`, not a generic error the stage would retry blindly.
- Expired session (`Failed to authenticate`, HTTP 401) must name `claude auth login`.
- `with_structured_output` when the CLI returns `structured_output: null` with `is_error: false`: parse failure surfaces through `invoke_structured`, not a crash in the adapter.
- `review_provider` equal to `provider` builds no second model (no duplicate client, same behavior as today).

---

### Task 1: `ClaudeCLI`

**Files:**
- Create: `src/forge/services/claude_cli.py`
- Test: `tests/services/test_claude_cli.py`

**Interfaces:**
- Produces: `ClaudeCLI(settings).run(prompt: str, *, system: str, model: str, timeout: float, schema: dict | None = None) -> ClaudeResponse`; `ClaudeResponse(text: str, structured: dict | None, work_dir: Path, stop_reason: str | None, usage: dict)`; `ClaudeCLI.check_auth() -> None`; errors `ClaudeError`, `ClaudeAuthError(ClaudeError)`, `ClaudeUsageLimitError(ClaudeError)`.

- [ ] Tests (fake `SubprocessExecutor` like `tests/services/test_codex.py`, writing the CLI JSON to the stdout file):
  - `test_argv_isolado_e_ambiente_sem_chave`: every Global-Constraints flag present; `ANTHROPIC_API_KEY`, `FORGE_API_KEY`, `ANTHROPIC_BASE_URL` absent from env; prompt arrives on stdin; `prompt.txt`, `system.txt`, `response.json` in `work_dir`; cwd is `work_dir`; owner terminated.
  - `test_system_prompt_vai_por_arquivo`: 40 000-char system text not in any argv element; file content equal.
  - `test_schema_vai_em_json_schema`: `json.loads(argv[argv.index('--json-schema')+1]) == schema`; absent without schema.
  - `test_sucesso_devolve_texto_e_estruturado`: `result`, `structured_output`, `stop_reason`, `usage` mapped.
  - `test_is_error_decide_mesmo_com_subtype_success` (param: auth text → `ClaudeAuthError` with `claude auth login`; `"Claude AI usage limit reached|1763337600"` and `api_error_status: 429` → `ClaudeUsageLimitError` with `cota`; other text → `ClaudeError`), each message carries `logs:`.
  - `test_saida_nao_json_falha_fechado`, `test_timeout_encerra_arvore`.
  - `test_check_auth` (param on `claude auth status` JSON: `loggedIn true/claude.ai` passes; `loggedIn false` or `authMethod` other than `claude.ai` raises `ClaudeAuthError`).
- [ ] Run, watch fail (module missing).
- [ ] Implement: work dir `settings.claude_runs_dir/call-*`; stdout to `response.json`; parse; error mapping by `is_error` + `api_error_status` + text.
- [ ] Run tests, pass.

### Task 2: Config, `ClaudeChatModel`, `build_chat_model`

**Files:**
- Modify: `src/forge/infrastructure/config.py`, `src/forge/llms/model.py`
- Create: `src/forge/llms/claude.py`
- Test: `tests/test_claude_model.py`, `tests/infrastructure/test_config.py` (or the existing config test file)

**Interfaces:**
- Consumes: Task 1.
- Produces: `Provider` includes `"claude"`; settings `claude_bin: str = "claude"`, `claude_effort: Literal["low","medium","high","xhigh","max"] = "high"`, `claude_runs_dir: Path = Path("output/claude")`; `ClaudeChatModel(settings=..., cli=None, model=...)`.

- [ ] Tests:
  - config: `Settings(provider="claude").resolved_model == "claude-opus-5-5"`; `resolved_api_key is None`.
  - `build_chat_model(Settings(provider="claude"))` is a `ClaudeChatModel` and needs no key.
  - adapter: system messages joined into `system`, others serialized as JSON roles on stdin; `invoke` returns `AIMessage` with `response_metadata.provider == "claude"`, `finish_reason` `"length"` when `stop_reason == "max_tokens"` else `"stop"`; `usage_metadata` from usage.
  - `with_structured_output(PydanticSchema, include_raw=True)` returns `parsed` from `structured`; with `structured=None` returns `parsing_error` set and `parsed None`.
  - `invoke_structured(ClaudeChatModel(...), Schema, msgs)` returns the parsed object (bind path works).
- [ ] Watch fail; implement; pass.

### Task 3: Reviewer from another provider

**Files:**
- Modify: `src/forge/infrastructure/config.py`, `src/forge/llms/model.py`, `src/forge/orchestration/graph.py`, `src/forge/executors/roteiro.py`, `src/forge/cli.py`
- Test: `tests/test_review_provider.py`

**Interfaces:**
- Produces: settings `review_provider: Provider | None = None`, `review_model: str | None = None`; `build_review_model(settings) -> BaseChatModel | None`; `build_graph(model, settings, inicio="tema", revisor=None)`.

- [ ] Tests:
  - `build_review_model` is `None` when unset or equal to `provider`; with `provider="codex", review_provider="claude"` returns a `ClaudeChatModel` whose model is `claude-opus-5-5`; `review_model` overrides; `FORGE_MODEL` of the writer does not leak to the reviewer.
  - graph from `inicio="review"` with two `ScriptedModel`s: only the reviewer's structured queue is consumed by `review`.
  - roteiro executor plan hash changes when `review_provider` changes.
- [ ] Watch fail; implement (executor and CLI pass `revisor=build_review_model(settings)`; log `revisor_provider`, `revisor_model` on review completion); pass.

### Task 4: Preflight, health, `/api/system`

**Files:**
- Modify: `src/forge/services/preflight.py`, `src/forge/services/saude.py`, `src/forge/api/routes/system.py`
- Test: existing `tests/services/test_preflight.py`, `tests/services/test_saude.py`, `tests/api/test_system.py`

- [ ] Tests:
  - preflight with `provider="claude"`: no `lm_studio` check; `claude` check PASS when a real minimal `claude -p` call (fake runner) returns `is_error false`; FAIL with action `claude auth login` when it returns the auth error even though `auth status` says logged in.
  - preflight checks `lm_studio` only when `lm-studio` is the provider or the review provider.
  - health with `provider="claude"`: `claude` in names, `lm_studio` absent; probe uses `auth status` (no model call — the dashboard polls it).
  - `/api/system/services` requires `claude` for that provider; `/config/effective` reports `review_provider`, `review_model`, `claude_effort`.
- [ ] Watch fail; implement; pass.

### Task 5: Docs and full suite

- [ ] `CLAUDE.md` Providers section and `.env.example`: `claude` provider, `claude auth login`, `FORGE_REVIEW_PROVIDER`.
- [ ] `uv run pytest` full; pre-existing deselected failure `tests/executors/test_audio_generate.py::test_build_argv_uses_fixed_safe_batch_flags_and_no_sampling_knobs` named in the report.
