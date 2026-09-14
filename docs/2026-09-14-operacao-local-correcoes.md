---
timestamp: 2026-09-14
tema: operação local — pipeline parado e painel vermelho
status: fechado
---

# Correções de operação local (2026-09-14)

Sintomas relatados: o Painel Web mostrava ComfyUI e TTS como indisponíveis, e
criar um vídeo na fila não iniciava nada. O diagnóstico e as correções abaixo
saem de probes reais (`forge-studio-doctor`, `/api/services`, SQLite, linha de
`progresso.jsonl`), não de leitura de código.

## Causas raiz do ambiente

1. **Paths do TTS derivados do layout errado.** `Settings` resolvia
   `<audio_generate_dir>/audio-generate.exe`, `model.gguf` e `voice.wav`; o
   `audio-generate` distribui `runtime/bin/audiocpp_cli.exe`,
   `runtime/models/<gguf>` e `ref.wav` na raiz. O doctor reprovava o TTS
   (`Faltam: tts_binary, tts_model, tts_voice_reference`) e a etapa de áudio não
   tinha como rodar. Corrigido em `infrastructure/config.py` (defaults derivam
   do layout real) e explicitado no `.env`.
2. **ComfyUI fora da configuração.** `FORGE_COMFY_DIR` apontava para
   `data/comfy` (inexistente), então `garantir_comfy` não tinha `main.py` para
   subir. Com o diretório do pacote StabilityMatrix no `.env`, o ComfyUI sobe
   pelo próprio pipeline.
3. **Worker não estava rodando.** Sem worker a fila fica `queued` para sempre —
   nenhum erro, nenhuma pista no painel. O worker funciona: `run.claimed` →
   `stage.started` → `stage.succeeded` gravados no SQLite.

Armadilha adicional: o parser do `.env` interpreta `\a`, `\b` e `\v` como
escape. `C:\dev\audio-generate` chega como `C:<BEL>udio-generate`. Todo path no
`.env` usa barras normais.

## Defeitos de código encontrados pelas provas

| Onde | Defeito | Consequência |
|---|---|---|
| `services/saude.py` | probe de GPU lia `%TEMP%/forge_health_state.json` | painel anunciava "Sem residente" com o LLM carregado |
| `gpu/broker.py` | faltava leitura com dono vivo | estado sobrevive ao filho; PID morto aparecia como residente |
| `orchestration/graph.py` | `max_passos` só era conferido em `rotear`, e o handoff `write → research` não passa por lá; o nó nem vê `passos` (o `com_wrapper` entrega só o `LE`) | modelo que sempre pede pesquisa rodava até o prazo do subprocesso: 7 rodadas de pesquisa e >2 h na mesma etapa |
| `services/worker.py` | `_current_pending_stage` escolhia a primeira `PENDING`, ignorando ordem | etapa `running` órfã (dono morto com lease válido) fazia o worker rodar a etapa SEGUINTE sem insumo, falhando a run e apontando a etapa errada |
| `services/control_plane.py` | `resume` só reinicia PAUSED/FAILED/INTERRUPTED | etapa presa em `running` não tinha saída pela API; run travada |
| `api/app.py` vs `api/errors.py` | mesmo 409 com dois códigos (`invalid_transition` / `transition_invalid`) | painel não podia decidir por `error.code` |
| `web/lib/api.ts` | lia `payload.error`, mas o FastAPI embrulha em `detail` | toda falha virava "Falha HTTP 4xx" |
| `web/lib/contracts.ts` | `UtcDatetime` tipado como objeto de campos; o wire é ISO string | contrato mentia sobre o formato |
| `web/hooks/use-dashboard.ts` | fila e runs esperavam o probe de serviços (3,1 s) e a recarga por SSE desabilitava o formulário | vídeo recém-criado demorava a aparecer; "nada acontece" |
| `web/components/dashboard.tsx` | chip de etapa pela posição do índice, sem `preparacao`/`plano_midia` | `imagens` aparecia concluída enquanto `audio` rodava; ações oferecidas onde a API responde 409 |

## Calibração para inferência local

O modelo local gasta ~5-7 min por passo do grafo e o teto da etapa `roteiro` era
3600 s. Os três botões, agora no `.env`:

- `FORGE_MAX_REVIEW_ROUNDS=4` — encurta o laço de review;
- `FORGE_LOCAL_STAGE_TIMEOUT_MULTIPLIER=2` — teto de 7200 s para o roteiro;
- `FORGE_MAX_PASSOS=12` — faz o **orçamento vencer o prazo**: o grafo encerra
  por decisão própria em vez de morrer em `subprocess_timeout`.

## Provas reais usadas

- `uv run forge-studio-doctor` → `tts: PASS`, `Preflight OK`;
- `GET /api/services` → os seis serviços `available`, `gpu: Residente: llm`;
- TTS: `test_tts_synthesizes_a_real_wav` (WAV mono 24 kHz do `audiocpp_cli`);
- ComfyUI: PNG 1024x576 real gerado pelo `ComfyClient`;
- acervo, LM Studio, FFmpeg (MP4 1080p h264/aac) e broker: testes de integração
  reais (`FORGE_RUN_INTEGRATION=1`);
- API: `POST /api/videos`, `POST /runs/{id}/resume`, `POST /runs/{id}/stages/{stage}/retry`
  e o histórico de eventos por SSE;
- painel: `Dashboard` renderizado contra a API real (teste vitest com
  `createStudioApi`, criado fora da suíte e removido depois).

## Triagem para a próxima vez

O runbook curto está no README, seção "Triagem quando o painel mostra vermelho
ou a fila não anda". Ordem: `forge-studio-doctor` → `/api/services` →
`forge-worker --once` → `resume` se a run estiver `interrupted`.

## Conclusão da tentativa ponta a ponta (run `6ab11aa4`)

O encanamento inteiro foi exercitado de verdade: fila → worker → `preparacao` →
`pesquisa` (5 fontes canônicas, gate `research_ready`) → `roteiro` com o grafo
corrigido, encerrando **pelo próprio orçamento** (sem `subprocess_timeout`).
A run parou no gate de qualidade do roteiro (`script_gate_failed`), pelas
seguintes causas, corrigidas nesta sessão:

- acento de seção (`Tensão` ≠ `Tensao`) derrubava as 9 de uma vez →
  `canonizar_nome()` na fronteira do `write` (`sections_ok` 0 → 9);
- o prompt do escritor jamais recebia a lista de fontes → `{fontes}` renderizado
  no `write.md` (o gate `sem_citacao` exige o autor/título literal da passagem
  em cada seção factual);
- o briefing de pesquisa acumulava ~23 kB e degradava o rascunho → `max_passos`
  baixo o suficiente para o contexto local sustentar.

Restou um bloqueio de **capacidade do modelo local** (gemma-4-e4b, contexto
16k): a 4ª e a 5ª tentativa produziram as 9 seções com nomes/citações corretos,
mas sem âncora literal de autor/título do acervo em cada seção. Isso é o gate
funcionando — recusar roteiro sem ancoragem não é defeito. Caminhos, nesta
ordem: modelo local maior/longo-contexto, suavizar o contrato textual do gate,
ou aceitar a taxa de reprovação e usar `retry` (`POST /api/runs/{id}/stages/roteiro/retry`).
