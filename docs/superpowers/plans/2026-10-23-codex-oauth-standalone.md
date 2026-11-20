# Codex OAuth independente — Implementation Plan

> **For agentic workers:** Use superpowers-executing-plans. Execute task-by-task with RED/GREEN tests. Preserve all pre-existing WIP; do not stage or commit unrelated files.

**Goal:** Run Forge text on exactly `gpt-6.1-sol` and images on native Codex image generation, without Hermes or a running Codex CLI, retaining local providers.

**Architecture:** An independent OAuth credential manager reads an explicitly configured token store or Forge's own default store, refreshes under a file lock, and offers browser PKCE login. A native HTTP adapter implements Responses SSE and native image requests. Existing LangChain/executor contracts and CLI transport remain available, explicitly selected. No cloud fallback, model substitution, or GPU slot for remote images.

**Tech Stack:** Existing Python/httpx/Pydantic/Pillow/filelock; standard-library browser PKCE/HTTPServer. No new runtime dependency.

## Verified prerequisite

Native POST to `https://chatgpt.com/backend-api/codex/responses` using existing Codex OAuth, Forge's own originator, `store=false`, `stream=true` returned HTTP 200, `model=gpt-6.1-sol`, completed output `OK`. The existing CLI path rejects that same model. No copied Hermes credentials or runtime imports are needed.

## Ticket 1: Credentials and request identity

Files: create `src/forge/services/codex_auth.py`, `tests/services/test_codex_auth.py`; add settings in `src/forge/infrastructure/config.py`.

- [x] RED/GREEN valid OAuth store, rejection of API-key-only/malformed/missing credentials, expiry-triggered refresh under a lock, atomic token rotation preserving unrelated store keys, no network when token fresh.
- [x] RED/GREEN Forge request identity, account/residency headers from JWT; no token sent to configurable third-party hosts (native endpoints are fixed).
- [x] Add browser PKCE login with random state, loopback-only listener, bounded wait, state verification and token exchange; status prints no secrets. Default store `~/.forge/codex/auth.json`, optional `FORGE_CODEX_AUTH_FILE` points at existing Codex store without copying tokens.

Example contract:
```python
assert OAuthCredentials(path, client=http).access_token() == fresh_token
assert requests == []
```
Run: `uv run pytest tests/services/test_codex_auth.py -q`.

## Ticket 2: Native Responses and LangChain

Files: create `src/forge/services/codex_native.py`, `tests/services/test_codex_native.py`; modify `src/forge/llms/codex.py`, configuration and focused model tests.

- [x] RED/GREEN outgoing exact model, system messages as instructions, human/assistant roles preserved, no tools/store/paid keys; omit unsupported temperature/max-output fields.
- [x] RED/GREEN SSE completed response, schema text.format with strict closed objects, incomplete/disconnected/error/refusal responses fail closed, HTTP auth/quota failures distinct, no model fallback or automatic spend retries.
- [x] Add per-call prompt/result metadata and logs without Authorization/token data. Keep explicit legacy `codex_transport=cli`; native default with text default `gpt-6.1-sol`.

Example contract:
```python
assert sent['model'] == 'gpt-6.1-sol'
assert sent['store'] is False
assert sent['tools'] == []
```
Run: `uv run pytest tests/services/test_codex_native.py tests/test_codex_model.py tests/services/test_codex.py -q`.

## Ticket 3: Direct images and verified cache

Files: create `src/forge/executors/codex_native_images.py`, `tests/executors/test_codex_native_images.py`; modify `src/forge/executors/imagens.py`.

- [x] RED/GREEN native `images/generations` request, one image per beat, requested model `gpt-image-2`, configurable quality, original payload bytes validated with Pillow, normalized PNG and original preserved.
- [x] Cache identity includes backend/model/quality/prompt/resolution; receipt binds final hash; corrupt cache regenerates. Atomic writes preserve prior valid artefact on failure.
- [x] Metadata distinguishes requested model/quality/size from backend-reported fields; seed unsupported, never claimed applied. Preserve backend correlation id.
- [x] Quota rejection stops batch and keeps following beats pending; no GPU/ComfyUI calls.

Example contract:
```python
assert metadata['seed_applied'] is False
assert image.size == (1024, 576)
```
Run: `uv run pytest tests/executors/test_codex_native_images.py tests/executors/test_imagens.py tests/executors/test_codex_images.py -q`.

## Ticket 4: Operator integration and docs

Files: modify `src/forge/cli.py`, `src/forge/services/preflight.py`, `src/forge/services/saude.py`, `src/forge/api/routes/system.py`, `.env.example`, `docs/codex-assinatura.md`, relevant tests; add attribution `THIRD_PARTY_NOTICES.md`.

- [x] RED/GREEN native health/preflight never spawn CLI and never probe replaced LM Studio/ComfyUI; status does not claim model entitlement, only usable authentication.
- [x] Add `forge auth codex login/status` and explicit configuration instructions; text/image selection independent; local unchanged.
- [x] Update effective config with transport/requested image settings, no credentials. Document borrowed token-store sharing/refresh caveat and login to own store for isolation.
- [x] Preserve MIT attribution for adapted protocol logic from Hermes, source revision `bd3cbe91a90097f9804f16ea5c1768f5cbaaf0b7`.

## Ticket 5: Verification and local activation

- [x] Run full standard test suite, compare pre-change baseline; fix only introduced regressions.
- [x] Smoke real text, strict JSON and one image via Forge adapters using explicitly selected existing auth store; inspect PNG and repeat to prove no-spend cache reuse.
- [x] Confirm no Hermes imports, processes or proxy; use project's own Python environment.
- [x] Update only provider/model/transport/image/auth-path settings in local `.env`, preserving secrets and unrelated values; verify via allowlisted Settings output. Do not restart live workers or trigger a full video without checking running jobs.
- [x] Save reproducible validation report with timings/model/status/paths and no credential content. Final report must distinguish smoke validation from a complete video run.
