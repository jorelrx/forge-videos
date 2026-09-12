# Pipeline de vídeo: acervo, narração, imagens e gerência de GPU

Data: 2026-09-06
Estado: aprovado para planejamento

## Problema

O forge hoje para no roteiro em markdown. O objetivo é entregar um MP4: roteiro
ancorado em fontes reais, narrado, ilustrado e montado.

Três restrições moldam todo o desenho:

1. **A pesquisa web sai de cena.** Uma API local (`acervo`) indexa livros de
   domínio público e devolve passagens citáveis com caminho canônico estável. Ela
   substitui a busca web — não a complementa.
2. **Uma GPU, três consumidores.** RX 580 de 8 GB (gfx803: sem ROCm, sem PyTorch
   CUDA). Disputam a placa o LLM local (LM Studio), o TTS (higgs-tts-3-4b GGUF Q8
   via Vulkan, ~4,5 GB) e o SDXL do ComfyUI (DirectML, ~6 GB). Nenhum par cabe
   junto.
3. **A fase de imagem é longa e frágil.** 30-50 imagens por vídeo, e o ComfyUI
   crasha se a VRAM não for liberada entre gerações. Perder o trabalho no item 33
   é inaceitável.

## Ambiente verificado

Levantado nesta máquina em 2026-09-06, não presumido:

| Peça | Estado |
|---|---|
| `acervo` | no ar em `http://127.0.0.1:8000`, 14 livros ingeridos (Nietzsche, Kant, determinismo, freethought) |
| LM Studio | no ar em `:1234`; `GET /api/v0/models` reporta `state`; CLI `lms` em `~/.lmstudio/bin/lms.exe` |
| ComfyUI | `C:\Program Files\StabilityMatrix-win-x64\Data\Packages\ComfyUI`, torch 2.4.1+cpu + `torch_directml`, checkpoints SDXL, workflows verticais 432x768 |
| `audiocpp_cli.exe` | backend vulkan, RTF 2,11x; caminho CPU (PyTorch bfloat16) a 16,4x |
| ffmpeg | 8.1.2 no PATH |
| RAM | 32 GB |

Endpoints do acervo em uso: `GET /search` (devolve `PassageOut` com `path`,
`book_id`, `book_title`, `authors`, `breadcrumb`, `text`, `url`, `score`),
`GET /discover`, `GET /health`.

Contratos do ComfyUI em uso: `POST /prompt`, `GET /history/{id}`,
`GET /system_stats`, `POST /free` com `{"unload_models": true, "free_memory": true}`
(confirmado em `server.py:1192`).

## Decisões

**D1 — O acervo substitui a web.** Sem fallback para DuckDuckGo ou `web_search`.
Acervo fora do ar é erro explícito. Um fallback silencioso reintroduziria
exatamente a fonte não-citável que este desenho elimina.

**D2 — As fontes deixam de ser inferidas por LLM.** Hoje `_extrair_fontes` faz um
LLM reler o brief e reconstruir a lista de fontes; é onde nascem citações
inventadas. Com o acervo, `Fonte` vem estruturada da resposta HTTP. A função morre.

**D3 — Geração de vídeo é processo separado, consumindo o roteiro pronto.**
`forge roteiro` entrega o roteiro aprovado e mais o plano de mídia (S3) — o plano
sai junto porque é a última coisa que exige LLM, e emiti-lo ali evita recarregar o
modelo depois. `forge video <run>` lê esses artefatos do disco e produz o MP4, sem
nenhuma chamada de LLM. Retomada por item.

**D4 — Broker de GPU com slot exclusivo, trocado por fase.** Um recurso residente
por vez. Trocar por item pagaria dezenas de reloads de modelo.

**D5 — Manifesto persistente por item.** Cada trecho de áudio e cada imagem é uma
linha com estado próprio, gravada após cada item. É o que torna 40 imagens numa
RX 580 uma operação retomável em vez de um all-or-nothing de horas.

**D6 — `/free` antes de cada imagem.** Contraria D4 na aparência, não no fundo: o
slot continua sendo da fase de imagem inteira; o `/free` interno descarrega o
checkpoint entre prompts. Sem isso o ComfyUI crasha no meio da fase. O custo é um
reload de checkpoint por imagem.

**D7 — Backend de TTS configurável, e é ele que decide se há paralelismo.**
`vulkan` toma o slot de GPU; `cpu` não toma nada, liberando a fase de narração
para rodar concorrente com a de imagens. Ver "Questão em aberto" abaixo.

## Sub-projetos

Ordem de construção. Cada um é entregável e testável sozinho.

| # | Nome | Depende de |
|---|---|---|
| S0 | Pontas soltas da camada `knowledge` | — |
| S1 | Research via acervo | S0 |
| S2 | Broker de GPU | — |
| S3 | Plano de mídia (fase LLM) | S1 |
| S4 | Manifesto e runner | S2 |
| S5 | Narração (TTS) | S3, S4 |
| S6 | Imagens (ComfyUI) | S3, S4 |
| S7 | Montagem (ffmpeg) | S5, S6 |

Antes de S0 roda um spike de medição (ver "Questão em aberto").

### S0 — Pontas soltas da camada `knowledge`

A pasta `src/forge/knowledge/` já foi removida do working tree. Sobraram
referências que quebram o CLI:

- `cli.py:45` e `cli.py:90` — subcomando `ingest` importando `forge.knowledge.ingest`;
  `forge ingest` hoje levanta `ModuleNotFoundError`. Remover o subcomando.
- `infrastructure/config.py:15` — `KnowledgeSettings` e `knowledge_enabled`. Remover.
- `pyproject.toml:21` — extras `knowledge`, `books`, `ocr`. Remover.
- `tests/knowledge/` — testes do módulo ausente. Remover.
- `docker-compose.yml` — Qdrant, Neo4j, Postgres. Remover; o acervo é dono dos
  seus próprios stores.
- `CLAUDE.md` — reescrever a seção "Knowledge layer" apontando para o acervo.
- `docs/knowledge.md` — marcar como histórico ou remover.

Ingestão de livros passa a ser responsabilidade do acervo
(`POST /books/{book_id}/ingest`), fora do forge.

### S1 — Research via acervo

**Novo `services/acervo.py`** — cliente HTTP puro, sem LLM:

```python
def buscar(q: str, *, top: int, excerpt: int, rerank: bool, neighbours: bool) -> list[Passagem]
def descobrir(q: str) -> list[Candidato]
def saude() -> bool
```

`Passagem` é um modelo Pydantic espelhando `PassageOut`.

**`agents/research.py` reescrito.** Some a bifurcação server-side/client-side e a
dependência `ddgs`; a pesquisa passa a ser idêntica em todo provider. Fluxo:

1. LLM converte `tema` (ou `pedido`, na reentrada dirigida do reviewer) em 3-5
   queries de busca.
2. Uma chamada `GET /search` por query.
3. Passagens deduplicadas por `path`, ordenadas por `score`.
4. LLM sintetiza o brief citando `path` canônico.
5. `fontes` sai direto das passagens — sem passo de extração.

`Fonte` ganha `path: str` e `book_id: int`. `titulo`/`autor` passam a vir de
`book_title`/`authors`.

Acervo sem resultado relevante: o brief registra a lacuna explicitamente e a
resposta inclui as sugestões de `/discover`, para o usuário decidir ingerir. O
agente nunca preenche a lacuna de memória.

Novas configurações: `FORGE_ACERVO_URL` (default `http://127.0.0.1:8000`),
`FORGE_ACERVO_TOP`, `FORGE_ACERVO_TIMEOUT`.

### S2 — Broker de GPU

**Novo `gpu/broker.py`.** Três recursos nomeados: `llm`, `tts`, `imagem`.

```python
with broker.exclusivo("imagem"):
    ...
```

Aquisição do slot: lock de arquivo em `output/.gpu.lock` mais um arquivo de estado
com o recurso residente. Dois processos `forge` simultâneos se respeitam.

Liberação, por recurso — todos os mecanismos verificados nesta máquina:

| Recurso | Libera com | Confirma com |
|---|---|---|
| `llm` | `lms unload --all` | `GET /api/v0/models`, todos com `state != "loaded"` |
| `imagem` | `POST /free {"unload_models": true, "free_memory": true}` | `GET /system_stats`, campo `vram_free` |
| `tts` | o processo `audiocpp_cli.exe` termina sozinho | espera o exit do subprocess |

Cada liberação tem timeout e é verificada; falha em confirmar é erro, não aviso.
Binário ou serviço ausente degrada com log, não com exceção — o liberador de um
recurso que não está no ar não tem o que fazer.

`FORGE_TTS_BACKEND=cpu` faz o recurso `tts` declarar que não usa GPU: nesse modo
`exclusivo("tts")` não disputa o slot.

### S3 — Plano de mídia

Roda no fim do `forge roteiro`, com o LLM ainda residente, e grava
`<run>/video/midia.json`. Concentra todo o trabalho de LLM da fase de vídeo num
lugar só, para que narração e imagem sejam pura execução.

Produz:

- **Blocos de narração** — o roteiro fatiado em trechos de 1 a 3 frases, cada um
  com tags de controle do higgs (`<|emotion:...|>`, `<|prosody:...|>`), o índice
  da seção de origem e um id estável.
- **Plano de imagens** — um prompt por beat visual, com alvo de ~15 s de tela,
  amarrado ao id do bloco de narração onde o beat começa.

As tags são validadas contra o catálogo das 43 antes de qualquer GPU: uma tag
inválida custa minutos de síntese para descobrir.

### S4 — Manifesto e runner

`<run>/video/manifesto.json`, uma entrada por item:

```json
{
  "id": "audio-007",
  "tipo": "audio",
  "estado": "pendente | ok | falhou",
  "entrada": { "texto": "...", "bloco": 7 },
  "saida": "video/audio/007.wav",
  "duracao_ms": 4820,
  "tentativas": 1,
  "erro": ""
}
```

O runner agrupa por `tipo`, toma o slot de GPU uma vez por grupo, processa os
`pendente` e regrava o manifesto depois de **cada** item, com escrita atômica
(arquivo temporário e `os.replace`). Um crash perde no máximo um item.

`forge video <run>` recalcula os pendentes e retoma. `--refazer <id>` devolve um
item ao estado pendente. `--so audio` / `--so imagens` roda um grupo isolado.

Com `FORGE_TTS_BACKEND=cpu`, o runner pode rodar os grupos `audio` e `imagem`
concorrentes, porque só um deles reivindica o slot.

### S5 — Narração

**Novo `services/narracao.py`**, dois backends atrás da mesma função:

- `vulkan` (default) — subprocess para `audiocpp_cli.exe`, como em
  `C:\dev\audio-generate\run_ensaio_gpu.py`: `--task tts --family higgs_audio_tts
  --backend vulkan --device 0 --metrics --voice-ref ... --reference-text ...`.
  As métricas do stdout (`metrics.audio_duration_ms`, `metrics.rtf`) alimentam
  `duracao_ms` no manifesto — e é essa duração que cronometra as imagens em S7.
  Zero dependência Python pesada.
- `cpu` — caminho de `C:\dev\audio-generate\run_ensaio.py`:
  `audio_generate.synthesize` com `SynthesisOptions(device="cpu",
  dtype="bfloat16")`, ~8,5 GB de RAM. Não toma o slot de GPU.

O modo `cpu` exige o pacote `audio-generate` importável, então o forge ganha um
extra opcional `[audio]` com dependência de caminho para `C:\dev\audio-generate`.
Isso também evita duplicar o catálogo das 43 tags: a validação usa
`audio_generate.tags` quando o extra está instalado. No modo `vulkan` sem o extra,
a validação cai para um catálogo mínimo embutido — a lista de tags é dado, não
lógica, e a divergência é registrada em comentário.

Novas configurações: `FORGE_TTS_BACKEND`, `FORGE_AUDIOCPP_BIN`,
`FORGE_AUDIOCPP_MODEL`, `FORGE_TTS_REF_AUDIO`, `FORGE_TTS_REF_TEXT`,
`FORGE_TTS_SEED`, `FORGE_TTS_TEMPERATURE`.

### S6 — Imagens

**Novo `services/comfy.py`.** Carrega um template de workflow em **formato API**
de `config/workflows/`, injeta prompt, seed e dimensões por id de nó, enfileira e
espera.

Por imagem, nesta ordem:

1. `POST /free {"unload_models": true, "free_memory": true}`.
2. Espera `GET /system_stats` confirmar VRAM livre acima do limiar (com timeout).
3. `POST /prompt` com o workflow preenchido.
4. Poll em `GET /history/{prompt_id}` até concluir.
5. Copia o arquivo de saída para `<run>/video/imagens/NNN.png`.

O passo 1 é o que impede o crash observado no meio da fase.

Workflow inicial deliberadamente simples: `CheckpointLoaderSimple`,
`CLIPTextEncode` positivo e negativo, `KSampler`, `VAEDecode`, `SaveImage`. SDXL,
432x768 vertical. Como o template é JSON externo, trocá-lo por algo mais elaborado
(o `ProducaoImagem.json` do usuário, com dois passes, DetailDaemon e upscale 4x)
não exige mudança de código — só que os ids de nó injetáveis sejam declarados na
config do template.

Novas configurações: `FORGE_COMFY_URL` (default `http://127.0.0.1:8188`),
`FORGE_COMFY_WORKFLOW`, `FORGE_COMFY_TIMEOUT`, `FORGE_COMFY_VRAM_LIVRE_MIN`.

### S7 — Montagem

ffmpeg, já disponível no PATH:

- Trilha de áudio: concatenação dos WAVs dos blocos, na ordem.
- Trilha visual: cada imagem ocupa a janela do seu beat, calculada a partir das
  durações reais dos blocos no manifesto — nunca de uma estimativa.
- Movimento: Ken Burns via `zoompan`, crossfade nas trocas.
- Legendas: SRT derivado dos blocos e das durações; queima opcional.
- Saída: `output/videos/<slug>.mp4`.

## Testes

Nenhum teste toca a rede ou a GPU.

- **acervo** — transporte httpx falso com respostas fixas; cobre resultado normal,
  vazio, e API fora do ar.
- **broker** — liberadores falsos; asserções sobre ordem de liberação, exclusão
  mútua entre dois brokers, e erro quando a liberação não confirma.
- **runner/manifesto** — executor falso que estoura no item N; asserção de que a
  retomada processa exatamente os pendentes e preserva os concluídos.
- **comfy** — servidor HTTP falso; asserção de que `/free` precede cada `/prompt`.
- **narração** — subprocess falso devolvendo o stdout de métricas real; asserção
  do parse de `duracao_ms`.
- **plano de mídia** — modelo mockado; asserção de que tag inválida é recusada
  antes de qualquer chamada de síntese.
- **integração** — atrás de marker, exigindo acervo, LM Studio e ComfyUI no ar.

## Questão em aberto (resolvida por medição, antes de S0)

**Vale rodar o TTS na CPU em paralelo com as imagens na GPU?**

Com `D` segundos de áudio final e `I` segundos de fase de imagem:

- serial, TTS na GPU: `2,11·D + I`
- paralelo, TTS na CPU: `max(16,4·D, I)`

O paralelo só ganha se `I > 14,3·D`. Para um vídeo de 10 minutos (`D = 600 s`),
isso exige mais de 2,4 horas de geração de imagem — cerca de 3,5 min por imagem em
40 imagens. Plausível nesta placa, ainda mais com o reload de checkpoint por
imagem que o `/free` impõe, mas não é para ser decidido por estimativa.

**Spike:** cronometrar uma imagem no workflow simples, com `/free` antes,
multiplicar pela contagem de imagens e comparar. O resultado escolhe apenas o
*default* de `FORGE_TTS_BACKEND`; o desenho já suporta os dois modos, então o
spike não bloqueia nada além dessa escolha.

## Fora de escopo

- Reintroduzir busca web sob qualquer forma.
- Ingestão de livros dentro do forge (é do acervo).
- Upload para YouTube, thumbnails, metadados de publicação.
- Treino, quantização ou troca de modelo de TTS.
- Rodar ComfyUI ou acervo em outra máquina (o desenho não impede — os dois são
  URLs configuráveis — mas não é alvo agora).

---

# Adendo — 2026-09-06 (tarde): autonomia e realimentação do acervo

Aprovado depois do Plano 1 (S0+S1) estar em produção. Não altera nenhuma
decisão anterior; acrescenta duas.

## Meta

Gerar vídeos do nicho **livre-arbítrio, determinismo e natureza humana**, sem
supervisão, um após o outro, até ordem explícita de parar. O nicho não é uma
preferência editorial: é o eixo que as 16 obras do acervo cobrem de fato
(Bergson, Leibniz, Kant, Darwin, William James, Nietzsche, `Determinism or
Free-Will?`). Tema fora desse eixo produz roteiro sem fonte.

## Decisões novas

**D8 — O forge julga a relevância do que o acervo devolveu.** O acervo já
registra a pergunta quando *nada* casou. O caso que escapa é o pior: passagens
voltam com score alto e são sobre outra coisa. Um passo de LLM barato, depois da
busca, decide se as passagens respondem à query. Nenhuma serve: trata como
lacuna, pelo mesmo caminho de `_brief_lacuna`.

**D9 — O contrato do arquivo do acervo é respeitado.**
`C:\dev\research\dados\unanswered_questions.txt` guarda, segundo o próprio
`unanswered_log.py`, *apenas a pergunta, sem duplicata, uma por linha* — e o
acervo o lê de volta. O forge escreve **só a pergunta** ali, com o mesmo
dedupe. O par pergunta/resposta completo vai para um arquivo próprio ao lado,
`C:\dev\research\dados\respostas_ruins.jsonl`, que o acervo não lê. Escrever o
par no arquivo do acervo quebraria o dedupe dele.

**D10 — A autonomia é um processo, não uma sessão de agente.** `forge canal`
roda o ciclo inteiro em loop e sobrevive ao fechamento do Claude Code. Um loop
conduzido por agente só anda enquanto a sessão viver e gasta contexto a cada
volta.

**D11 — Chamada de LLM tem prazo.** O run real do Plano 1 travou duas vezes na
síntese do LM Studio (10 e 12 min, sem retorno). Num loop infinito isso não é
lentidão, é parada. Toda chamada de modelo ganha timeout e uma retentativa; a
segunda falha aborta o vídeo corrente, registra e o loop segue para o próximo
tema.

## S8 — Juiz de relevância e realimentação do acervo

Entra em `agents/research.py`, entre `colher` e `_sintetizar`.

O juiz recebe a query e as passagens em forma curta (título, breadcrumb, e o
começo do texto) e devolve quais servem. Sobrou alguma: segue a síntese só com
elas. Nenhuma serve: o brief vira o de lacuna e o par é registrado.

Registro, em duas mãos:

- a query em `unanswered_questions.txt`, uma linha, dedupe contra o arquivo
  inteiro antes de escrever — mesmo algoritmo do `FileUnansweredLog` do acervo;
- a evidência em `respostas_ruins.jsonl`, uma linha JSON por caso:
  `{"ts", "tema", "query", "motivo", "passagens": [{"path", "book_title",
  "score", "trecho"}]}`.

Escrita em arquivo de outro projeto falha de forma tolerante: um caminho
inexistente ou sem permissão vira log de aviso, nunca derruba o roteiro.

Configuração: `FORGE_GAPS_FILE`, `FORGE_RESPOSTAS_RUINS_FILE`,
`FORGE_JUIZ_RELEVANCIA` (default ligado).

## S9 — Canal autônomo (`forge canal`)

Um ciclo, repetido:

1. **Escolhe o tema.** O modelo propõe um tema dentro do nicho, recebendo a
   lista dos temas já produzidos para não repetir.
2. **Sonda o acervo** antes de gastar qualquer coisa: uma busca com o tema. Zero
   passagens relevantes (pelo juiz de S8) descarta o tema, registra a lacuna e
   volta ao passo 1. Três descartes seguidos param o loop — o acervo não cobre o
   que o modelo está propondo, e insistir só queima GPU.
3. **Roteiro**, pelo grafo que já existe.
4. **Plano de mídia** (S3), ainda com o LLM residente.
5. **Vídeo** (S4-S7), pelo runner do manifesto.
6. **Registra** no catálogo e recomeça.

**Catálogo:** `output/canal/catalogo.json`, uma entrada por vídeo — tema, run
dir, timestamp, estado (`ok` / `falhou`), caminho do MP4, motivo da falha. É
dele que sai a lista de temas já feitos.

**Parada:** o arquivo `output/canal/PARAR`, conferido entre um vídeo e o
próximo, e `Ctrl+C`, que termina o item corrente do manifesto antes de sair. O
manifesto de S4 já garante que nada se perde.

**Retomada:** ao subir, se o último run do catálogo está incompleto, o canal o
termina antes de escolher tema novo.

**Falha não derruba o loop.** Um vídeo que estoura vira `falhou` no catálogo e o
ciclo segue. Três falhas seguidas param o loop: o problema deixou de ser do
vídeo e passou a ser do ambiente.

## Ordem de construção revisada

S2 → S3 → S4 → S8 → S5 → S6 → S7 → S9.

S8 entra antes da narração porque é barato, é independente da GPU, e quanto
antes o acervo receber as lacunas, mais cedo as obras que faltam podem ser
ingeridas. S9 vem por último por definição: é a costura de tudo.

## Requisitos que S9 herda do Plano 2

Levantados pela revisão final do Plano 2 e deliberadamente adiados ali, porque
só mordem quando o loop desassistido existir:

- **Retentativa com teto substitui `--refazer`.** Hoje um `GPUOcupada` ou um
  `LiberacaoFalhou` transitório marca o grupo inteiro como `falhou` e nada o
  devolve para `pendente`; o campo `tentativas` é incrementado e nunca lido.
  `--refazer` é um comando manual e não serve a um processo que roda sozinho. O
  canal precisa de retentativa automática com teto e recuo, e de tratar um item
  no teto como falha definitiva daquele vídeo, não do loop.
- **`PlanoJaExiste` não é erro.** O `except Exception` do `forge roteiro`
  registra a recusa de sobrescrever `midia.json` como `ERROR "Plano de mídia
  falhou"`, embora o processo termine com sucesso e o plano continue íntegro.
  Num loop que ninguém acompanha, um ERROR que não é erro esconde os que são.
  Tratar separadamente.

## Medições do primeiro run real completo (2026-09-06, 18:31-20:31)

`forge roteiro --provider lm-studio` com `qwen3.8-9b-distill` (Q4_K_M, contexto
carregado 32768) na RX 580. Tema: "O livre-arbítrio é compatível com o
determinismo?".

| nó | 1ª volta | 2ª volta |
|---|---|---|
| research (queries + síntese) | 22 min | 15,7 min |
| plan | 9,2 min | 5,5 min |
| write (9 seções) | 7,5 min | 18,4 min |
| review | 6,5 min | 8,9 min |

**1h25 para duas voltas.** O usuário aceitou esse custo e mantém o modelo local.
Um vídeo por dia é a ordem de grandeza realista, não um fluxo contínuo — S9 deve
ser desenhado para isso, não para cadência de minutos.

Confirmado em produção: o timeout de D11 disparou duas vezes e salvou o run (a
síntese de research só terminou porque a primeira tentativa estourou em 600 s e a
retentativa passou em 556 s). O broker reivindicou o slot `llm`, gravou o estado e
soltou o lock mesmo com o processo morrendo por exceção.

### Dois defeitos que o run revelou

**A seção `Verificar` do revisor está sendo usada como checklist.** O modelo
escreve pares pergunta/resposta (`- Hook sem preâmbulo?` / `- Sim`) e cada linha
vira um item de `verificar`. Como `rotear` faz `verificar` vencer `aprovado`, o
grafo nunca termina por aprovação — termina por teto de passos, gastando uma volta
inteira (~50 min) por roteiro. Pior: a pesquisa dirigida leva `"Sim"` ao acervo, e
quando S8 existir essas queries-lixo entrariam no `unanswered_questions.txt`. O
prompt de review precisa exigir alegação factual citável e lista vazia quando não
houver. Corrigir junto de S8, antes que S8 comece a escrever no arquivo do acervo.

**Um descarregamento externo do modelo mata o run.** O run morreu com
`400 - Model unloaded by user or API request` durante uma retentativa; o estado do
broker prova que não foi o forge (nenhuma troca de recurso aconteceu). LM Studio ou
outro cliente derrubou o modelo. Um `400` não é retentado pelo cliente OpenAI, então
o vídeo inteiro se perde. S9 precisa tratar isso: detectar o descarregamento,
recarregar pelo `lms load`, e retomar o vídeo em vez de abandoná-lo.

## Revisão de S3 — o fatiamento sai do LLM (2026-09-07)

Verificação isolada de `planejar_midia` contra o roteiro real do run anterior
(1079 palavras, 9 seções, ~7,2 min de áudio). A mecânica passou inteira: ids
renumerados, beats órfãos descartados com aviso, escrita atômica, round-trip
idêntico. O conteúdo não:

| | roteiro | plano gerado |
|---|---|---|
| seções | 9 | 1 (só o Hook) |
| palavras | 1079 | 85 |
| áudio | ~7,2 min | ~0,6 min |

O modelo emitiu três blocos e parou, mas listou beats apontando para `b_014`,
`b_024` … `b_078` — planejou dezenas de blocos, escreveu três. O descarte de
órfãos limpou a inconsistência e o resultado foi um plano coerente e vazio.
Levado ao `forge video`, isso geraria 36 segundos de narração para um roteiro de
sete minutos e marcaria todos os itens do manifesto como `ok`.

**D12 — Fatiar é trabalho de código, não de modelo.** O próprio prompt dizia
"você está cortando, não editando": nenhuma palavra pode ser perdida ou
reescrita. Isso é uma operação determinística, e um LLM a executa com risco de
truncar, pular ou reescrever — foi o que aconteceu. O fatiamento passa para
Python: cobertura garantida por construção, custo zero, sem truncamento. O LLM
fica só com o que exige juízo, os prompts de imagem, e é chamado uma vez por
seção em vez de uma vez pelo roteiro inteiro.

Tags de controle de emoção saem desta versão. Elas eram o outro motivo para o
modelo tocar no texto, e o TTS narra bem sem elas; voltam depois, se a narração
soar chapada. O catálogo das 43 tags e sua validação continuam onde estão — são
o guarda-corpo de quem reintroduzir isso.

### O que o fatiador precisa saber sobre o texto real

- Cada seção abre com uma rubrica de cena numa linha inteiramente entre
  parênteses: `(Cena: Um carro acelerando numa estrada reta.)`. **Ela não é
  narração** e não pode ir para o TTS — mas é uma descrição visual escrita pelo
  autor, então serve de semente para os prompts de imagem daquela seção.
- O corpo traz ênfase markdown (`*dentro*`), que o TTS não deve receber.
- Nove rubricas para sete minutos dão uma imagem a cada 47 s; o alvo é ~15 s.
  A rubrica orienta o estilo da seção, não substitui os beats.
