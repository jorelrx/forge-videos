# forge-videos

**CreatorBrain** — gerador de roteiros de vídeo em português, construído sobre [LangGraph](https://langchain-ai.github.io/langgraph/).

A partir de um tema (ou nenhum — ele inventa um), o pipeline pesquisa na web, planeja uma tese, escreve o roteiro em 9 seções e itera com um agente revisor até aprovar. O resultado é um arquivo Markdown com frontmatter.

---

## Instalação

Requer Python >= 3.12. O projeto usa [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

Copie o exemplo de configuração e preencha a API key:

```bash
cp .env.example .env
```

```dotenv
FORGE_ANTHROPIC_API_KEY=sk-ant-...
```

## Uso

```bash
# Tema gerado pelo LLM
uv run forge roteiro

# Tema definido por você
uv run forge roteiro --tema "O paradoxo da escolha"

# Trocar de provider na hora
uv run forge roteiro --provider lm-studio
```

O comando imprime no stdout o caminho do arquivo gerado (`output/roteiros/<slug>-<timestamp>.md`) e envia o progresso por node para o stderr:

```
[tema]
[research]
[plan]
[write]
[review]
output/roteiros/o-paradoxo-da-escolha-20260719-143012.md
```

## Como funciona

O orquestrador é um `StateGraph` com cinco nodes e um loop de revisão:

```
tema ──► research ──► plan ──► write ──► review ──┐
                                   ▲              │
                                   └── reprovado ─┤
                                                  ▼
                                              aprovado / limite → END
```

| Node | Módulo | O que faz |
|---|---|---|
| `tema` | `agents/tema.py` | Usa o tema recebido, ou pede um ao LLM |
| `research` | `agents/research.py` | Pesquisa no acervo (`FORGE_ACERVO_URL`) — sem fallback web |
| `plan` | `agents/plan.py` | Produz `tese` + `esboco` |
| `write` | `agents/write.py` | Escreve 9 seções (Gancho → Fecho) com gate objetivo |
| `review` | `agents/review.py` | Devolve `aprovado` + `notas` + `findings` (métricas objetivas) |

O loop volta para `write` enquanto o review reprovar, até o teto de `FORGE_MAX_REVIEW_ROUNDS` (padrão: 8). O estado compartilhado está em `domain/execucao.py` (RunSnapshot, StagePlan, GateResult) e `repositories/operacao.py` (SQLite transacional: work_items, artifacts, videos). O Marco 3 adiciona executores isolados por subprocesso (`executors/`), catálogo de artefatos com SHA-256 (`services/catalogo.py`), reconciliação (`services/reconciliacao.py`) e gate final (`executors/validacao.py`).

### Pesquisa web

Duas estratégias, escolhidas pelo provider:

- **anthropic** — ferramenta `web_search` server-side, executada pela própria API.
- **openai / lm-studio** — tool-calling client-side com DuckDuckGo (`ddgs`), até 5 rodadas de busca.

### Seções do roteiro

Fixas em `domain/roteiro.py` (9 seções, arquitetura narrativa):

`Gancho` · `Estake` · `Tensao` · `Virada` · `Filosofo` · `Prova` · `Espelho` · `Aplicacao` · `Fecho`

Cada seção tem `papel`, `alvo_palavras`, `abre_loop`/`fecha_loop`/`rehook` definido. A arquitetura é imutável (`frozen=True`).

### Prompts

Todos os prompts continuam em `src/forge/prompts/` (Markdown, carregados por nome via `load_prompt()`) e os skills em `src/forge/skills/` (frontmatter: `nome`, `dono`, `dominio`; seções `Critérios` / `Anti-padrões` / `Procedimento` — esta última visível apenas ao agente dono). Editar um prompt ou skill não exige mudança em código Python.

## Configuração

Variáveis com prefixo `FORGE_`, lidas de `.env` ou do ambiente (via `pydantic-settings`).

| Variável | Padrão | Descrição |
|---|---|---|
| `FORGE_PROVIDER` | `anthropic` | `anthropic` · `openai` · `lm-studio` |
| `FORGE_MODEL` | por provider | Sobrepõe o default do provider ativo |
| `FORGE_API_KEY` | — | Chave do provider ativo; vence as específicas abaixo |
| `FORGE_ANTHROPIC_API_KEY` | — | Aceita também `ANTHROPIC_API_KEY` |
| `FORGE_OPENAI_API_KEY` | — | Aceita também `OPENAI_API_KEY` |
| `FORGE_EFFORT` | `high` | Effort do output config (só `anthropic`) |
| `FORGE_MAX_REVIEW_ROUNDS` | `8` | Teto de iterações do loop de review |
| `FORGE_OUTPUT_DIR` | `output/roteiros` | Onde os roteiros são gravados |
| `FORGE_LOG_LEVEL` | `INFO` | `DEBUG` · `INFO` · `WARNING` · `ERROR` |
| `FORGE_LM_STUDIO_BASE_URL` | `http://localhost:1234/v1` | Endpoint do LM Studio |

`model` e `api_key` são resolvidos pelo provider ativo — `settings.resolved_model` e
`settings.resolved_api_key`. Sem `FORGE_MODEL`, o default é `claude-opus-4-8`
(anthropic), `gpt-5-nano` (openai) ou `qwen/qwen3.5-9b` (lm-studio). A chave de um
provider nunca é usada por outro; faltando a chave, `build_chat_model` falha com
`API key ausente para o provider '<nome>'` em vez de 401 opaco.

### LM Studio (local, sem API key)

Suba o servidor local do LM Studio na porta 1234 e rode:

```bash
uv run forge roteiro --provider lm-studio
```

## Saída

```markdown
---
tema: O paradoxo da escolha
tese: Mais opções não ampliam a liberdade; deslocam o custo da decisão.
modelo: claude-opus-4-8
timestamp: 20260719-143012
rounds: 2
aprovado: True
---

## Hook

...

## Fontes

- The Paradox of Choice — Barry Schwartz
```

## Desenvolvimento

```bash
uv run pytest              # suíte completa
uv run pytest -k research  # um módulo
```

Os testes cobrem cada estágio do writer, o grafo, storage, config e logging — todos com o modelo mockado, sem chamadas de rede. O teste de integração em `tests/test_integration.py` é gated e só roda quando as credenciais estão presentes.

### Layout atual

```
src/forge/
  agents/          tema, research, plan, write, review, midia
  orchestration/   grafo LangGraph (StateGraph, RoteiroState)
  executors/       8 executores de stage (subprocesso isolado) + base/process/retry
  executors/audio/ audio + audio_generate (tts, WAV 24kHz, seed 42)
  executors/estilo/ estilo_visual (Cosmos Interior, SDXL), comfy (client ComfyUI), imagens
  executors/video/ ffmpeg (H.264/AAC 1920x1080), montagem
  domain/          execucao (contratos), operacao (SQLite transacional),
                    roteiro (9 seções), models, midia
  llms/            model.py (anthropic, openai, lm-studio; contexto 16384; qwen3.8-27b não no preset)
  services/        catalogo (SHA-256 + MIME), reconciliacao (órfãos, is_current=false),
                    qualidade_roteiro (métricas objetivas), worker, manifesto, storage
  gpu/             broker (PID, .gpu.lock, dead-owner), liberadores (VRAM, ComfyUI shutdown)
  prompts/         markdown por nome
  skills/          markdown com frontmatter (Procedimento visível só ao dono)
  infrastructure/  config (FORGE_* env), logging
```

### Marco 3 — Executores (entregue)

Plano completo em `docs/superpowers/plans/2026-09-13-forge-studio-executors.md`. Todos os 8 executores implementados com isolamento por subprocesso (`python -m forge.executors.entrypoint`), checkpoint por item (`work_items`), catálogo de artefatos (`services/catalogo.py` com SHA-256), gates objetivos (`domain/execucao.py`) e retomada sem repetir saídas válidas (`reusable_outputs`, `reconciliacao`). Gate final (`validacao`) confirma H.264+AAC, 1920x1080, frames amostrados e zero silêncio não planejado acima do limite.

Detalhes de logging em [`docs/logging.md`](docs/logging.md). Veja também `docs/2026-09-13-marco3-status.md` para o resumo do Marco 3.

