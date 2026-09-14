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
# API (FastAPI)
uv run forge-api

# Dev web (Next.js)
npm run dev --prefix web

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

## Forge Studio (operação local)

O Studio é local e de usuário único: API em `127.0.0.1:8765`, web em `127.0.0.1:3100`. `data/forge.db` é a fonte de verdade operacional.

```powershell
# verifica a máquina e aplica a migração SQLite (não inicia nada)
uv run forge-studio-doctor --migrate

# inicia API, worker e web; abre o dashboard no navegador
.\scripts\start-studio.ps1

# encerra: pede pausa cooperativa antes de derrubar o que sobrou
.\scripts\stop-studio.ps1 -GraceSeconds 30

# importa apenas histórico; a origem é copiada, nunca movida nem apagada
uv run forge-import-runs C:\caminho\output\runs --children
```

Parâmetros do launcher:

| Parâmetro | Efeito |
|---|---|
| `-NoBrowser` | não abre o dashboard |
| `-WebMode production` | usa `next start` em vez de `next dev` |
| `-Force` | ignora um estado vivo e reinicia (a validação de linha de comando continua valendo) |
| `-GraceSeconds <1..300>` | prazo da pausa cooperativa no stop |

**Arquivos de estado.** PIDs, logs e banco ficam sob `data/studio/` — nunca em `output/runs/`. O stop só encerra árvores cujos PIDs e linhas de comando pertençam ao Studio; um PID reciclado por outro programa não é morto.

**Runs importadas são somente-leitura.** Não entram na fila, não aceitam pause/resume/retry (a API responde 409) e não têm artefatos invalidados. A importação **não** atesta os gates de qualidade antigos: os arquivos entram com `gate_status=imported_unverified`.

**O doctor não inicia Docker.** Serviços externos indisponíveis aparecem como `warning` com a ação concreta; um pré-requisito de binário ou caminho ausente é `failed` e o launcher se recusa a subir meio Studio.

### Testes de integração (opt-in)

A suíte padrão (`uv run pytest`) mantém `-m not integration` e não toca rede nem GPU.

```powershell
# provas reais contra research, LM Studio, TTS, ComfyUI, FFmpeg e broker
$env:FORGE_RUN_INTEGRATION=1
uv run pytest tests/integration -m integration -ra

# run completa: produz e valida um vídeo de verdade (exige também a flag abaixo)
$env:FORGE_RUN_STUDIO_E2E=1
uv run pytest tests/integration/test_studio_e2e.py -m integration -ra
```

Um serviço fora do ar vira `SKIP` com o endpoint/caminho exato e a ação para corrigir — nunca `PASS` sem chamada. Use `$env:FORGE_KEEP_INTEGRATION_OUTPUT=1` para preservar o diretório temporário da run.

### Ordem obrigatória na GPU

Nesta máquina (RX 580 8 GB) os consumidores não cabem juntos: **LLM → TTS → ComfyUI → ffmpeg**. O broker ([`gpu/broker.py`](src/forge/gpu/broker.py)) mantém um residente por vez e troca por fase. Duas consequências práticas:

- o TTS exige o LLM descarregado — com o modelo carregado no LM Studio o `audiocpp_cli` falha com `ErrorOutOfDeviceMemory`;
- o ComfyUI precisa ser **encerrado** (não apenas `/free`) antes do TTS, porque o processo segura o heap Vulkan. Por isso o slot de imagem o sobe de novo (`FORGE_COMFY_AUTO_START`, ligado por padrão).

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

