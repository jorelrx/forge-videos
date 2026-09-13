# Task 5 — arquitetura narrativa e gate local

## Status

Implementação concluída em TDD. O pipeline agora usa a arquitetura tipada de
nove funções em português, integra o `ResearchBundle` já persistido, roteia
chamadas estruturadas pelo retry limitado e aplica gate determinístico antes
de aceitar o roteiro.

## Implementação

- `domain/roteiro.py`: `NarrativeSection`, `ARQUITETURA` imutável e nomes
  canônicos Gancho/Estake/Tensao/Virada/Filosofo/Prova/Espelho/Aplicacao/Fecho.
- `services/qualidade_roteiro.py`: `ScriptGateReport`, defeitos tipados,
  citações independentes de F0, limites de tamanho/frase, similaridade de
  aberturas, labels robóticos e validação de Espelho/Fecho.
- `executors/lm_studio.py`: carregamento fixo Gemma 4 E4B, contexto 16k,
  TTL 3600 e rejeição explícita de `qwen/qwen3.8-27b`.
- `llms/model.py` + agentes: `invoke_structured` com `include_raw=True`,
  reasoning separado e retry único dobrando `max_tokens` apenas após
  `finish_reason=length` sem parse, até teto 16k.
- `executors/roteiro.py`: hash de pesquisa/preset/modelo, carga do bundle
  tipado, execução do grafo a partir de `plan`, loops de fact-check preservados,
  artefatos `video/roteiro.json` e `roteiro.md`, gate determinístico autoritativo.
- Prompts/skills atualizados para a arquitetura e regras de citação/loop.

## TDD e verificações

- RED: coleção falhou pelos três módulos novos ausentes.
- GREEN focado: `uv run --no-cache pytest tests/domain/test_roteiro.py tests/services/test_qualidade_roteiro.py tests/executors/test_lm_studio.py tests/executors/test_roteiro.py tests/test_llm_model.py tests/agents tests/orchestration -q` → **104 passed**.
- Suíte completa: `uv run --no-cache pytest -q` → **525 passed, 1 skipped, 1 deselected**.
- `uv run --no-cache python -m compileall -q src` → OK.
- `git diff --check` → OK.

## Autorrevisão e preocupações

- Fixtures caracterizam exatamente três defeitos graves (`sem_citacao`,
  `frase_longa`, `aberturas_parecidas`) e um roteiro aprovado.
- O executor depende de `video/research.json` canônico; ausência é falha
  deliberada, evitando refazer pesquisa implicitamente.
- Avisos permanecem em `findings`, mas `approved` depende somente de graves.
- Mudanças de expectativa em `tests/agents/test_models.py` e `tests/test_config.py`
  acompanham a migração dos nomes/modelo do contrato.

## Round 1/5 — correções de revisão

### RED/GREEN

- RED focado: `uv run --no-cache pytest tests/services/test_qualidade_roteiro.py::test_espelho_requires_question_as_final_sentence tests/executors/test_roteiro.py::test_execute_passes_reentered_research_evidence_to_gate tests/test_llm_model.py::test_reasoning_content_survives_string_content_in_additional_kwargs -q` → **3 failed**, cada falha reproduzindo um finding.
- GREEN focado: `uv run --no-cache pytest tests/services/test_qualidade_roteiro.py tests/executors/test_roteiro.py tests/test_llm_model.py -q` → **12 passed**.
- Integração: `uv run --no-cache pytest tests/services/test_qualidade_roteiro.py tests/executors/test_roteiro.py tests/test_llm_model.py tests/agents tests/orchestration -q` → **99 passed**.

### Alterações

- `qualidade_roteiro.py`: Espelho agora exige que a última frase termine em
  pergunta; caso contrário é defeito grave. Fixture aprovada corrigida.
- `orchestration/state.py`, `orchestration/graph.py`, `agents/research.py` e
  `executors/roteiro.py`: `research_passages` tipado é inicializado do bundle,
  mesclado por caminho canônico nas reentradas e usado pelo gate final.
- `llms/model.py` e agentes estruturados: reasoning é extraído também de
  `additional_kwargs`/`response_metadata` mesmo com `content` string e salvo
  em `progresso.jsonl` via `run_dir`; plumbing de etapa/subfase incluído.
- Testes: `tests/services/test_qualidade_roteiro.py`,
  `tests/executors/test_roteiro.py`, `tests/test_llm_model.py`.

### Autorrevisão Round 1

- Evidência dirigida sem caminho canônico continua preservada, sem substituir
  evidência anterior; deduplicação ocorre somente quando há `path`.
- Gate não aceita Espelho com pergunta intermediária seguida de declaração.
- Reasoning continua fora do conteúdo parseado e recebe log separado; sem
  `run_dir`, mantém apenas o comportamento de retorno estruturado anterior.
- Round 1 adicional: o executor também aceita `fontes` renovadas como ponte
  para estados de grafo legados que ainda não carreguem `research_passages`.
