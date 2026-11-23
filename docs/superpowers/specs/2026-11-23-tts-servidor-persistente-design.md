# TTS com servidor persistente e fila de CPU em paralelo

Data: 2026-11-23 · Status: proposta

## Intenção

A etapa de áudio gasta ~8 s por chamada só para carregar o Higgs Audio v3 (4,75 GB)
na RX 580, porque cada lote do `audiocpp_cli` é um processo novo. E um trecho que bate
no `max_tokens` derruba o lote: os trechos seguintes, mesmo os que nem começaram, caem
no caminho de isolamento e cada um paga a carga do modelo de novo. Quando a GPU desiste
de um trecho, a CPU assume — e enquanto a CPU trabalha, a GPU fica parada esperando.

O usuário quer três coisas:

1. carregar o modelo uma vez por etapa;
2. que cada trecho seja independente: falha de um não arrasta os outros;
3. que o trecho que falhou na GPU vá para uma **fila de CPU que roda em paralelo**, sem
   travar a GPU — "um não deve impedir o outro".

## O que foi medido (2026-11-23, RX 580 2048SP, Ryzen 7 5700X, 32 GB)

O pacote pré-compilado em `C:\dev\audio-generate\runtime\bin` já traz
`audiocpp_server.exe`, que o Forge nunca usou. Spike descartável:

| Medida | Resultado |
|---|---|
| Mesmo bloco, seed 42, CLI one-shot | 16,2 s de parede |
| Mesmo bloco, seed 42, servidor residente | 8,2 s |
| Saída servidor × CLI | **idêntica byte a byte** (24 kHz, 112 320 frames) |
| Cache da referência de voz entre pedidos | `reference_kv_cache_hit 1` a partir do 2º pedido |
| `max_tokens` estourado | HTTP 500 `Higgs TTS generation reached max_tokens before EOC`; servidor segue de pé |
| `voice_ref` inexistente | HTTP 500 `could not open WAV input: <path>` em ~0 s |
| GPU sozinha × GPU com servidor CPU (12 threads) sintetizando junto | 8,2–9,4 s × 8,2–8,5 s — **sem perda** |
| CPU, servidor residente, 12 threads | 5,0 s de áudio em 20,2 s |

Contrato do servidor, descoberto no spike (não há documentação local):

- Config JSON: `{"host": "127.0.0.1", "port": N, "models": [{"id": "higgs", "task": "tts",
  "family": "higgs_audio_tts", "path": "<gguf>"}]}`. A chave do caminho é `path`
  (com `model` o servidor recusa: `missing required json key: path`).
- Linha de comando: `audiocpp_server.exe --config <json> --backend vulkan|cpu --no-ui
  [--threads N] [--log-file <path>]`. O modelo é carregado na subida;
  `GET /health` → `{"status":"ok","models":1}`; `GET /v1/models` → `loaded: true`.
- Pedido: `POST /v1/audio/speech` com JSON `{"model": "higgs", "input": <texto>,
  "response_format": "wav", "voice_ref": <path>, "reference_text": <texto>, "seed": N,
  "max_tokens": N?}`. Resposta `audio/wav`.
- **Armadilha:** os campos de clonagem vão no nível de cima. Dentro de `"options"` são
  ignorados em silêncio — o servidor responde 200 com uma voz não clonada.

## Objetivos

- Um processo `audiocpp_server` por backend durante a etapa de áudio; nenhuma recarga
  por trecho.
- Cada trecho é um pedido independente. O lote deixa de existir (o problema 1 do pedido
  original desaparece por construção).
- Trecho que esgota as tentativas na GPU entra numa fila de CPU consumida em paralelo; a
  GPU segue nos trechos seguintes sem esperar.
- VRAM devolvida antes da etapa de imagens, com o processo confirmado encerrado.

## Não-objetivos

- Compartilhar o servidor entre chamadas de `execute()`. A abertura
  ([executors/abertura.py](../../../src/forge/executors/abertura.py)) chama
  `AudioExecutor.execute` várias vezes com 1–2 itens; cada chamada sobe e derruba o
  servidor — uma carga por chamada, igual a hoje. Sem regressão, sem ganho ali.
- Começar a etapa de imagens enquanto a fila de CPU termina. As etapas do Studio são
  sequenciais; a etapa de áudio só termina quando as duas filas esvaziam.
- Streaming (`/v1/audio/speech/live`, `stream_format`).
- Mexer no pacote Python do `audio-generate` (caminho torch/CPU) ou no
  `run_segments_gpu.py`, que tem alterações não commitadas do usuário.

## Anti-objetivos (falha mesmo que "funcione")

- **Voz não clonada aceita como sucesso.** É o modo de falha silencioso do contrato.
- **Duas cópias do modelo na VRAM**, ou um servidor órfão segurando 4,75 GB depois que o
  worker morreu.
- **Rodar o roteiro inteiro na CPU em silêncio** porque o servidor de GPU caiu. Queda de
  servidor não é "trecho que falhou na GPU".
- Trecho da fila de CPU impedindo o progresso da GPU, ou vice-versa.

## Abordagens consideradas

- **A — o Forge controla o servidor (escolhida pelo usuário).** O executor sobe o
  `audiocpp_server`, faz um pedido HTTP por trecho e o derruba no fim, no mesmo padrão
  de `garantir_comfy`/`shutdown_comfy`. Tudo fica num repositório; o executor continua
  dono dos eventos, da validação e do retry.
- **B — módulo servidor+cliente dentro do `audio-generate`.** Reutilizável pelos scripts
  de lá, mas o pacote depende de torch: o Forge teria de instalá-lo ou contorná-lo só
  para falar HTTP. Rejeitada.
- **Manter o CLI e só consertar a recuperação** (primeiro WAV faltante isolado, o resto
  devolvido a um lote). Resolve o problema 1, não o 2. Rejeitada depois do spike.

## Desenho

### 1. Processo do servidor — `executors/audiocpp_server.py` (novo)

`ServidorTTS(settings, backend, *, pasta_log)` como context manager:

- Gera o config JSON num diretório temporário próprio, com porta livre escolhida pelo SO
  (bind em `127.0.0.1:0`, lê a porta, fecha, passa ao servidor).
- Sobe com `subprocess.Popen(..., shell=False)`, `cwd=settings.audio_generate_dir`,
  `--no-ui`, `--log-file <run>/video/audio/.servidor-<backend>.log`; para `cpu`, também
  `--threads settings.tts_cpu_threads`.
- Espera `GET /health` com `models >= 1` até `settings.tts_server_start_timeout`
  (novo, padrão 120 s). Processo que sai antes disso = falha de subida com o fim do log.
- **Sonda de contrato** logo após a subida: um pedido com `voice_ref` apontando para um
  caminho que não existe precisa voltar HTTP 500 contendo `could not open WAV input`.
  Se voltar 200, o servidor não está lendo `voice_ref` no nível de cima — falha alto
  (`tts_contrato_servidor`), nunca segue gerando voz não clonada. Custo medido: ~0 s.
- Registra o PID em `output/.tts-servidor.json` (mesma raiz que `criar_run_dir` usa,
  como o lock do broker) e remove no encerramento.
- `__exit__`: `terminate`, espera, `kill` se preciso, confirma que o processo saiu.

### 2. Cliente — `executors/audio_generate.py` (reescrito)

`AudioGenerateClient.synthesize(request, servidor, destino) -> AudioOutcome`:

- `POST /v1/audio/speech` com os campos no nível de cima (a montagem do payload é uma
  função pura, testada contra a armadilha de `options`).
- Escreve o WAV em `<key>.wav.tmp` e renomeia para `<key>.wav` — nunca meio arquivo com o
  nome canônico.
- Mapeia a falha mantendo os códigos que já existem:
  - 500 com `max_tokens before EOC` → `tts_max_tokens_before_eoc`;
  - 500 com `ggml_vulkan: Device memory allocation` → `tts_vulkan_oom`;
  - conexão recusada / reset / timeout do pedido → `tts_servidor_indisponivel` (novo);
  - outro 500 → `tts_process_failed`, com a mensagem do servidor (truncada como hoje).
- `synthesize_batch`, `build_argv`, `_map_manifest_outputs`, `_map_partial_outputs` e o
  `.batches/` saem. O CLI deixa de ser usado pelo Forge.

### 3. Executor — `executors/audio.py`

Duas filas, dois servidores, uma thread de trabalho para a CPU:

```
thread principal (GPU)                     thread CPU
──────────────────────                     ──────────
para cada trecho pendente:                 servidor CPU sobe no 1º item da fila
  seeds = (tts_seed, *alternate_seeds)     para cada item da fila:
  para cada seed: pedido → valida            mesmas seeds, mesma validação
    ok e sem achados → aceito                resultado → fila_resultados
  esgotou com falha de trecho → fila_cpu   (sentinela encerra)
  drena fila_resultados (sem bloquear)
espera fila_cpu esvaziar, drenando resultados
passe de outliers de voz (GPU)
encerra os dois servidores (finally)
```

- **Falha de trecho** (vai para a CPU): `tts_max_tokens_before_eoc`, ou WAV que sai com
  achados de validação (silêncio longo, formato) em todas as seeds. O silêncio longo
  deixa de ser um passe separado (`_retry_long_silences`): passa a ser "esta seed não
  serve, tente a próxima" dentro do laço de seeds, nos dois backends.
- Repetir a mesma seed na GPU é inútil: a saída é determinística (byte a byte).
- **Falha de servidor** (`tts_servidor_indisponivel`, OOM): o executor reinicia o
  servidor daquele backend **uma vez por etapa** e repete o trecho. Se cair de novo, os
  trechos restantes daquele backend falham com `tts_servidor_indisponivel`; não são
  despejados na outra fila.
- Uma só thread mexe em `paths`, `artifacts` e chama `emit`: a principal. A thread CPU só
  sintetiza e valida — `_artifact_for` não tem efeito colateral — e devolve
  `(item, outcome, artefato | achados, seed, elapsed)` pela `fila_resultados`.
- O servidor de GPU fica de pé enquanto a fila de CPU termina. Nada mais pode usar a
  placa durante a etapa, e o passe de outliers precisa dele com todos os artefatos em mão.
- Passe de outliers de voz (`_retry_voice_outliers`) roda **dentro** do slot `tts`, na
  GPU, depois das duas filas — hoje ele roda fora do `with broker.exclusivo("tts")`,
  disparando um CLI na GPU sem o slot.
- Eventos: os mesmos de hoje (`item.started`, `item.succeeded`, `item.failed`,
  `artifact.created`). `audio.recovery.started` passa a significar "entrou na fila de
  CPU" (payload com `queued: true` e a falha original da GPU);
  `audio.recovery.completed` sai quando a CPU termina o trecho, com sucesso ou não.
- `tts_backend == "cpu"`: só o servidor CPU, só a thread principal, sem fila de recuperação.

### 3a. Tabela de falhas

| Situação | Classe | O que acontece |
|---|---|---|
| `tts_max_tokens_before_eoc` | trecho | próxima seed; esgotou na GPU → fila de CPU; esgotou na CPU → `item.failed`, sem artefato |
| WAV com achados (silêncio longo etc.) | trecho | próxima seed; esgotou na GPU → fila de CPU; esgotou na CPU → mantém o artefato da última seed e o gate (`validate`) reprova, como hoje |
| `tts_vulkan_oom` | servidor | reinicia o servidor (consome o reinício único da etapa) e repete o trecho |
| conexão recusada / reset / timeout | servidor | idem |
| servidor que não sobe, ou cai de novo depois do reinício | servidor | trechos restantes **daquele backend** → `item.failed` com `tts_servidor_indisponivel`; nada é despejado no outro backend |
| sonda de contrato reprova no servidor de **GPU** (ou no único, com `tts_backend="cpu"`) | etapa | `StageExecutionResult.failure` com `tts_contrato_servidor`, nenhum trecho tentado — é binário/versão errados, não um trecho |
| sonda de contrato reprova no servidor de **CPU** | servidor | trechos na fila de CPU → `item.failed` com `tts_contrato_servidor` |
| outro HTTP 500 (`tts_process_failed`, ex.: `could not open WAV input`) | configuração | `item.failed` na hora, sem trocar seed e sem ir para a CPU: é erro igual para todo trecho e esconder na CPU só atrasaria o diagnóstico |

A lista `retry` e o uso de `FailureDetail.retriable` para decidir uma segunda tentativa
saem: o laço de seeds e o reinício único de servidor substituem os dois.

Protocolo da thread de CPU: para **todo** item que entra na `fila_cpu` ela publica
exatamente um resultado na `fila_resultados` — sucesso, falha de trecho ou falha de
servidor. Se a própria thread morrer com exceção, a principal percebe
(`thread.is_alive()` falso com itens em aberto) e marca os restantes como
`tts_servidor_indisponivel`. A espera final nunca é um `join` cego.

Passe de outliers com o servidor de GPU já indisponível: pula, com log de aviso; o gate
continua reprovando o outlier como hoje.

A abertura também passa pelo laço de seeds e pode subir o servidor de CPU para um único
trecho que falhou — o mesmo custo de carga que o fallback via CLI já tinha.

### 4. Broker e liberação — `gpu/liberadores.py`

- `liberar_tts` deixa de ser no-op: lê `output/.tts-servidor.json`, encerra o PID
  registrado se ainda for um `audiocpp_server` vivo (confere a linha de comando antes de
  matar) e espera ele sair. É a rede de segurança para o worker que morreu no meio da
  etapa; no caminho feliz o `__exit__` do `ServidorTTS` já encerrou tudo.
- O executor continua tomando `broker.exclusivo("tts")` uma vez em volta da etapa inteira.

### 5. Configuração — `infrastructure/config.py`

- Novos: `tts_cpu_threads` (padrão 12 — medido sem perda na GPU com 16 threads lógicas),
  `tts_server_start_timeout` (120 s), `resolved_tts_server_binary`
  (`<audio_generate_dir>/runtime/bin/audiocpp_server.exe`, sobrescrevível por
  `FORGE_TTS_SERVER_BINARY`).
- `tts_item_timeout` passa a ser o timeout de cada pedido HTTP.
- Saem: `tts_batch_size`, `tts_batch_timeout`, `tts_binary`/`resolved_tts_binary`. O
  `.env` atual não define os dois primeiros, e `extra="ignore"` absorve um
  `FORGE_TTS_BATCH_SIZE` esquecido. `FORGE_TTS_BINARY` no `.env` vira variável ignorada.
- `services/preflight.py` e `services/saude.py` passam a conferir
  `resolved_tts_server_binary` (obrigatório nos dois backends) no lugar do CLI.

### 5a. Pontos de injeção

- `AudioExecutor(..., client=..., servidor_factory=...)`: `servidor_factory(backend)`
  devolve o context manager do servidor; o padrão constrói `ServidorTTS`.
- `client.synthesize(request, servidor, destino)`: o servidor vai por chamada, então um
  cliente serve aos dois backends.
- Os testes de `tests/executors/test_audio*.py` que falsificam `synthesize_batch` são
  reescritos contra a nova interface; sem shim de compatibilidade.

### 6. `audio-generate`

Só documentação: seção no README sobre o caminho Vulkan na RX 580 via `audiocpp_server`
(config, contrato, armadilha de `options`), e corrigir a frase "GPUs AMD não servem",
que vale só para o caminho torch.

## Testes

Unitários, com servidor falso injetado (nada de rede real):

- payload com `voice_ref`/`reference_text`/`seed` no nível de cima, nunca em `options`;
- sonda de contrato: servidor que devolve 200 para `voice_ref` inexistente → falha alto;
- trecho com `max_tokens` em todas as seeds da GPU vai para a CPU **e** os trechos
  seguintes terminam na GPU antes do trecho da CPU (ordem provada com um evento que
  segura a CPU até a GPU acabar);
- silêncio longo na seed padrão, seed alternativa limpa → aceito sem ir para a CPU;
- servidor cai uma vez → reinicia e continua; cai duas → restantes falham com
  `tts_servidor_indisponivel`, nenhum despejado na CPU;
- `liberar_tts` mata só PID registrado cuja linha de comando é `audiocpp_server`;
- `tts_backend="cpu"`: um servidor, sem fila de recuperação.

Aceite ao vivo: etapa de áudio de uma run real; tempo total antes × depois; um trecho
forçado na CPU (`max_tokens` baixo) conferido **por ASR**, não por RMS/pico.

## Decisões minhas (conferir)

- Servidor caído não manda trechos para a CPU (anti-objetivo de rodar tudo na CPU em
  silêncio); reinicia uma vez e depois falha.
- Silêncio longo entra no laço de seeds e pode levar o trecho para a CPU.
- Servidor de GPU fica residente até a fila de CPU acabar.
- Sonda de contrato a cada subida, em vez de confiar no contrato descoberto.
- CPU também via servidor residente (não CLI): troca de seed na CPU sem recarga e um só
  cliente para os dois backends.
- Toda a tabela de falhas (3a): em especial OOM gastar o reinício único, e erro 500
  genérico falhar o trecho na hora em vez de ir para a CPU.
- Trecho que esgota as seeds na CPU só por achados mantém o artefato e deixa o gate
  reprovar, como hoje.

## Fica para quem constrói

- Nome exato de funções, forma da `fila_resultados`, estrutura dos testes.
- Detalhe do encerramento no Windows (`terminate` × `CTRL_BREAK_EVENT`) desde que o
  processo seja confirmado morto.
- Se `tts_binary` some ou fica sem uso.
