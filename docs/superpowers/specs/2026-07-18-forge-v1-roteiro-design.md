# Forge V1 — Gerador de Roteiro — Design

> Data: 2026-07-18
> Escopo: primeira versão do forge-videos. Transforma um tema num roteiro de
> vídeo nível profissional (PT-BR), gravado em arquivo. Fundação da plataforma
> CreatorBrain (roadmap V1: "Fundação, orquestrador, skills, múltiplos LLMs").

## 1. Objetivo

`forge roteiro` produz um roteiro de vídeo completo na estrutura editorial do
doc CreatorBrain, em português, ancorado em pesquisa web verificada, passando
por um portão de revisão de qualidade antes de gravar. App Python standalone —
não depende de nenhum harness de agente. É a base horizontal sobre a qual as
fases seguintes (RAG, memória, multiagentes, multimídia) serão construídas.

## 2. Saída

Um roteiro de vídeo estruturado nas nove partes do doc, gravado como Markdown
com frontmatter YAML em `output/roteiros/<slug>-<timestamp>.md`. O caminho do
arquivo é impresso ao final.

Estrutura do roteiro (ordem fixa):

1. Hook
2. Problema
3. História
4. Explicação
5. Filósofo
6. Psicologia
7. Aplicação
8. Resumo
9. Conclusão

Nicho: filosofia, desenvolvimento pessoal e psicologia.

## 3. Entrada / Interface

CLI: `forge roteiro [--tema TEXT]`.

- Sem `--tema`: o sistema gera o tema no nicho e produz o roteiro (comportamento
  padrão, como o `ensaio-filosofico`).
- Com `--tema "..."`: usa o tema fornecido.

Sem API/servidor web nesta fase (fica para o roadmap V6).

## 4. Stack

- Python 3.12+
- uv (ambiente, deps, lockfile)
- **LangGraph** — orquestração do pipeline como grafo de estado
- **LangChain** (`langchain-core`, `langchain-anthropic`) — camada de LLM.
  `BaseChatModel` é o seam multi-provider; `ChatAnthropic` é a implementação V1.
- Pydantic v2 (`pydantic-settings` para config; modelos de dados do roteiro e
  do review)
- structlog (logging estruturado)
- pytest (testes)
- SDK Anthropic (via `langchain-anthropic`)

Modelo padrão: `claude-opus-4-8`, adaptive thinking (`{"type": "adaptive"}`),
`effort` configurável (default `high`). Pesquisa web pela ferramenta server-side
`web_search_20260209` (suportada no Opus 4.8; filtragem dinâmica embutida).

## 5. Arquitetura

Duas features separadas com fronteira limpa:

- **`writer`** — produção textual. Funções puras sobre um `BaseChatModel`
  injetado, sem nenhum conhecimento de LangGraph. Cada estágio recebe entradas
  e devolve objetos de domínio. Testável isoladamente.
- **`orchestrator`** — o grafo LangGraph. Adapta cada estágio do `writer` como
  um nó sobre o estado, fia a sequência e gerencia o loop de review + o
  disjuntor. Não contém lógica de escrita.

Pipeline linear orquestrado por um `StateGraph`:

```text
                 ┌──────────────────────────────┐
 [--tema?] → tema → research → plan → write → review
                                        ▲          │
                                        └──────────┘
                              should_continue: reprovado → write
                                               aprovado / teto → END → grava
```

Os nós `tema/research/plan/write/review` são adaptadores finos que chamam
`writer.*`. A CLI compila o grafo uma vez e o invoca.

### 5.1 Layout

```text
forge-videos/
├── pyproject.toml              # uv-managed, deps + config de ferramentas
├── uv.lock                     # lockfile versionado
├── .env                        # segredos locais (gitignored)
├── .env.example                # template versionado
├── src/forge/
│   ├── __init__.py
│   ├── config.py               # Settings (pydantic-settings)
│   ├── logging.py              # setup_logging() structlog
│   ├── cli.py                  # entrypoint `forge`
│   ├── llm/
│   │   ├── __init__.py
│   │   └── model.py            # build_chat_model(settings) -> BaseChatModel
│   ├── writer/                 # FEATURE: produção textual (sem LangGraph)
│   │   ├── __init__.py
│   │   ├── models.py           # Roteiro, Secao, Fonte, ReviewResult, Nota
│   │   ├── tema.py             # gerar_tema(model, tema=None) -> str
│   │   ├── research.py         # pesquisar(model, tema) -> (notes, fontes)
│   │   ├── plan.py             # planejar(model, tema, research) -> (tese, esboco)
│   │   ├── write.py            # escrever(model, tese, esboco, research, notas=None) -> Roteiro
│   │   ├── review.py           # revisar(model, roteiro) -> ReviewResult
│   │   └── prompts/
│   │       ├── tema.md
│   │       ├── research.md
│   │       ├── plan.md
│   │       ├── write.md
│   │       └── review.md
│   ├── orchestrator/           # FEATURE: grafo LangGraph
│   │   ├── __init__.py
│   │   ├── state.py            # RoteiroState
│   │   └── graph.py            # build_graph(model, settings); nós adaptam writer.*; should_continue
│   ├── output/
│   │   ├── __init__.py
│   │   └── storage.py          # gravar_roteiro(roteiro, settings) -> Path
│   └── py.typed
└── tests/
    ├── conftest.py             # fake BaseChatModel, settings de teste
    ├── test_config.py
    ├── writer/
    │   ├── test_tema.py
    │   ├── test_research.py
    │   ├── test_plan.py
    │   ├── test_write.py
    │   └── test_review.py
    ├── orchestrator/
    │   └── test_graph.py        # lógica do loop de review
    ├── test_storage.py
    └── test_integration.py      # opcional, atrás de env var com API key real
```

Decisão: src-layout com pacote `src/forge/`. Organização por feature (`writer`,
`orchestrator`) em vez de por camada técnica — cada feature entendível e testável
sozinha, com dependência de sentido único: `orchestrator` depende de `writer`,
nunca o contrário.

## 6. Componentes

### 6.1 config.py

`class Settings(BaseSettings)` (pydantic-settings), `env_prefix="FORGE_"`,
`env_file=".env"`, `extra="ignore"`. Campos:

- `anthropic_api_key: str | None` (lido também de `ANTHROPIC_API_KEY`)
- `model: str = "claude-opus-4-8"`
- `effort: str = "high"`
- `output_dir: Path = Path("output/roteiros")`
- `log_level: str = "INFO"`
- `max_review_rounds: int = 8` — disjuntor de segurança do loop de review

`get_settings() -> Settings` cacheada (`functools.lru_cache`).

### 6.2 logging.py

`setup_logging(level)` configura structlog (console legível em dev; timestamp,
nível, logger). Idempotente. `get_logger(name)` helper.

### 6.3 llm/model.py

`build_chat_model(settings) -> BaseChatModel`. Constrói `ChatAnthropic` com
`model`, adaptive thinking, `max_tokens` alto (streaming), `effort`. Único ponto
que conhece o provider concreto — trocar por `ChatOpenAI` / `ChatOllama` no
futuro é uma edição local. A ferramenta `web_search` é ligada dentro de
`writer.research`, não aqui.

### 6.4 Feature `writer`

Todos os estágios de produção textual. Funções puras: recebem o `model` e
entradas, devolvem objetos de domínio. Nenhuma referência a LangGraph nem ao
estado do grafo.

**writer/models.py** — modelos pydantic:

- `Fonte` — `titulo`, `autor`, `url`, `frase` (opcional, só se confirmada).
- `Secao` — `nome` (uma das nove partes), `conteudo`.
- `Roteiro` — `tema`, `tese`, `secoes: list[Secao]`, `fontes: list[Fonte]`.
- `Nota` — `dimensao`, `problema`, `sugestao`.
- `ReviewResult` — `aprovado: bool`, `notas: list[Nota]`.

**writer/tema.py** — `gerar_tema(model, tema=None) -> str`. Se `tema` vier, o
retorna; senão gera um tema discutível no nicho.

**writer/research.py** — `pesquisar(model, tema) -> tuple[str, list[Fonte]]`.
Usa `model.bind_tools([web_search])`; confirma fatos e citações na web. Aplica
as regras anti-fabricação do `ensaio-filosofico`: **padrão zero aspas; aspa só
com frase + autor + obra confirmados por busca.**

**writer/plan.py** — `planejar(model, tema, research) -> tuple[str, str]`. Deriva
`tese` (afirmação discutível) e `esboco` mapeado nas nove partes; cada movimento
avança a tese.

**writer/write.py** — `escrever(model, tese, esboco, research, notas=None) ->
Roteiro`. Escreve o roteiro completo. Nas reescritas, recebe `notas` pendentes
do review.

**writer/review.py** — `revisar(model, roteiro) -> ReviewResult`. Usa
`model.with_structured_output(ReviewResult)`; avalia as dimensões do doc (fato,
clareza, retenção, coesão, repetição).

**writer/prompts/*.md** — um prompt por estágio, carregados em runtime. O
`research.md` incorpora as regras de citação do
`.pi/skills/ensaio-filosofico/SKILL.md` (fonte da verdade a copiar: seção "Regra
de citação"). Prompts em arquivo mantêm o código limpo e facilitam iteração.

### 6.5 Feature `orchestrator`

**orchestrator/state.py** — `RoteiroState` (pydantic/TypedDict):

- `tema: str | None`
- `research_notes: str`
- `fontes: list[Fonte]`
- `tese: str`
- `esboco: str`
- `roteiro: Roteiro | None`
- `review: ReviewResult | None`
- `rounds: int`

**orchestrator/graph.py** — `build_graph(model, settings) -> CompiledGraph`.
Cada nó é um adaptador fino que chama a função `writer.*` correspondente e
devolve a fatia do estado:

- `node_tema` → `writer.gerar_tema`
- `node_research` → `writer.pesquisar`
- `node_plan` → `writer.planejar`
- `node_write` → `writer.escrever` (passa `state.review.notas` nas reescritas)
- `node_review` → `writer.revisar`; incrementa `rounds`
- `should_continue(state) -> "write" | END` — aresta condicional após review:
  `aprovado` **ou** `rounds >= max_review_rounds` → `END`; senão → `write`.

Fia `tema → research → plan → write → review` e liga a aresta condicional.
Ao bater o teto sem aprovar, entrega a melhor versão + notas pendentes e loga
warning. O teto não limita a qualidade — é rede contra loop infinito/custo.

### 6.6 output/storage.py

`gravar_roteiro(roteiro, settings) -> Path`. Serializa em Markdown: frontmatter
YAML (tema, tese, timestamp, modelo, rounds, fontes) + corpo com as nove seções.
Slug a partir do tema; nome `output/roteiros/<slug>-<timestamp>.md`. Cria o
diretório se faltar.

### 6.7 cli.py

Entrypoint `forge` (definido em `pyproject.toml [project.scripts]`). Subcomando
`roteiro [--tema TEXT]`: lê settings, `setup_logging`, `build_chat_model`,
`build_graph`, invoca com estado inicial, grava via `output.storage`, imprime o
caminho.

## 7. Testes (TDD)

Um `BaseChatModel` falso injetável (respostas roteirizadas) deixa tudo
determinístico e sem rede:

- `test_config.py` — defaults, leitura de `.env`, cache de `get_settings`.
- `writer/test_*.py` — cada estágio produz o objeto de domínio esperado dado um
  model falso; `gerar_tema` respeita `--tema` fornecido; `revisar` faz parse do
  `ReviewResult`.
- `orchestrator/test_graph.py` — lógica do loop: aprova na primeira volta;
  aprova após N voltas; bate `max_review_rounds` e encerra entregando a melhor
  versão. Usa writer falso ou model falso.
- `test_storage.py` — frontmatter e as nove seções na ordem certa; slug/caminho.
- `test_integration.py` — opcional, roda o grafo real contra a API se
  `FORGE_ANTHROPIC_API_KEY` estiver setada (senão, `skip`).

## 8. Fora de escopo (fases seguintes)

RAG e banco vetorial (V2), memória de longo prazo, multiagentes autônomos (V3),
aprendizado contínuo (V4), TTS/imagem/vídeo (V5), thumbnail, SEO, descrição,
publishing, API/web (V6), e qualquer provider de LLM além do Anthropic (o seam
`BaseChatModel` já deixa isso pronto sem custo).

## 9. Critério de Pronto

- `uv sync` cria `.venv` e instala deps (incl. langgraph, langchain-core,
  langchain-anthropic) sem erro.
- `uv run pytest` passa todos os testes (unitários, sem rede).
- `forge roteiro --tema "..."` gera um `.md` válido em `output/roteiros/` com as
  nove seções e frontmatter.
- `.env.example` documenta todas as variáveis suportadas.
- O loop de review encerra sempre — por aprovação ou pelo disjuntor.

## 10. Riscos / a validar na implementação

- Compatibilidade de `ChatAnthropic` com adaptive thinking + `web_search`
  server-side + `with_structured_output` na mesma cadeia. Validar cedo; se
  algum combo não fluir, isolar o review (structured output) numa chamada
  separada do research (tools).
- Custo do loop de review sem limite fixo. O disjuntor `max_review_rounds`
  cobre o pior caso; monitorar rounds típicos e ajustar o default se preciso.
