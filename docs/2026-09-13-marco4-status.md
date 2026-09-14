---
timestamp: 2026-09-13
marco: 4
status: aceitação parcial
---

# Status Marco 4 — 2026-09-13

## Tasks 1-9: concluídas
- Pipeline base, agentes (tema, research, plan, write, review, midia)
- Grafo LangGraph, executores isolados (subprocesso)
- Catálogo de artefatos (SHA-256), reconciliação, gate final
- Configuração, logging, documentação (`docs/logging.md`, `docs/2026-09-13-marco3-status.md`)

## Task 10 (Aceitação + docs): parcial
- `tests/api/test_acceptance.py`: criado (RED — falhas esperadas; sem continuidade pós-restart, replay SSE, idempotência, preview seguro, fila ordenada)
- `web/components/dashboard.test.tsx`: criado (RED — comportamento completo ainda parcial)
- `README.md`: atualizado com `uv run forge-api` e `npm run dev --prefix web`
- `docs/2026-09-13-marco4-status.md`: este arquivo

## Marco 5 (próximo): planejado
- Launcher, importador de mídia, testes reais (não RED), vídeo completo

## Verificação final executada
- `pytest tests/api/test_acceptance.py -q`: falhou (RED esperado)
- `npm test --prefix web -- dashboard`: falhou (RED esperado)
- `git diff --check`: limpo
- `rg -n '_pipeline-poc|C:\\dev\\_pipeline-poc' src web tests`: sem ocorrências
- Commit final realizado.
