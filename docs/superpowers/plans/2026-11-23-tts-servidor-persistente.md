# TTS com servidor persistente e fila de CPU — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trocar o `audiocpp_cli` em lotes por um `audiocpp_server` residente por backend, com um pedido HTTP por trecho e uma fila de CPU que roda em paralelo à GPU.

**Architecture:** `ServidorTTS` (novo) sobe/encerra o processo e confere o contrato; `AudioGenerateClient.synthesize` faz um pedido por trecho; `AudioExecutor.execute` roda o laço de seeds na GPU na thread principal e despeja trechos esgotados numa thread de CPU, que devolve resultados por fila. Só a thread principal chama `emit` e mexe em `paths`/`artifacts`.

**Tech Stack:** Python 3.12, httpx, subprocess, threading/queue, pytest (`httpx.MockTransport`, Popen falso).

**Spec:** [docs/superpowers/specs/2026-11-23-tts-servidor-persistente-design.md](../specs/2026-11-23-tts-servidor-persistente-design.md) — ler inteiro antes de qualquer tarefa; a tabela de falhas (3a) é normativa.

## Global Constraints

- Campos de clonagem no nível de cima do JSON: `model`, `input`, `response_format: "wav"`, `voice_ref`, `reference_text`, `seed`, `max_tokens` (só se definido). Nunca dentro de `options`.
- Config do servidor: `{"host": "127.0.0.1", "port": N, "models": [{"id": "higgs", "task": "tts", "family": settings.tts_family, "path": "<gguf>"}]}` — chave `path`, não `model`.
- Linha de comando: `<server> --config <json> --backend vulkan|cpu --no-ui --log-file <run>/video/audio/.servidor-<backend>.log`, mais `--threads <tts_cpu_threads>` só no backend `cpu`.
- Sonda de contrato: pedido com `voice_ref` inexistente tem de voltar HTTP 500 contendo `could not open WAV input`; 200 → `ContratoServidorQuebrado`.
- Seeds por trecho: `(tts_seed, *alternate_seeds)` sem repetir valor; `alternate_seeds = (1042, 2042)`.
- Silêncio longo: `metadata["silencio_max"] > SILENCIO_MAXIMO_SEGUNDOS` (1.5) reprova a seed.
- Reinício: um por backend por etapa.
- Registro de PIDs: `settings.output_dir.parent / ".tts-servidor.json"`.
- Logs `structlog` key=value, nunca f-string; nomes de domínio em português, casar com o arquivo ao redor.
- Não tocar em `C:\dev\audio-generate\run_segments_gpu.py` nem em `segments_*.json` (alterações não commitadas do usuário).

## Review Focus

1. Thread de CPU morre com exceção no meio da fila → a principal não pode esperar para sempre; restantes viram `tts_servidor_indisponivel`. (Teste na Task 5.)
2. Exceção na thread principal com a CPU rodando → `finally` encerra os dois servidores e a thread de CPU sai (sentinela), sem processo órfão. (Teste na Task 5.)
3. Servidor de CPU que nunca sobe (binário ausente, porta ocupada) → só os trechos da fila de CPU falham; a GPU termina os seus. (Teste na Task 5.)
4. Pedido HTTP que estoura `tts_item_timeout` → conta como falha de servidor (reinício), não como falha de trecho. (Teste na Task 4.)
5. `abertura.py` chamando `execute` com 1–2 itens e `tts_seed` sobrescrito → seed sobrescrita é a primeira tentada; nenhum servidor de CPU sobe se nada falha. (Teste na Task 4.)

---

### Task 1: Configuração e checagens de binário

**Files:**
- Modify: `src/forge/infrastructure/config.py` (bloco TTS ~165-260)
- Modify: `src/forge/services/preflight.py:137-155`, `src/forge/services/saude.py:219-225`
- Test: `tests/test_config.py`, `tests/services/test_preflight.py`

**Interfaces:**
- Produces: `Settings.tts_cpu_threads: int = Field(default=12, ge=1)`, `Settings.tts_server_start_timeout: float = Field(default=120, gt=0)`, `Settings.tts_server_binary: Path | None = None`, `Settings.resolved_tts_server_binary -> Path` (padrão `audio_generate_dir / "runtime" / "bin" / "audiocpp_server.exe"`).

- [ ] **Step 1: Testes que falham**

```python
def test_tts_server_binary_padrao_fica_no_runtime(tmp_path):
    s = Settings(_env_file=None, audio_generate_dir=tmp_path)
    assert s.resolved_tts_server_binary == tmp_path / "runtime" / "bin" / "audiocpp_server.exe"
    assert s.tts_cpu_threads == 12 and s.tts_server_start_timeout == 120

def test_preflight_tts_exige_binario_do_servidor(tmp_path):
    # modelo e voz existem, só o audiocpp_server.exe falta
    check = _check_tts(settings, path_exists=lambda p: p != settings.resolved_tts_server_binary)
    assert check.state == FAIL and "tts_server_binary" in check.message
```

- [ ] **Step 2:** `uv run pytest tests/test_config.py tests/services/test_preflight.py -q` → FAIL (atributo inexistente).
- [ ] **Step 3:** Adicionar os campos; em `_check_tts` e `tts_probe` trocar `resolved_tts_binary` por `resolved_tts_server_binary` (rótulo `tts_server_binary`, action citando `tts_server_binary`). Os campos antigos continuam por enquanto (saem na Task 6).
- [ ] **Step 4:** mesmo comando → PASS; `uv run pytest -q` sem regressão.
- [ ] **Step 5:** `git commit -m "feat(tts): configuração do servidor audiocpp"`

---

### Task 2: `ServidorTTS` — ciclo de vida do processo

**Files:**
- Create: `src/forge/executors/audiocpp_server.py`
- Test: `tests/executors/test_audiocpp_server.py`

**Interfaces:**
- Produces:
  - `class ServidorIndisponivel(RuntimeError)` e `class ContratoServidorQuebrado(RuntimeError)`.
  - `def caminho_registro(settings: Settings) -> Path` → `settings.output_dir.parent / ".tts-servidor.json"`; conteúdo: lista JSON de `{"pid": int, "backend": str}`.
  - `class ServidorTTS:` `__init__(self, settings, backend: Literal["vulkan", "cpu"], *, pasta_log: Path, popen=subprocess.Popen, http: httpx.Client | None = None)`; atributos `backend: str`, `url: str` (válido após entrar); `__enter__ -> ServidorTTS`; `__exit__` encerra; `reiniciar() -> None` (encerra e sobe de novo, mesma pasta de log).
  - `def montar_servidor(settings: Settings, backend: str, *, pasta_log: Path) -> ServidorTTS` — fábrica padrão que o executor usa.

- [ ] **Step 1: Testes que falham** (Popen falso com `pid`, `poll()`, `terminate()`, `kill()`, `wait()`; http via `httpx.MockTransport`)

```python
def test_sobe_com_config_path_e_espera_health(tmp_path): ...
    # config gravado tem models[0]["path"] == str(resolved_tts_model) e "model" not in models[0]
    # argv contém "--backend","vulkan","--no-ui","--log-file"; não contém "--threads"
def test_backend_cpu_passa_threads(tmp_path): ...            # "--threads","12" em argv
def test_sonda_de_contrato_reprova_servidor_que_ignora_voice_ref(tmp_path):
    # /v1/audio/speech responde 200 → pytest.raises(ContratoServidorQuebrado); processo encerrado
def test_processo_que_sai_antes_do_health_e_indisponivel(tmp_path):
    # poll() != None antes do health → ServidorIndisponivel com o fim do log na mensagem
def test_health_que_nao_chega_no_prazo_e_indisponivel(tmp_path): ...  # tts_server_start_timeout=0.2
def test_registro_ganha_e_perde_o_pid(tmp_path):
    # dentro do with: caminho_registro contém {"pid": 4321, "backend": "vulkan"}; depois: sem a entrada
def test_saida_encerra_e_mata_se_terminate_nao_basta(tmp_path): ...  # wait() estoura na 1ª → kill()
```

- [ ] **Step 2:** `uv run pytest tests/executors/test_audiocpp_server.py -q` → FAIL (módulo inexistente).
- [ ] **Step 3:** Implementar. Porta: `socket.bind(("127.0.0.1", 0))`, ler, fechar. Config num `TemporaryDirectory` próprio que vive enquanto o servidor vive. Health: `GET /health` até `models >= 1`, poll de 0,5 s, abortando se `poll()` não for `None`. Sonda: `POST /v1/audio/speech` com o payload da Task 3 e `voice_ref` = caminho inexistente dentro do temp. Registro com `FileLock` (já é dependência; ver `services/lacunas.py`), lendo/regravando a lista. Encerramento no Windows: `terminate()` + `wait(10)`, `kill()` se `TimeoutExpired`.
- [ ] **Step 4:** mesmo comando → PASS.
- [ ] **Step 5:** `git commit -m "feat(tts): ServidorTTS sobe e encerra o audiocpp_server"`

---

### Task 3: Cliente HTTP por trecho

**Files:**
- Modify (reescrever): `src/forge/executors/audio_generate.py`
- Test (reescrever): `tests/executors/test_audio_generate.py`

**Interfaces:**
- Consumes: `ServidorTTS.url` (Task 2) — o cliente só lê `.url`.
- Produces:
  - `AudioRequest(item_key: str, text: str, seed: int | None = None, max_tokens: int | None = None)`.
  - `AudioOutcome` e `classify_audio_failure` mantêm nome e campos.
  - `def montar_payload(request: AudioRequest, settings: Settings) -> dict` (pura; remove tags `<|emotion:...|>` como hoje).
  - `AudioGenerateClient(settings, *, http: httpx.Client | None = None)`, `synthesize(self, request, servidor, destino_dir: Path) -> AudioOutcome`.
  - Códigos: `tts_max_tokens_before_eoc` (DETERMINISTIC, não retriable), `tts_vulkan_oom` (CAPACITY), `tts_servidor_indisponivel` (PROCESS, novo: conexão recusada/reset/`httpx.TimeoutException`), `tts_process_failed` (outro 500).
  - Constante `FALHAS_DE_SERVIDOR = frozenset({"tts_vulkan_oom", "tts_servidor_indisponivel"})` exportada.

- [ ] **Step 1: Testes que falham**

```python
def test_payload_leva_clonagem_no_nivel_de_cima(tmp_path):
    p = montar_payload(AudioRequest("b001", "<|emotion:calm|>Olá", seed=7), settings)
    assert p["voice_ref"] == str(settings.resolved_tts_voice_reference)
    assert p["reference_text"] == settings.tts_reference_text and p["seed"] == 7
    assert p["input"] == "Olá" and "options" not in p and "max_tokens" not in p
def test_seed_ausente_usa_tts_seed(tmp_path): ...
def test_grava_wav_atomico_com_nome_canonico(tmp_path):
    # 200 audio/wav → destino_dir/"b001.wav" existe, nenhum ".tmp" sobra, outcome.ok
def test_500_max_tokens_classifica_deterministico(tmp_path):
    # corpo {"error":{"message":"Higgs TTS generation reached max_tokens before EOC"}}
    assert outcome.failure.code == "tts_max_tokens_before_eoc" and not outcome.failure.retriable
def test_500_oom_vulkan_e_falha_de_servidor(tmp_path): ...  # "ggml_vulkan: Device memory allocation"
def test_conexao_recusada_e_timeout_viram_servidor_indisponivel(tmp_path): ...  # ConnectError, ReadTimeout
def test_outro_500_e_process_failed_com_mensagem_truncada(tmp_path): ...  # "could not open WAV input"
def test_item_key_invalido_nao_escreve_fora_do_destino(tmp_path): ...  # "../x" → falha, nada gravado
```

- [ ] **Step 2:** `uv run pytest tests/executors/test_audio_generate.py -q` → FAIL.
- [ ] **Step 3:** Reescrever o módulo; remover `build_argv`, `synthesize_batch`, `_map_manifest_outputs`, `_map_partial_outputs`, `_missing_output`. Timeout do pedido = `settings.tts_item_timeout`.
- [ ] **Step 4:** mesmo comando → PASS. (`tests/executors/test_audio.py` e afins quebram aqui; são reescritos na Task 4 — não commitar com a suíte vermelha: Tasks 3 e 4 fecham juntas no mesmo commit se preciso.)
- [ ] **Step 5:** commit junto com a Task 4.

---

### Task 4: Executor — laço de seeds na GPU e política de servidor

**Files:**
- Modify: `src/forge/executors/audio.py` (`__init__`, `execute`, `_retry_voice_outliers`; remover `_retry_long_silences`)
- Test (reescrever fakes): `tests/executors/test_audio.py`, `tests/executors/test_audio_review.py`, `tests/services/test_catalogo_audio_review.py`, `tests/integration/test_services_real.py` (TTS real passa a usar `ServidorTTS` + `synthesize`)

**Interfaces:**
- Consumes: `montar_servidor` / `ServidorTTS` (Task 2), `AudioGenerateClient.synthesize`, `FALHAS_DE_SERVIDOR`, `AudioRequest` (Task 3).
- Produces:
  - `AudioExecutor(*, settings=None, client=None, broker=None, servidor_factory: Callable[[str, Path], ContextManager[ServidorTTS]] | None = None)`; padrão `lambda backend, pasta: montar_servidor(settings, backend, pasta_log=pasta)`.
  - `def _tentar(self, context, item, servidor, *, output_dir) -> _Tentativa` — laço de seeds; `_Tentativa` é um dataclass com `artefato: ArtifactOutput | None`, `path: Path | None`, `seed: int | None`, `falha: FailureDetail | None`, `classe: Literal["ok", "trecho", "servidor", "config"]`, `elapsed_ms: int`. Sem efeito colateral (usado também pela thread de CPU na Task 5).
  - Nesta task, trecho esgotado na GPU vai para uma lista `fila_cpu` processada **sequencialmente** depois da GPU pelo mesmo `_tentar` num servidor `cpu`; a Task 5 troca por thread.

- [ ] **Step 1: Testes que falham** (fakes: `ServidorFalso` context manager com `url`, `reiniciar()` contando chamadas; `ClienteFalso.synthesize(request, servidor, destino)` roteado por `(item_key, seed, servidor.backend)`)

```python
def test_cada_trecho_e_um_pedido_e_um_servidor_por_etapa(tmp_path):
    # 3 trechos ok → 3 chamadas, servidor_factory chamado 1x com "vulkan", broker.calls == ["tts"]
def test_max_tokens_troca_de_seed_na_gpu_antes_da_cpu(tmp_path):
    # b002 falha seed 42, ok seed 1042 na GPU → nenhum servidor "cpu" criado
def test_trecho_esgotado_na_gpu_vai_para_cpu(tmp_path):
    # b002 max_tokens nas 3 seeds GPU, ok na CPU seed 42 → evento audio.recovery.started (queued=True) e completed
def test_silencio_longo_conta_como_seed_ruim(tmp_path): ...  # reusa _fala() existente
def test_silencio_que_nenhuma_seed_cura_mantem_artefato_e_gate_reprova(tmp_path): ...
def test_erro_500_generico_falha_na_hora_sem_trocar_seed_nem_cpu(tmp_path):
    # tts_process_failed → item.failed, 1 chamada para b002, nenhum servidor cpu
def test_servidor_cai_reinicia_uma_vez_e_repete_o_trecho(tmp_path): ...
def test_servidor_cai_duas_vezes_restantes_falham_sem_ir_para_cpu(tmp_path):
    # códigos item.failed == "tts_servidor_indisponivel"; nenhum servidor cpu
def test_timeout_de_pedido_e_falha_de_servidor(tmp_path): ...        # Review Focus 4
def test_contrato_quebrado_na_gpu_falha_a_etapa(tmp_path):
    # servidor_factory levanta ContratoServidorQuebrado → result.failure.code == "tts_contrato_servidor", 0 pedidos
def test_seed_sobrescrita_da_abertura_e_a_primeira(tmp_path): ...   # Review Focus 5; tts_seed=43 → 1ª chamada seed 43
def test_outliers_de_voz_rodam_dentro_do_slot_tts(tmp_path): ...    # ordem: broker entra, outlier, servidor sai
def test_backend_cpu_usa_so_servidor_cpu(tmp_path): ...
```

Manter os testes atuais de pitch, prepare, reuso e validate; apagar os que testam lote (`test_run_batches_*`, `test_max_tokens_isolates_*`, `test_non_retriable_max_tokens_*`) — o comportamento novo os substitui.

- [ ] **Step 2:** `uv run pytest tests/executors tests/services/test_catalogo_audio_review.py -q` → FAIL.
- [ ] **Step 3:** Implementar seguindo a tabela 3a do spec. Ordem dentro do slot: GPU → fila de CPU → `_retry_voice_outliers` no servidor GPU (pular com `logger.warning` se ele já estiver indisponível) → `finally` fecha os servidores. Contrato quebrado no servidor principal → `StageExecutionResult` com `failure` `tts_contrato_servidor` (ver como `StageExecutionResult.failure` é montado em outros executores).
- [ ] **Step 4:** mesmo comando → PASS; `uv run pytest -q` → PASS.
- [ ] **Step 5:** `git commit -m "feat(tts): um pedido por trecho no servidor residente"` (inclui a Task 3)

---

### Task 5: Fila de CPU em thread paralela

**Files:**
- Modify: `src/forge/executors/audio.py`
- Test: `tests/executors/test_audio.py`

**Interfaces:**
- Consumes: `_tentar` e `_Tentativa` (Task 4).
- Produces: classe interna `_TrabalhadorCPU(executor, context, servidor_factory, output_dir)` com `enfileirar(item)`, `resultados: queue.Queue[tuple[WorkItemPlan, _Tentativa]]`, `encerrar()` (sentinela + `join`), `vivo -> bool`. Servidor `cpu` sobe no primeiro `enfileirar`. Publica exatamente um resultado por item enfileirado.

- [ ] **Step 1: Testes que falham**

```python
def test_gpu_segue_enquanto_cpu_trabalha(tmp_path):
    # b001 vai para CPU; ClienteFalso da CPU espera threading.Event liberado só quando b003 (GPU) terminar.
    # ordem de item.succeeded: b002, b003, b001 — e o teste termina (timeout de 5 s no Event)
def test_thread_cpu_que_morre_nao_trava_a_etapa(tmp_path):        # Review Focus 1
    # synthesize da CPU levanta RuntimeError → b001 item.failed "tts_servidor_indisponivel", execute retorna
def test_excecao_na_principal_encerra_servidores_e_thread(tmp_path):  # Review Focus 2
    # emit levanta na 3ª chamada → ambos ServidorFalso saíram, thread não está viva
def test_servidor_cpu_que_nao_sobe_so_afeta_a_fila_cpu(tmp_path):   # Review Focus 3
    # factory("cpu") levanta ServidorIndisponivel → b001 falha; b002/b003 ok na GPU
def test_contrato_quebrado_na_cpu_falha_so_os_itens_da_fila(tmp_path): ...  # código tts_contrato_servidor
def test_emit_so_e_chamado_da_thread_principal(tmp_path):
    # emit grava threading.get_ident(); todos iguais ao da thread do teste
```

- [ ] **Step 2:** `uv run pytest tests/executors/test_audio.py -q` → FAIL.
- [ ] **Step 3:** Trocar a lista sequencial por `_TrabalhadorCPU`. A principal drena `resultados` com `get_nowait` entre trechos de GPU; no fim espera com `get(timeout=1)` em laço, conferindo `vivo` e itens em aberto (nunca `join` cego). Servidor GPU fica de pé até a fila esvaziar.
- [ ] **Step 4:** mesmo comando → PASS; `uv run pytest -q` → PASS.
- [ ] **Step 5:** `git commit -m "feat(tts): fila de CPU em paralelo à GPU"`

---

### Task 6: Liberação, limpeza e documentação

**Files:**
- Modify: `src/forge/gpu/liberadores.py:387-389`
- Modify: `src/forge/infrastructure/config.py` (remover `tts_batch_size`, `tts_batch_timeout`, `tts_binary`, `resolved_tts_binary`)
- Modify: `CLAUDE.md` (seção do broker: `liberar_tts` não é mais no-op), `C:\dev\audio-generate\README.md`
- Test: `tests/gpu/test_liberadores.py`, `tests/test_config.py:120`, `tests/services/test_preflight.py:93`

**Interfaces:**
- Consumes: `caminho_registro` (Task 2).
- Produces: `liberar_tts(settings, *, executar=subprocess.run) -> None`.

- [ ] **Step 1: Testes que falham** (substituem `test_liberar_tts_e_no_op`)

```python
def test_liberar_tts_mata_servidor_registrado_vivo(tmp_path):
    # registro [{"pid": 77, "backend": "vulkan"}]; linha de comando do PID 77 contém "audiocpp_server"
    # → taskkill /PID 77 /T /F chamado; registro esvaziado
def test_liberar_tts_nao_mata_pid_reaproveitado_por_outro_programa(tmp_path):
    # PID 77 vivo mas linha de comando "notepad.exe" → nenhum taskkill; entrada removida
def test_liberar_tts_sem_registro_nao_faz_nada(tmp_path): ...
```

- [ ] **Step 2:** `uv run pytest tests/gpu/test_liberadores.py -q` → FAIL.
- [ ] **Step 3:** Implementar (linha de comando via a mesma consulta CIM de `diagnose_gpu_orphans`); remover os campos antigos e seus usos em testes; README do `audio-generate`: seção "GPU AMD via audio.cpp (RX 580)" com config, linha de comando, contrato e a armadilha de `options`, e restringir "GPUs AMD não servem" ao caminho torch.
- [ ] **Step 4:** `uv run pytest -q` → PASS; `grep -rn "tts_batch_size\|resolved_tts_binary\|synthesize_batch" src tests` → nada.
- [ ] **Step 5:** commits separados: forge `git commit -m "feat(tts): liberar_tts encerra servidor órfão"`; em `C:\dev\audio-generate` só `git add README.md` + `git commit -m "docs: caminho Vulkan via audiocpp_server"`.

---

### Task 7: Aceite ao vivo

Sem código novo; nada de GPU ocupada por outro processo (conferir LM Studio/ComfyUI desligados).

- [ ] **Step 1:** `uv run pytest tests/integration/test_services_real.py -k tts -q` → PASS (servidor real, um WAV).
- [ ] **Step 2:** Rodar a etapa de áudio de uma run real com ≥ 20 blocos pelo Studio ou `forge`; anotar tempo total e comparar com o da última run feita por CLI (eventos `item.succeeded.duration_ms` no banco). Esperado: ~8 s/bloco na GPU, nenhuma recarga entre blocos no `.servidor-vulkan.log`.
- [ ] **Step 3:** Forçar um trecho para a CPU (script descartável em scratchpad: `ServidorTTS` vulkan + `synthesize` com `max_tokens=20` nas três seeds, depois CPU sem limite) enquanto outro trecho roda na GPU; conferir que o da GPU terminou primeiro.
- [ ] **Step 4:** Validar por **ASR (Whisper)** o WAV saído da CPU e dois da GPU — transcrição bate com o texto. Nunca por RMS/pico.
- [ ] **Step 5:** `tasklist | findstr audiocpp` → nada depois da etapa.
