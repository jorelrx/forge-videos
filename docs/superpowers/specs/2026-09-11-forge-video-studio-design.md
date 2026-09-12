# Forge Video Studio — especificação de arquitetura e produto

**Data:** 2026-09-11
**Status:** aprovado pelo dono
**Escopo:** primeira versão operacional local
**Repositório:** `C:\dev\forge-videos`
**Referência experimental:** `C:\dev\_pipeline-poc`

## 1. Resumo executivo

O `forge-videos` deixa de ser apenas uma CLI de geração de roteiros e passa a ser
o produto local completo para produção e acompanhamento de vídeos. O produto
terá um backend Python/FastAPI, um worker de execução e um frontend Next.js no
mesmo repositório.

O Forge será o proprietário da fila, das runs, da máquina de estados, dos gates
de qualidade, dos artefatos e do dashboard. Ele consumirá, por contratos
explícitos, projetos e serviços externos já existentes:

- `research` para pesquisa e fontes citáveis;
- LM Studio para LLM local;
- `audio-generate` para narração;
- ComfyUI para imagens;
- FFmpeg para composição e validação de mídia.

O `_pipeline-poc` não será dependência de runtime. Ele permanece como laboratório,
benchmark e documentação. Cada comportamento comprovado nele será migrado para
o Forge acompanhado de testes de caracterização.

## 2. Contexto e motivação

O fluxo atual já gera roteiro, imagens, áudio e vídeo, mas sua operação está
espalhada entre scripts, JSONs, terminais e processos independentes. Isso cria
problemas recorrentes:

1. o operador precisa lembrar comandos e a ordem correta dos serviços;
2. não há uma visão única de fila, execução atual e histórico;
3. um processo pode terminar com código zero enquanto uma etapa ficou parcial;
4. pausar ou retomar depende de conhecimento dos arquivos internos;
5. logs técnicos não distinguem progresso, warning, falha transitória e gate de
   qualidade;
6. LM Studio, ComfyUI e TTS disputam uma GPU de 8 GB e não podem coexistir;
7. reinícios e processos órfãos deixam locks ou VRAM presos;
8. artefatos existem no disco, mas não há um catálogo central para preview e
   auditoria.

A solução precisa preservar o que já funciona no Forge: agentes LangGraph,
artefatos numerados, retomada, `PlanoMidia`, `Manifesto`, runner por item,
persistência atômica e broker de GPU.

## 3. Objetivos

### 3.1 Objetivos da V1

- Criar vídeos e colocá-los em uma fila persistente.
- Mostrar fila, run ativa e histórico na tela principal.
- Iniciar, solicitar pausa, retomar e repetir uma etapa.
- Exibir progresso por etapa e por item em tempo real.
- Mostrar estado e ocupação dos serviços locais.
- Exibir logs estruturados e erros acionáveis.
- Permitir preview de roteiro, fontes, imagens, áudio e vídeo.
- Retomar após encerramento inesperado sem repetir artefatos aprovados.
- Impedir uso simultâneo dos consumidores de GPU.
- Bloquear montagem e conclusão quando artefatos obrigatórios estiverem
  incompletos.
- Registrar configuração, métricas, tentativas, duração e procedência de cada
  artefato.
- Operar 100% localmente e para um único usuário.

### 3.2 Não objetivos da V1

- Edição visual de roteiro, áudio ou imagens dentro do dashboard.
- Timeline de vídeo semelhante a Premiere/DaVinci.
- Execução distribuída em várias máquinas.
- Vários usuários, autenticação ou permissões.
- Aplicativo desktop nativo.
- Upload ou publicação automática no YouTube.
- Execução paralela de várias runs.
- Substituição do LangGraph por outro engine de workflow.
- Integração com o Gateway Central.
- Uso de Temporal, Prefect ou outro orquestrador externo.

## 4. Decisões arquiteturais

### D-001 — O produto vive no `forge-videos`

Backend, worker, frontend e modelo operacional pertencem ao repositório
`C:\dev\forge-videos`. `research`, `audio-generate` e ComfyUI continuam projetos
ou serviços externos.

### D-002 — Um repositório, responsabilidades separadas

Não serão criados dois repositórios. O Python existente não será movido apenas
para criar uma pasta `backend/`. A separação será feita com novos limites
internos:

```text
forge-videos/
├── src/forge/                 # backend e núcleo Python existentes
│   ├── agents/                # agentes atuais
│   ├── orchestration/         # grafo de roteiro atual
│   ├── domain/                # domínio atual + operação do Studio
│   ├── services/              # regras de aplicação
│   ├── repositories/          # persistência SQLite operacional
│   ├── executors/             # executores de etapas e integrações externas
│   ├── api/                   # FastAPI, schemas, SSE
│   └── worker/                # fila, lease, subprocessos, heartbeat
├── web/                       # dashboard Next.js
├── tests/                     # testes Python
├── docs/
├── data/forge.db              # estado operacional local
├── output/runs/               # artefatos de produção
└── scripts/                   # start/stop/build local
```

Os módulos atuais não serão renomeados em massa. A implementação deve estender
os limites existentes e mover código somente quando houver ganho de domínio
comprovável.

### D-003 — SQLite é a fonte de verdade operacional

`data/forge.db`, em WAL, guarda fila, runs, etapas, itens, comandos, eventos e
metadados de artefatos. `output/runs/` guarda arquivos grandes e snapshots
legíveis por humanos.

O dashboard não determina estado raspando logs nem inferindo a presença de um
arquivo. JSONs e Markdown existentes continuam úteis como artefatos auditáveis,
mas não competem com o banco como estado operacional.

### D-004 — API e worker são processos separados

Processos previstos:

```text
forge-api       FastAPI, comandos, consultas e SSE
forge-worker    claim da fila, lease, heartbeat e supervisão
forge-web       Next.js
```

Reiniciar API ou frontend não encerra a run ativa. Cada etapa pesada será
executada em subprocesso separado para impedir vazamento de memória entre LLM,
ComfyUI e TTS.

### D-005 — Eventos estruturados, não scraping de terminal

Subprocessos emitem eventos JSONL em stdout. O worker valida e persiste esses
eventos. Stderr bruto é capturado como diagnóstico, mas não é o contrato do
dashboard.

### D-006 — Pausa cooperativa e segura

Pausar grava `pause_requested`. O worker conclui o item atômico atual, persiste o
checkpoint e muda a run para `paused`. A V1 não interrompe uma chamada LLM ou um
render SDXL no meio; a interface informa “pausa após o item atual”.

### D-007 — Falha parcial não é conclusão

Uma etapa essencial só recebe `succeeded` quando seu gate passa. Por exemplo,
36/41 blocos de áudio é `failed`, não `succeeded`. Montagem não roda com áudio
obrigatório ausente.

### D-008 — Um consumidor de GPU por vez

LM Studio, `audio-generate` Vulkan e ComfyUI compartilham um único broker. O
broker deve confirmar a liberação real, detectar locks/PIDs órfãos e desligar o
ComfyUI antes do TTS quando `/free` não devolver o heap Vulkan.

### D-009 — `_pipeline-poc` é referência, não dependência

Nenhum import, subprocesso ou configuração de produção apontará para
`C:\dev\_pipeline-poc`. A migração copia conceitos e implementações para o Forge
com testes. O POC permanece congelado como evidência das medições.

### D-010 — Uma run por vez na V1

A fila pode conter vários vídeos, mas só uma run executa. A restrição simplifica
a semântica de GPU, pausa, prioridades e recuperação. Paralelismo de tarefas CPU
fica fora da V1.

### D-011 — Serviço local sem autenticação

API e frontend fazem bind em `127.0.0.1`. CORS aceita apenas o frontend local.
Não há autenticação na V1. A API nunca aceita comandos shell livres nem paths de
artefato enviados pelo cliente.

### D-012 — Áudio precede imagens na execução

Ordem canônica:

```text
preparação → pesquisa → roteiro → plano de mídia → áudio → imagens → montagem → validação
```

O áudio fornece durações reais para o planejamento visual e deve rodar antes do
ComfyUI para evitar o heap Vulkan residual observado no POC. A UI pode agrupar
`preparação` e `plano de mídia`, mas o estado interno mantém as oito etapas.

### D-013 — CLI existente permanece disponível

`forge roteiro` continuará funcionando como ferramenta headless e de
desenvolvimento. Runs completas do Studio entram pelo control plane para manter
o estado central. Um importador de runs antigas registra artefatos existentes
como histórico somente leitura.

## 5. Componentes

### 5.1 Dashboard Next.js

A primeira tela contém:

1. status de `research`, LM Studio, ComfyUI, TTS, FFmpeg e GPU;
2. run ativa com progresso global e por etapa;
3. comandos iniciar, pausar, retomar e repetir etapa;
4. fila de próximos vídeos;
5. histórico de runs;
6. log ao vivo;
7. preview do artefato mais recente;
8. falhas e itens pendentes visíveis.

A V1 usa um preset local recomendado. O formulário de novo vídeo pede apenas:

- tema;
- tese opcional;
- prioridade;
- preset.

Parâmetros técnicos avançados permanecem em configuração do backend.

### 5.2 Control plane FastAPI

Responsabilidades:

- validar comandos;
- aplicar transições de estado;
- gravar comandos de forma idempotente;
- consultar fila, runs, etapas, eventos e artefatos;
- expor SSE com replay;
- fazer health checks dos serviços;
- servir previews com MIME e `Range` controlados;
- nunca executar a pipeline dentro da thread de request.

Porta padrão: `127.0.0.1:8765`.

### 5.3 Worker

Responsabilidades:

- reivindicar a próxima run por `UPDATE` atômico;
- renovar lease por heartbeat;
- observar comandos pendentes;
- iniciar um subprocesso por etapa;
- traduzir eventos JSONL para o banco;
- capturar stderr;
- aplicar gates;
- persistir checkpoint por item;
- recuperar runs interrompidas;
- avançar a máquina de estados.

### 5.4 Executores

Cada executor implementa contrato equivalente a:

```python
class StageExecutor(Protocol):
    stage: StageName

    def prepare(self, context: RunContext) -> StagePlan: ...
    def execute(self, context: RunContext, emit: EventSink) -> StageResult: ...
    def validate(self, context: RunContext, result: StageResult) -> GateResult: ...
```

Executores previstos:

- `ResearchExecutor` — `research` em `127.0.0.1:8000`;
- `ScriptExecutor` — LangGraph + LM Studio;
- `MediaPlanExecutor` — `PlanoMidia` atual;
- `AudioExecutor` — `audio-generate` via CLI isolada;
- `ImageExecutor` — ComfyUI + cache/biblioteca;
- `ComposeExecutor` — FFmpeg;
- `ValidationExecutor` — contagens, codecs, duração, silêncio e frames.

Os executores reaproveitam `services/manifesto.py`, `services/runner.py`,
`services/persistencia.py`, `gpu/broker.py` e os modelos de mídia atuais. Não
haverá segundo manifesto concorrente.

## 6. Máquina de estados

### 6.1 Estado da run

```text
queued → preparing → running → validating → completed
                  ↘ pausing → paused → queued
                  ↘ failed → queued (após comando de retry/resume)
                  ↘ interrupted → queued
```

Estados terminais: `completed`, `cancelled`. `failed` não é terminal para fins de
retomada, mas exige comando ou política de retry.

### 6.2 Estado da etapa

```text
pending → running → succeeded
                  ↘ failed
                  ↘ pausing → paused
                  ↘ interrupted
                  ↘ invalidated
```

### 6.3 Estado do item

```text
pending → running → succeeded | failed | invalidated
```

### 6.4 Invalidação por dependência

Repetir etapa cria nova tentativa e marca saídas dependentes como `invalidated`:

| Etapa repetida | Invalida |
|---|---|
| preparação | todas as posteriores |
| pesquisa | roteiro, plano de mídia, áudio, imagens, montagem, validação |
| roteiro | plano de mídia, áudio, imagens, montagem, validação |
| plano de mídia | áudio, imagens, montagem, validação |
| áudio | imagens, montagem, validação |
| imagens | montagem, validação |
| montagem | validação |
| validação | somente validação |

Artefatos invalidados não são apagados. Recebem `is_current=false` e permanecem
no histórico.

## 7. Modelo persistente

### 7.1 `videos`

Representa o vídeo como intenção estável.

- `id` UUID;
- `tema`;
- `tese` opcional;
- `created_at`;
- `updated_at`.

### 7.2 `runs`

- `id` UUID;
- `video_id`;
- `status`;
- `priority`;
- `queue_position`;
- `config_snapshot_json`;
- `workflow_version`;
- `git_commit`;
- `lease_owner`;
- `lease_expires_at`;
- `pause_requested_at`;
- `created_at`, `started_at`, `finished_at`;
- `failure_code`, `failure_message`.

### 7.3 `stage_runs`

- `id` UUID;
- `run_id`;
- `stage`;
- `attempt`;
- `status`;
- `current_items`, `total_items`;
- `progress`;
- `gate_status`;
- `input_hash`;
- timestamps e erro.

### 7.4 `work_items`

- `id` UUID;
- `stage_run_id`;
- `item_key` estável;
- `status`;
- `input_json`, `input_hash`;
- `attempts`;
- `duration_ms`;
- erro estruturado.

### 7.5 `artifacts`

- `id` UUID;
- `run_id`;
- `stage_run_id`;
- `work_item_id` opcional;
- `kind`;
- `relative_path`;
- `sha256`;
- `size_bytes`;
- `mime_type`;
- `metadata_json`;
- `is_current`;
- `created_at`.

Somente paths relativos a `output/runs/<run-id>/` são persistidos.

### 7.6 `events`

Tabela append-only:

- `id` inteiro monotônico;
- `run_id`, `stage_run_id`, `work_item_id` opcionais;
- `kind`, `level`, `message`;
- `payload_json`;
- `created_at`.

### 7.7 `commands`

- `id` UUID;
- `run_id`;
- `type`: `pause`, `resume`, `retry_stage`;
- `stage` opcional;
- `idempotency_key` único;
- `status`: `pending`, `accepted`, `applied`, `rejected`;
- timestamps e resultado.

## 8. API HTTP

| Método e rota | Função |
|---|---|
| `POST /api/videos` | cria vídeo e primeira run na fila |
| `GET /api/queue` | fila ordenada |
| `GET /api/runs` | histórico paginado |
| `GET /api/runs/{id}` | run, etapas, métricas e progresso |
| `POST /api/runs/{id}/pause` | cria comando de pausa |
| `POST /api/runs/{id}/resume` | cria comando de retomada |
| `POST /api/runs/{id}/stages/{stage}/retry` | repete etapa |
| `GET /api/runs/{id}/events` | eventos paginados |
| `GET /api/events/stream` | SSE filtrável por run |
| `GET /api/runs/{id}/artifacts` | catálogo de artefatos |
| `GET /api/artifacts/{id}/content` | preview/stream por ID |
| `GET /api/services` | saúde dos serviços locais |
| `GET /api/config/effective` | configuração efetiva sem segredos |

Todos os POSTs de comando aceitam `Idempotency-Key`. Repetição da mesma chave
devolve o comando existente.

### 8.1 Contrato do evento

```json
{
  "id": 1842,
  "run_id": "...",
  "stage": "audio",
  "item_id": "tensao_06",
  "kind": "item.succeeded",
  "level": "info",
  "message": "Bloco sintetizado",
  "progress": {"current": 36, "total": 41},
  "metrics": {"duration_ms": 43800, "f0_hz": 115},
  "created_at": "2026-09-11T17:49:29Z"
}
```

O stream usa `id:` do SSE e respeita `Last-Event-ID`. Ao reconectar, o servidor
reproduz eventos posteriores antes de voltar ao modo ao vivo.

## 9. Snapshot de configuração

A run grava uma cópia imutável da configuração que a produziu:

```json
{
  "preset": "local-recomendado-v1",
  "model": "google/gemma-4-e4b",
  "context_length": 16384,
  "llm_max_tokens": 4000,
  "tts_backend": "vulkan",
  "tts_seed": 42,
  "tts_sampler": "model-defaults",
  "visual_style": "cosmos-interior",
  "image_width": 1024,
  "image_height": 576,
  "image_steps": 14,
  "image_cfg": 3.2
}
```

Segredos nunca entram no snapshot, nos eventos nem na API. A resposta de
configuração efetiva mascara qualquer credencial como `[REDACTED]`.

## 10. Classificação de falhas e retries

| Classe | Exemplos | Política |
|---|---|---|
| transitória | serviço iniciando, timeout HTTP, VRAM ainda liberando | retry limitado com backoff |
| capacidade | OOM Vulkan/DirectML | falha rápida, sem repetir o mesmo payload cegamente |
| determinística | fonte ausente, gate de qualidade, saída inválida | sem retry automático cego |
| processo | subprocesso/worker morto | `interrupted`; retomada por checkpoint |
| usuário | pausa solicitada | não é erro |
| item | bloco/beat falhou | etapa falha; retry somente dos falhos |

Erro persistido inclui:

- código estável;
- mensagem para o operador;
- stack trace;
- adapter/comando;
- tentativa e item;
- serviços e GPU no momento;
- `retriable`;
- ação recomendada.

A tela principal mostra mensagem curta. Um drawer técnico mostra a evidência
completa.

## 11. Gates de qualidade

### Pesquisa

- API do `research` disponível;
- passagens possuem `path` canônico;
- quantidade mínima configurada;
- lacunas registradas sem inventar fonte.

### Roteiro

- nove funções narrativas previstas;
- zero rótulos-robô;
- zero anti-padrões graves de hook;
- zero frases acima do teto incompatível com TTS;
- citação/ancoragem nas seções de corpo;
- exceção deliberada para o Gancho;
- zero defeitos classificados como graves.

### Áudio

- 100% dos blocos sintetizados;
- WAV válido, 24 kHz mono ou configuração registrada;
- duração não vazia;
- guarda de voz/F0 aprovada;
- nenhum trecho obrigatório ausente.

### Imagens

- 100% dos beats obrigatórios;
- arquivo válido e resolução esperada;
- cache ou fallback registrado;
- procedência e prompt associados ao artefato.

### Montagem

- H.264 + AAC;
- 1920×1080;
- duração coerente com a narração;
- todas as trilhas obrigatórias presentes;
- nenhum path ausente.

### Validação final

- contagens cruzadas entre plano, itens e artefatos;
- ausência programática de silêncio indevido;
- frames amostrados extraídos com sucesso;
- vídeo final legível pelo `ffprobe`;
- status `completed` apenas após todos os gates.

## 12. Integrações externas

### 12.1 `research`

- HTTP em `127.0.0.1:8000`;
- falha indisponível bloqueia pesquisa;
- nenhum fallback para web na V1;
- resposta normalizada antes de chegar ao domínio;
- `path`, livro e autores preservados.

### 12.2 LM Studio

- HTTP OpenAI-compatible em `127.0.0.1:1234`;
- modelo carregado explicitamente com contexto 16384;
- `reasoning_content` tratado separadamente de `content`;
- `finish_reason=length` pode ampliar orçamento dentro do limite do executor;
- modelo removido `qwen/qwen3.8-27b` não volta ao preset.

### 12.3 `audio-generate`

- CLI executada em subprocesso isolado;
- seed e voice reference fixas;
- sampler usa padrões do modelo;
- tags de emoção não entram na síntese da V1;
- `reached max_tokens before EOC` e OOM possuem códigos diferentes;
- licença/atribuição do Higgs aparece como alerta de configuração.

### 12.4 ComfyUI

- API em `127.0.0.1:8188`;
- auto-start controlado pelo executor;
- SDXL com decode tiled;
- somente LoRAs validadas como compatíveis;
- style token sem conteúdo específico de cena;
- servidor pode ser encerrado antes do TTS.

### 12.5 FFmpeg

- execução CPU;
- inputs vêm apenas do catálogo de artefatos;
- concat usa caminhos absolutos gerados no backend;
- `ffprobe` valida saída antes do gate final.

## 13. Broker de GPU

Requisitos obrigatórios, derivados das falhas reais do POC:

1. lock compartilhado entre Studio e CLI;
2. PID e recurso residente persistidos;
3. lock órfão detectado;
4. consumidor manualmente iniciado não pode ser invisível;
5. comando de unload não basta: a VRAM deve ser confirmada;
6. TTS desliga ComfyUI quando `/free` não libera o heap;
7. processo Python órfão que segura memória deve ser diagnosticado;
8. troca acontece por grupo/etapa, não por item;
9. estado ilegível libera todos de forma conservadora;
10. timeout produz falha terminal legível, nunca espera infinita.

## 14. Recuperação e reconciliação

O worker renova lease a cada cinco segundos. No startup:

1. localiza runs `running`/`pausing` com lease vencido;
2. muda para `interrupted`;
3. verifica hashes e existência dos artefatos atuais;
4. preserva item `succeeded` cujo artefato é válido;
5. marca como falho registro apontando arquivo ausente;
6. cataloga arquivo conhecido sem registro como órfão, sem consumi-lo;
7. enfileira a run do primeiro item obrigatório pendente quando houver comando de
   retomada.

A recuperação nunca apaga arquivos automaticamente.

## 15. Segurança local

- bind somente em `127.0.0.1`;
- CORS somente para `127.0.0.1:3100` e `localhost:3100`;
- allowlist de etapas e comandos;
- nenhum shell arbitrário vindo do frontend;
- preview por `artifact_id`, nunca por path de query;
- path resolvido deve permanecer dentro do run dir;
- MIME allowlist para Markdown, JSON, PNG/JPEG/WebP, WAV e MP4;
- suporte a `Range` para áudio e vídeo;
- segredos mascarados em logs, eventos e respostas.

## 16. Inicialização local

Um script PowerShell será o ponto de entrada:

```powershell
.\scripts\start-studio.ps1
```

Ele deve:

1. validar Python, Node, FFmpeg e caminhos configurados;
2. aplicar migrações SQLite idempotentes;
3. iniciar API em `:8765`;
4. iniciar worker;
5. iniciar frontend em `:3100`;
6. abrir o navegador;
7. gravar PIDs fora de `output/runs` para um `stop-studio.ps1` idempotente.

O launcher não inicia automaticamente Docker Desktop. Ele mostra o estado do
`research` e a ação necessária quando a infraestrutura estiver indisponível.

## 17. Estratégia de testes

### 17.1 Testes unitários

- transições válidas e inválidas;
- pausa e comandos idempotentes;
- grafo de invalidação;
- gates de qualidade;
- classificação dos erros observados no POC;
- cálculo de progresso;
- proteção de paths;
- masking de segredos.

### 17.2 Persistência

- claim atômico da fila;
- dois workers não executam a mesma run;
- lease e heartbeat;
- WAL e busy timeout;
- migrações idempotentes;
- artefato ausente e artefato órfão;
- histórico preservado após retry.

### 17.3 API

- criação/listagem de vídeos e runs;
- comando duplicado;
- transição inválida retorna 409;
- SSE reconecta sem lacuna nem duplicata;
- `Range` em WAV/MP4;
- path traversal rejeitado;
- configuração não expõe segredo.

### 17.4 Worker com executores falsos

- pausa durante item;
- morte e retomada;
- áudio 36/41 bloqueia montagem;
- repetir roteiro invalida dependentes;
- retry somente dos itens falhos;
- artefatos válidos não são refeitos;
- evento inválido vindo do subprocesso é rejeitado e registrado.

### 17.5 Integração real, marcada

Testes `integration` não rodam na suíte padrão. Suite real mínima:

- uma busca no `research`;
- uma chamada LM Studio;
- um WAV curto;
- uma imagem ComfyUI;
- um MP4 curto;
- tentativa simultânea de dois consumidores bloqueada pelo broker.

## 18. Critérios de aceite da V1

1. Três vídeos podem ser enfileirados e a ordem sobrevive a restart.
2. Apenas uma run executa.
3. Dashboard atualiza por SSE sem reload.
4. Pausa ocorre após o item atual e não deixa artefato parcial aprovado.
5. Retomada não repete artefato válido.
6. Worker morto é detectado por lease vencido.
7. Falha parcial não vira `completed`.
8. Retry de etapa invalida dependentes e preserva histórico.
9. Retry de áudio repete apenas blocos falhos.
10. Histórico mostra duração, snapshot, métricas, erros e artefatos.
11. Reiniciar API, frontend ou worker não perde estado.
12. Serviços e GPU aparecem com estado real ou indisponível; nunca estado
    inventado.
13. Um run completo produz roteiro, fontes, áudio 100%, imagens 100%, MP4 1080p
    e validação aprovada.
14. `scripts/start-studio.ps1` inicia a aplicação inteira.
15. Nenhum runtime depende de `C:\dev\_pipeline-poc`.

## 19. Migração do POC para produção

A migração ocorre por fatias, nunca copiando o diretório inteiro:

1. criar testes de caracterização para detector, métricas e arquitetura narrativa;
2. incorporar esses componentes ao domínio/serviços do Forge;
3. migrar TTS e suas falhas conhecidas para `AudioExecutor`;
4. migrar estilo, validação de LoRA e workflow para `ImageExecutor`;
5. migrar montagem e validação FFmpeg;
6. fortalecer o broker atual com PID, confirmação de VRAM e desligamento;
7. conectar tudo à máquina de estados operacional;
8. expor API/SSE;
9. construir o dashboard;
10. executar um run real completo e comparar artefatos/contagens.

Cada fatia entra com teste vermelho, implementação mínima, regressão verde e
commit próprio.

## 20. Sequência de entrega

A implementação será planejada em cinco marcos dependentes. Cada marco terá sua
própria spec de execução/plano, aprovação e ciclo de implementação. Não haverá um
plano monolítico tentando entregar backend, worker, integrações e frontend de uma
vez:

1. **Control plane:** domínio operacional, SQLite, fila, comandos e eventos.
2. **Worker:** lease, heartbeat, subprocessos, pausa e recuperação.
3. **Executores:** migração controlada do POC e gates de qualidade.
4. **API e dashboard:** SSE, previews, fila, run atual e histórico.
5. **Integração:** launcher, importador de runs, testes reais e vídeo completo.

Esta seção define somente a ordem e as dependências. O plano executável do
primeiro marco, com arquivos e testes por tarefa, será produzido após a revisão
desta especificação. Os marcos seguintes só serão planejados quando o anterior
estiver validado, evitando decisões detalhadas sobre código ainda inexistente.
