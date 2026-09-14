---
timestamp: 2026-09-14
marco: 5
status: em-verificacao
---

# Status Marco 5 — Integração

## Tasks 0–5 e 7: concluídas

| Task | Entrega | Commit |
|---|---|---|
| 0 | Gate M1–M4 verde (pytest, lint, build, sem referência ao POC antigo) | `3049158` |
| 1 | Migração SQLite v1→v2 (`runs.is_read_only`), histórico imutável, 409 na API | `7f62844` |
| 2 | `forge-studio-doctor`, `forge-worker`, preflight com redaction | `463ef4e` |
| 3 | Importador de runs legadas (cópia, id determinístico, imutabilidade) | `e3c4612` |
| 4 | `scripts/start-studio.ps1` / `stop-studio.ps1` + smoke real | `9568522` |
| 5 | Provas de integração reais (research, LM Studio, TTS, FFmpeg, broker) | `d0f5c5e` |
| 7 | Runbook no README, `.env.example`, teste de documentação | `455bb7c` |

## Ambiente verificado

- Python 3.13.5 · Node 24.18.0 · Next 16.3.4 · uv 0.12.5 · FFmpeg 8.1.2
- GPU: AMD RX 580 2048SP 8 GB · LM Studio com `google/gemma-4-e4b` (contexto 16384)
- TTS: `audiocpp_cli.exe` + `higgs-audio-v3-tts-4b-q8_0.gguf` (`--family higgs_audio_tts`)
- ComfyUI em `C:\Program Files\StabilityMatrix-win-x64\Data\Packages\ComfyUI`

## Defeitos reais encontrados e corrigidos

Os testes de integração e a run ponta a ponta existem para isso: cada item
abaixo passava na suíte antiga porque o teste travava o defeito em vez de
verificar comportamento.

1. **Adaptador TTS com contrato errado.** Faltavam `--task` e `--family`
   (obrigatórios: sem eles o binário sai 1 sem gerar áudio), `--voice-reference`
   não existe (é `--voice-ref`) e `--output-dir` também não (é `--out-dir`).
2. **Mapeamento de saída do TTS inventado.** O binário ignora o `id` do lote e
   grava `line_<N>.wav`. O adaptador anunciava `<item_key>.wav` — com exit 0, N
   itens viravam N sucessos apontando para arquivos inexistentes. Agora lê
   `--batch-manifest-out` e falha em qualquer saída ausente.
3. **`StageContext.run_dir` nunca preenchido.** O projetor de eventos resolvia
   caminho relativo contra o CWD e recusava todo `artifact.created` como
   "path outside run_dir": a run ponta a ponta morria na primeira etapa.
4. **`ImageExecutor` fora do protocolo do projetor.** Emitia `kind="image"` sem
   `stage` (o contrato é `imagem` + `imagens`) e nunca emitia `item.started`,
   tornando `item.succeeded` uma transição inválida a partir de `PENDING`.
5. **`ComfyClient` era stub.** `generate()` devolvia
   `video/images/<hash>.png` sem chamar o ComfyUI. Substituído pelo cliente
   HTTP real (`POST /prompt`, poll `/history`, `GET /view`, `VAEDecodeTiled`).
6. **`ComposeExecutor` era stub.** Gate fixo em 41 áudios e nenhuma chamada ao
   ffmpeg. Substituído pela montagem real (Ken Burns por beat, concat, mux AAC).
7. **`kind.startswith("image/")` no consumidor.** O produtor registra
   `image.png`; a validação reprovava todo vídeo com `image_artifact_missing`.
8. **ComfyUI não era religado.** O broker o encerra antes do TTS (segura o heap
   Vulkan) e o áudio roda antes das imagens: sem `garantir_comfy` o slot de
   imagem encontrava o servidor morto em todo run.
9. **Testes que liam o próprio código-fonte.** `test_montagem.py` afirmava
   `"expected_audio = 41" in source`; `test_ffmpeg.py` procurava `"shell=False"`
   no arquivo. Reescritos como testes de comportamento.

### Windows PowerShell 5.1 (scripts do launcher)

`$pid` é automático e read-only (usá-lo como variável ou parâmetro falha);
`Start-Process` recusa stdout e stderr no mesmo arquivo; `Join-Path` aceita só
dois argumentos; `.ps1` sem BOM é lido como ANSI (corrompe acentos);
`Set-Content -Encoding UTF8` grava BOM, que quebra `json.loads` fora do
PowerShell; o Pester nativo é 3.4 e não serve — a detecção exige ≥5.0 e cai para
o teste Python equivalente.

## Falhas conhecidas

- **ComfyUI em cold start:** o primeiro `/search` do acervo pode estourar 30 s
  enquanto o modelo de embedding carrega; depois responde em ~0,3 s.
- **Ordering de VRAM é obrigatório.** Com o LLM carregado, o `audiocpp_cli`
  falha com `ErrorOutOfDeviceMemory`. O broker descarrega antes; a run isolada
  precisa do mesmo cuidado.
- **LoRAs de estilo ausentes** nesta máquina: `add-detail-xl` e `more_details`
  não estão em `FORGE_LORA_DIR`, então a geração usa só o style token. A
  inspeção de safetensors existe para não aplicar LoRA de SD 1.5 em silêncio.

## Evidência da run real

Preenchida pelo `tests/integration/test_studio_e2e.py`. Ver a seção seguinte.
