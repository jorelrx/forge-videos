# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**CreatorBrain / forge-videos** — a LangGraph pipeline that generates Portuguese video scripts (roteiros) for the YouTube channel **Conquistas Cósmicas**. From a theme (or none — it picks one the acervo can support), it researches the acervo, plans a thesis, writes a 9-section long-form script, iterates with a reviewer agent until approved, and emits the publishing package (titles, thumbnail concept, description, chapters, tags).

> Note: `README.md` describes an older module layout (`writer/`, `orchestrator/`, `llm/`, `output/`). The current tree is `agents/`, `orchestration/`, `llms/`, `services/`, `prompts/`. Trust the code, not the README, for structure.

## Commands

```bash
uv sync                                  # core deps

uv run forge temas --n 5                 # themes the acervo supports, ranked by appeal
uv run forge roteiro                     # theme picked by the selector (top suggestion)
uv run forge roteiro --tema "..."        # fixed theme
uv run forge roteiro --provider lm-studio
uv run forge roteiro --retomar output/runs/<ts>-<slug>   # resume a prior run from disk
uv run forge auth youtube login          # one-time Google login for publishing
uv run forge publicar output/runs/<id> --titulo 1 [--agendar 2026-11-21T18:00-03:00]

uv run pytest                            # full suite (model mocked, no network)
uv run pytest -k research                # one module
uv run pytest tests/agents/test_write.py::test_name   # single test
```

`roteiro` prints the output path to stdout and per-node progress (`[tema]`, `[research]`, ...) plus the run dir to stderr. Config comes from `FORGE_`-prefixed env vars / `.env` (see `infrastructure/config.py`). Minimum to run anthropic: `FORGE_ANTHROPIC_API_KEY`.

## Architecture

### The graph ([orchestration/graph.py](src/forge/orchestration/graph.py))

A LangGraph `StateGraph` over shared `RoteiroState` (a `TypedDict`, [orchestration/state.py](src/forge/orchestration/state.py)):

```
tema → research → plan → write → review → (conditional)
```

`rotear()` decides after each review:
- `review.verificar` non-empty → **research** (fact-check handoff: reviewer flagged claims needing verification)
- `review.aprovado` → END
- else, under `max_review_rounds` → **write** (revise using review notes)
- `passos >= max_passos` → END (hard budget cap on total steps, independent of the review-round cap)

`write` can *also* jump straight back to research via `Command(goto="research")` when the model sets `falta_pesquisa` — the material doesn't support a section. So research is re-entered from two places, and it merges directed follow-up briefs into the accumulated `research_notes` rather than replacing them.

**Two counters, two limits:** `rounds` counts review iterations (`max_review_rounds`, default 8); `passos` counts every node execution (`max_passos`, default 20) and is the backstop against runaway loops.

`plan` also classifies the theme into one of the channel's four `eixo`s (or none); the value rides in the state, in the plan artifact's frontmatter, and through `--retomar`.

`write` makes **one model call per section**, not one for the whole script: asked for ~2,000 words at once the model shortens the text and the word-for-word check between `conteudo` and `blocos` fails more often. Each call gets the section's role, word target and the sections already written. On a revision round only the sections named in the reviewer's notes (`Nota.secao`) are rewritten; the rest pass through untouched. That targeted path requires a previous script with all nine sections **and the same thesis** — after a research loop the plan is redone and everything is rewritten. A note without a valid section name is a general note and also rewrites everything, never silently dropped.

### Agent contract ([agents/](src/forge/agents/))

Each stage module (`tema`, `research`, `plan`, `write`, `review`) exports:
- `LE` — the list of state keys the agent reads. `com_wrapper` in graph.py narrows the full state down to `LE` before calling the node, so agents can't accidentally depend on unlisted state.
- a pure function doing the LLM work.

`com_wrapper` also writes the stage's artifact to disk and increments `passos`. A node returning a dict with `_raw` gets that written as a `.raw.md` sidecar (unparsed model output).

### Run artifacts & resume ([services/artefatos.py](src/forge/services/artefatos.py))

Every stage writes a numbered markdown file (`00-tema.md`, `01-research.md`, `03-write-r1.md`, ...) into `output/runs/<ts>-<slug>/`. `--retomar` reconstructs `RoteiroState` by parsing these back and returns the first pending stage. Subtleties encoded here (with comments explaining why): write/review files are numbered by counting existing files, not by `rounds`; `-r10` sorts after `-r2` by parsed round number, not lexically; section parsing is restricted to the closed set `SECOES_NOMES` so a stray `##` in prose can't create a phantom section. The final approved script is rendered separately by [services/storage.py](src/forge/services/storage.py) into `output/roteiros/`.

### Providers ([llms/model.py](src/forge/llms/model.py), [infrastructure/config.py](src/forge/infrastructure/config.py))

Providers: `anthropic` (API key), `openai`, `lm-studio`, `codex` (ChatGPT subscription) and `claude` (Claude subscription). `settings.resolved_model` / `settings.resolved_api_key` pick model + key for the *active* provider. Keys never cross providers — a missing key fails with an explicit `API key ausente para o provider '<name>'` instead of an opaque 401 downstream.

`claude` ([services/claude_cli.py](src/forge/services/claude_cli.py), [llms/claude.py](src/forge/llms/claude.py)) only goes through the official `claude -p`: the subscription OAuth token must not be used outside Anthropic's tools. Each call runs with `--safe-mode --strict-mcp-config --tools ""` in an empty dir under `%TEMP%/forge-claude/` — outside the repo on purpose, since the CLI walks up looking for CLAUDE.md — so the user's CLAUDE.md, hooks, plugins and MCP never reach the script prompt. A lone user message goes raw (not JSON), an empty system prompt becomes a neutral one, the system prompt goes by file (Windows command-line limit), and every `*_API_KEY` plus the parent session's `CLAUDECODE`/`CLAUDE_CODE_*` markers are stripped so billing stays on the subscription. A truncated structured answer raises `llm_output_truncated` at once: the CLI ignores `max_tokens`, so the budget-doubling retry would only repeat the call. `review_provider='lm-studio'` is rejected (the broker only manages the main provider's VRAM). Errors are decided by `is_error`, never `subtype` (an auth failure arrives as `subtype: "success"`). `claude auth status` can say `loggedIn` with a dead refresh, so the preflight makes one real minimal call (`ClaudeCLI.sondar`); the dashboard health probe only reads `auth status`, to not spend quota on every poll. Fix an expired session with `claude auth login` in a terminal.

`FORGE_REVIEW_PROVIDER` (+ optional `FORGE_REVIEW_MODEL`) runs the `review` node on a different provider than the writer (`build_review_model`, `build_graph(..., revisor=)`); a model reviewing its own text tends to approve it. Equal to `provider` or empty = one model. `FORGE_MODEL` belongs to the writer and never leaks to the reviewer. A pesquisa não depende mais do provider: todo provider passa pelo mesmo caminho, o acervo. O que varia entre providers é só o modelo e a chave.

### Prompts & skills

- **Prompts** ([prompts/](src/forge/prompts/)) are markdown loaded by name via `load_prompt()`. Editing a prompt needs no Python change.
- **Skills** ([skills/](src/forge/skills/)) are markdown with frontmatter (`nome`, `dono`, `dominio`) and sections `Critérios` / `Anti-padrões` / `Procedimento`. `load_skills()` injects them into prompts. Key rule: the **`Procedimento` section is only shown to the owning agent** (`dono`) — it's the boundary between what a *producer* agent sees and what a *reviewer* must not. An unrecognized section title raises rather than passing silently.

### Canal: Conquistas Cósmicas

The pipeline serves one channel; there is no multi-channel abstraction. Identity enters through the existing markdown mechanisms:

- [skills/canal.md](src/forge/skills/canal.md) — voice (second person, calm, no hype), soft CTA only in Espelho and Fecho. Loaded by `plan`, `write` and `review`.
- `skills/conquistas-cosmicas/references/<eixo>.md` — one reference per editorial axis (`EIXOS` in [skills/loader.py](src/forge/skills/loader.py)), loaded by `carregar_eixo`. It guides writing and lists common false attributions; it is **not** evidence — only an acervo passage is. `SKILL.md` and `scripts/` in that folder are the original manual flow and are not read by the pipeline.
- [domain/roteiro.py](src/forge/domain/roteiro.py) — section word targets sum to 1,600–2,450 (11–16 min at 150 wpm). [services/qualidade_roteiro.py](src/forge/services/qualidade_roteiro.py) adds retention gates: total under 1,500 words and a Gancho opening with a greeting or "neste vídeo" are blocking; a subscribe/like request outside Fecho is a warning.

**Theme selector** ([agents/tema.py](src/forge/agents/tema.py)): the model proposes candidates framed by viewer pain, code runs each candidate's queries against the acervo, and a second call judges — with the excerpts in hand — which are truly supported and how appealing they are. A candidate needs a `sustentado` verdict and at least `research_min_sources` passages. No supported candidate raises `SemTemaSustentado`; a theme is never invented. Axes with no surviving candidate are reported as uncovered — that is the cue to ingest books in the `research` project.

**Citations** ([services/citacoes.py](src/forge/services/citacoes.py)): the acervo's books are in English and German, the narration in Portuguese. `CitacaoLiteral.traducao` lets a block quote its own translation: `trecho` (original) must be in the passage, `traducao` must be in the spoken text, and the narration announces it as a free translation. `video/citacoes.json` is derived by code from the structured blocks plus passages — no model call — with type `literal`, `traducao` or `parafrase`.

**Packaging** ([agents/embalagem.py](src/forge/agents/embalagem.py)): only for an approved script, with the model still resident. One model call proposes titles, thumbnail text and prompt, description opening, chapter labels and tags; code assembles what is fact — chapter times (estimated from word count until real audio durations exist), sources from `citacoes.json`, and the pinned comment (Espelho's closing question). [services/qualidade_embalagem.py](src/forge/services/qualidade_embalagem.py) enforces YouTube's limits; a rejected package gets one retry with the findings in the prompt. In the CLI a failed package never fails the command. In the Studio it runs inside the `plano_midia` stage, **before** the media plan, so a rejected title does not cost the beat calls; rejection fails the stage with `packaging_gate_failed`. Outputs: `video/embalagem.json` and `embalagem.md`. The montage later replaces the estimated chapter times with real ones (`aplicar_tempos_reais`).

### Acervo ([services/acervo.py](src/forge/services/acervo.py))

A pesquisa não usa a web. Um serviço externo, `acervo`
(`FORGE_ACERVO_URL`, default `http://127.0.0.1:8000`), indexa livros de domínio
público e devolve passagens com caminho canônico estável (`PassageOut.path`) —
é esse caminho que o roteiro cita. O forge só consome: ingestão de livros é do
acervo (`POST /books/{book_id}/ingest`), não daqui.

Acervo fora do ar levanta `AcervoIndisponivel`. Não existe fallback para busca
web: um fallback silencioso reintroduziria exatamente a fonte não-citável que
este desenho elimina.

Depois da busca, um juiz de relevância (`FORGE_JUIZ_RELEVANCIA`, ligado por
padrão) decide quais passagens realmente respondem — busca semântica devolve
pontuação alta para material fora de assunto. Ele julga contra as queries e,
no handoff `review → research`, contra o `pedido` dirigido; não contra o tema
nu. Uma chamada por pesquisa, com o pool fundido: a atribuição de lacuna por
query é aproximada por isso, e `_julgar_e_registrar` diz onde.

O juiz é opcional e o roteiro não é. Chamada que estoura mantém todas as
passagens e não registra lacuna nenhuma; um veredicto que reprova um pool de
uma dúzia ou mais inteiro é lido como juiz quebrado, não como lacuna
(`POOL_MINIMO_PARA_DESCONFIAR_DO_JUIZ`) — sem esse piso, um veredicto ruim
produzia roteiro sem fonte alguma.

Os dois arquivos de realimentação ([services/lacunas.py](src/forge/services/lacunas.py))
não recebem os mesmos casos. `unanswered_questions.txt` é do acervo (só a
pergunta, deduplicada — aquele projeto lê o arquivo de volta), e só recebe a
rejeição do juiz, que é a única lacuna que o acervo não detecta sozinho: a
busca que não casa com nada ele já registra ele mesmo. A evidência completa de
todos os casos vai para `respostas_ruins.jsonl` ao lado. O append à pergunta
vai sob `FileLock` — no Windows o modo `a` não é atômico entre processos — e
nenhuma das duas escritas pode derrubar o roteiro.

### Vídeo: broker, plano de mídia e manifesto

`forge roteiro` grava, além do roteiro, `<run>/video/midia.json` — os blocos de
narração com tags de controle do TTS e um prompt de imagem por beat visual. É o
último artefato que exige LLM.

Os blocos de narração são cortados por código
([narracao/fatiar.py](src/forge/narracao/fatiar.py)), não pelo modelo: fatiar é
operação determinística, e pedi-la a um LLM custou, uma vez, 85 palavras de um
roteiro de 1079. A rubrica de cena entre parênteses e a ênfase markdown são
retiradas — nenhuma das duas é narração. `_conferir_cobertura` recusa o plano
cujos blocos não reproduzam o roteiro palavra por palavra.

O modelo é chamado uma vez por seção e só para propor os beats de imagem,
recebendo os blocos já prontos e a rubrica do autor como semente visual.

[gpu/broker.py](src/forge/gpu/broker.py) mantém **um** consumidor de GPU
residente por vez (`llm`, `tts`, `imagem`), com lock de arquivo em
`output/.gpu.lock`. A troca acontece por fase, nunca por item. Os liberadores
reais estão em [gpu/liberadores.py](src/forge/gpu/liberadores.py) e confirmam a
VRAM de volta antes de devolver o slot.

**TTS** ([executors/audio.py](src/forge/executors/audio.py),
[executors/audiocpp_server.py](src/forge/executors/audiocpp_server.py)): a etapa
de áudio sobe um `audiocpp_server` residente (o Higgs carrega uma vez, ~8 s na
RX 580) e faz um pedido HTTP por trecho, com as sementes `tts_seed`, 1042, 2042.
Trecho que esgota as sementes na GPU vai para uma thread de CPU com servidor
próprio, em paralelo — a GPU segue nos trechos seguintes; só a thread principal
emite eventos. Queda ou OOM do servidor reinicia o processo uma vez por
backend; erro 500 genérico falha o trecho na hora. Armadilha do contrato:
`voice_ref`/`reference_text` vão no nível de cima do JSON — dentro de `options`
o servidor os ignora e devolve 200 com voz não clonada; cada subida faz uma
sonda que exige 500 para um `voice_ref` inexistente. Os PIDs ficam em
`output/.tts-servidor.json`, e `liberar_tts` encerra o servidor órfão (só se a
linha de comando ainda for `audiocpp_server`).

[services/manifesto.py](src/forge/services/manifesto.py) dá estado próprio a cada
bloco e cada beat; [services/runner.py](src/forge/services/runner.py) consome os
pendentes agrupados por tipo, tomando o slot uma vez por grupo e regravando o
manifesto depois de cada item. Os executores de áudio e imagem entram por
injeção.

### Acabamento do vídeo (montagem e imagens)

Nenhuma etapa nova no Studio: a montagem e as imagens ganharam o acabamento, e
nada disso chama modelo. [services/linha_tempo.py](src/forge/services/linha_tempo.py)
dá o início e o fim reais de cada bloco a partir dos WAVs; cartões, legenda e
capítulos leem dela, para nunca discordarem do áudio.

- **Crossfade** ([executors/ffmpeg.py](src/forge/executors/ffmpeg.py),
  `crossfade_videos`): cada clipe leva `crossfade_segundos` a mais (menos o
  último) e um passe único encadeia `xfade` com offset na duração nominal
  acumulada — a linha do tempo fica igual à da narração. Preto só na abertura e
  no fim. O grafo vai em arquivo (`-/filter_complex`) por causa do limite de
  linha de comando do Windows.
- **Trilha** ([services/trilha.py](src/forge/services/trilha.py)): faixa de
  `FORGE_TRILHAS_DIR` (subpasta do eixo tem preferência), escolhida pelo hash do
  id da run. `mix_audio` normaliza a voz a −14 LUFS e abaixa a trilha sob ela
  (`sidechaincompress`). `<faixa>.txt` vira `Música: ...` na descrição. O
  pipeline não baixa nem gera música: licença é do usuário. `narration.wav`
  continua sendo a voz pura — a validação mede nela.
- **Cartões de fonte** ([services/cartoes.py](src/forge/services/cartoes.py)):
  `video/cartoes.ass`, queimado no passe de crossfade. Só aparece o que
  `citacoes.json` resolve; caminho sem entrada não gera cartão. Paráfrase vira
  rodapé quando a obra muda ou na primeira citação da seção; literal/tradução
  até 220 caracteres ocupa a tela.
- **Legenda** ([services/legendas.py](src/forge/services/legendas.py)):
  `video/legendas.srt`, por frase, tempo repartido por caracteres dentro do
  bloco. Não é queimada. É a única peça do acabamento que reprova a montagem.
- **Thumbnail** ([services/thumbnail.py](src/forge/services/thumbnail.py)): a
  etapa de imagens gera a base pelo provider e desenha o texto por código
  (Pillow) em `video/thumbnail.jpg`, 1280×720, abaixo de 2 MB. Não é item do
  plano: falha vira o aviso `thumbnail_ausente`.

Trilha, cartões, thumbnail e capítulos reais nunca derrubam a etapa: viram
achados num gate aprovado (`trilha_ausente`, `cartoes_ausentes`,
`capitulos_estimados`). A aba Publicação do painel
([web/components/publication.tsx](web/components/publication.tsx)) lê esses
artefatos; `GET /artifacts/{id}/content?download=1` responde com
`Content-Disposition`, porque painel e API ficam em portas diferentes.

### Publicação no YouTube ([services/publicacao.py](src/forge/services/publicacao.py))

`forge publicar <run>` ou o botão da aba Publicação sobem uma run aprovada
pela YouTube Data API ([services/youtube.py](src/forge/services/youtube.py),
httpx puro) com o login OAuth
([services/youtube_auth.py](src/forge/services/youtube_auth.py), PKCE em
loopback com o cliente OAuth desktop do próprio usuário). O Google fixa o canal
na tela de login, então há um token por canal
([services/youtube_canais.py](src/forge/services/youtube_canais.py),
`FORGE_YOUTUBE_CANAIS_DIR`); o painel envia o JSON do cliente e dispara o login
pela API (`/api/youtube`, callback em loopback numa thread da API — painel e
API na mesma máquina). A retomada usa o canal gravado no estado. Sempre privado
ou agendado. `video/publicacao.json` é o estado: a retomada reusa a sessão de
upload retomável e nunca sobe um segundo vídeo; thumbnail e legenda recusadas
viram aviso. No painel o envio roda numa thread da API (`Publicador`), fora do
worker e da máquina de estados — a run já terminou. Projeto do Google Cloud sem
auditoria deixa o vídeo travado em privado: limite do Google, não do código.

## Response style

- **Always keep caveman mode active** in your responses to the user (terse, drop articles/filler/pleasantries/hedging; fragments OK). This holds even while a Superpowers skill (brainstorming, systematic-debugging, TDD, etc.) is driving the workflow — run the skill's process *and* keep the caveman voice; they stack, one does not disable the other.
- Caveman applies only to prose addressed to the user. Code, commits, PRs, docs (like this file), and security/destructive-action warnings stay written normally.
- Preserve the user's dominant language: user writes Portuguese → reply Portuguese caveman.

## Conventions

- Domain/state names and log messages are Portuguese; code identifiers mix Portuguese and English. Match the surrounding file.
- Structured logging via `structlog` — `get_logger(__name__)`, key=value fields, never f-strings in log calls.
- Tests mock the model and hit no network; `tests/test_integration.py` is gated on real credentials being present.
