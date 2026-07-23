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
| `tema` | `writer/tema.py` | Usa o tema recebido, ou pede um ao LLM |
| `research` | `writer/research.py` | Pesquisa na web e extrai `Fonte`s citáveis |
| `plan` | `writer/plan.py` | Produz `tese` + `esboco` |
| `write` | `writer/write.py` | Escreve as seções; reaproveita as notas do review anterior |
| `review` | `writer/review.py` | Devolve `aprovado: bool` + `notas` estruturadas |

O loop volta para `write` enquanto o review reprovar, até o teto de `FORGE_MAX_REVIEW_ROUNDS` (padrão: 8). O estado compartilhado está em `orchestrator/state.py`.

### Pesquisa web

Duas estratégias, escolhidas pelo provider:

- **anthropic** — ferramenta `web_search` server-side, executada pela própria API.
- **openai / lm-studio** — tool-calling client-side com DuckDuckGo (`ddgs`), até 5 rodadas de busca.

### Seções do roteiro

Fixas em `writer/models.py`:

`Hook` · `Problema` · `História` · `Explicação` · `Filósofo` · `Psicologia` · `Aplicação` · `Resumo` · `Conclusão`

### Prompts

Todos os prompts vivem como Markdown em `src/forge/writer/prompts/` e são carregados por nome via `load_prompt()`. Editar um prompt não exige tocar em código Python.

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

### Layout

```
src/forge/
  agents/          tema, research, plan, write, review
  orchestration/   grafo LangGraph e estado compartilhado
  llms/            providers (anthropic, openai, lm-studio) e parsing
  knowledge/       camada Knowledge — ver docs/knowledge.md
  prompts/         markdown carregado por nome
  skills/          markdown com frontmatter, injetado nos prompts
  services/        artefatos de run e escrita do roteiro final
  domain/          modelos do roteiro
  infrastructure/  config e logging
```

Detalhes de logging em [`docs/logging.md`](docs/logging.md).
