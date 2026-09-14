---
timestamp: 2026-09-13
marco: 4
status: aprovado
---

# Status Marco 4 — 2026-09-13

## Tasks 1-9: concluídas
- Pipeline base, agentes (tema, research, plan, write, review, midia)
- Grafo LangGraph, executores isolados (subprocesso)
- Catálogo de artefatos (SHA-256), reconciliação, gate final
- Configuração, logging, documentação (`docs/logging.md`, `docs/2026-09-13-marco3-status.md`)

## Task 10 (Aceitação + docs): concluída
- `tests/api/test_acceptance.py`: aprovado — continuidade pós-restart, replay SSE, idempotência, preview seguro, fila ordenada
- `web/components/dashboard.test.tsx`: comportamento completo aprovado
- `README.md`: atualizado com `uv run forge-api` e `npm run dev --prefix web`
- `docs/2026-09-13-marco4-status.md`: este arquivo

## Marco 5 (próximo): planejado
- Launcher, importador de mídia, testes reais (não RED), vídeo completo

## Gate M1–M4 para Marco 5

- Data: 2026-09-14
- Commit: 2431976
- Python/API: 651 passed, 1 skipped, 7 deselected (integration)
- Web: 26 testes Vitest aprovados; lint 0 erros/16 warnings; build OK
- Browser: aceites de aceitação backend (23 testes) aprovados
- Integrações externas: deliberadamente excluídas por `-m not integration`

## Verificação final executada
- `uv run pytest -q`: 651 passed, 1 skipped, 7 deselected
- `uv run python -m compileall -q src/forge`: exit 0
- `npm test --prefix web`: 26 passed
- `npm run lint --prefix web`: 0 errors, 16 warnings (pre-existing)
- `npm run build --prefix web`: sucesso
- `rg -n '_pipeline-poc|C:\\dev\\_pipeline-poc' src tests web`: sem ocorrências
- Commit final realizado.
