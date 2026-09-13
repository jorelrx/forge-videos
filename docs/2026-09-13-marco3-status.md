# Forge Studio — Marco 3 (Executores) — Atualização

Plano implementado: `docs/superpowers/plans/2026-09-13-forge-studio-executors.md`

Nota: `README.md` ainda descreve a estrutura antiga (`writer/`, `orchestrator/`, `knowledge/`). A estrutura real está em `AGENTS.md` e neste arquivo.

## Marco 3 — Executores (concluído)

Todas 13 tasks do plano implementadas. 8 executores registrados em `studio.py`. Subprocesso isolado (`shell=False`), SQLite fonte de verdade, broker GPU com PID, reconciliação sem apagar arquivos, validação final com ffprobe + frames. Zero referências `_pipeline-poc`. Testes: 603 pass / 5 pré-existentes (não relacionadas ao plano).
