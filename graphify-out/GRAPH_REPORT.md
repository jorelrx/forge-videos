# Graph Report - forge-videos  (2026-09-13)

## Corpus Check
- 198 files · ~160,536 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2050 nodes · 5897 edges · 127 communities (85 shown, 24 thin omitted)
- Extraction: 77% EXTRACTED · 23% INFERRED · 0% AMBIGUOUS · INFERRED: 1370 edges (avg confidence: 0.93)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Manifesto e Runner
- Catálogo e Reconciliação
- Geração de Áudio
- Operação e Worker
- Arquitetura Forge
- Liberação de GPU
- Contratos de Execução
- Configuração e CLI
- Eventos do Control Plane
- Estados do Worker
- Evidência de Pesquisa
- Esquema SQLite
- Executor de Pesquisa
- Agente de Pesquisa
- Modelos LLM
- Qualidade de Roteiro
- Fatiamento de Narração
- Comandos Idempotentes
- Registro de Lacunas
- Beats Visuais
- Grafo de Roteiro
- Configuração Validada
- Domínio Operacional
- Executor de Preparação
- Plano de Mídia
- Revisão de Roteiro
- Executor Plano de Mídia
- Transições do Control Plane
- Supervisão de Subprocesso
- Executor de Áudio
- CLI de Roteiro
- Testes do Broker GPU
- Liberadores de GPU
- Escrita de Roteiro
- Tags de Narração
- Domínio de Mídia
- Executor de Roteiro
- Persistência Operacional
- Política de Retry
- Broker de GPU
- Processo de Etapa
- Job Object Windows
- Integração FFmpeg
- Planejamento Narrativo
- Reuso de Artefatos
- Conexão SQLite
- Montagem do Broker
- Protocolo de Subprocesso
- Fixtures Compartilhadas
- Validação de Domínio
- Encerramento de Descendentes
- Persistência Plano de Mídia
- Cliente ComfyUI
- Cliente do Acervo
- Transações SQLite
- Arquitetura de Conhecimento
- Serviço do Acervo
- Validação Final
- Falhas Job Object
- Prompts de Tema
- Entrypoint de Executores
- Estilo Visual SDXL
- Executor de Pesquisa
- Arquitetura de Agentes
- Armazenamento de Roteiro
- Bootstrap do Studio
- Projeção de Áudio
- Classes de Falha
- Heartbeat de Lease
- Skills Narrativas
- Chunking de Conhecimento
- Contrato de Validação
- Retomada por Artefato
- Pipeline de Vídeo GPU
- Aquisição de Fontes
- Modelo de Teste
- Aceite de Executores
- Cleanup Job Object
- Máquina de Estados Studio
- Inspeção de Processos
- Mock do Juiz
- Resiliência do Juiz
- Executor de Imagens
- Integração LM Studio
- Planos do Studio
- Pesquisa com Fontes
- Modelo de Candidato
- Limites de Configuração
- Validações de Estado
- Validadores Pydantic
- Paths do TTS
- Timeout do LM Studio
- Concorrência SQLite
- Silêncio em Validação
- Contextos de Conexão
- Suspensão Windows
- Smoke Tests
- Tipos Auxiliares
- Tipos Genéricos
- Validação de Heartbeat
- Resolução de Modelo
- Resolução de Credencial
- Redação de Segredos
- Paths de Configuração
- Pacote de Repositórios
- Isolamento de Testes
- Defaults de Modelo
- Isolamento de Chaves
- Raiz do Projeto

## God Nodes (most connected - your core abstractions)
1. `Settings` - 160 edges
2. `OperacaoRepository` - 119 edges
3. `StageName` - 114 edges
4. `RunSnapshot` - 84 edges
5. `Database` - 80 edges
6. `AudioExecutor` - 54 edges
7. `StagePlan` - 52 edges
8. `init_db()` - 52 edges
9. `Roteiro` - 49 edges
10. `RunStatus` - 47 edges

## Surprising Connections (you probably didn't know these)
- `Arquitetura Atual do Forge` --semantically_similar_to--> `Arquitetura Atual do Forge`  [INFERRED] [semantically similar]
  CLAUDE.md → AGENTS.md
- `Verified Literal Quote` --semantically_similar_to--> `Exact Quote Fact-Check Policy`  [INFERRED] [semantically similar]
  docs/superpowers/specs/2026-07-23-k2-estudo-do-chunk-design.md → src/forge/skills/fact_check.md
- `test_recommended_preset_matches_approved_snapshot_and_rejects_secrets()` --uses--> `StudioPreset`  [INFERRED]
  tests/domain/test_execucao.py → src/forge/domain/execucao.py
- `test_gate_rejected_requires_findings()` --uses--> `GateResult`  [INFERRED]
  tests/domain/test_execucao.py → src/forge/domain/execucao.py
- `test_ordem_canônica_põe_audio_antes_de_imagens()` --uses--> `StageName`  [INFERRED]
  tests/domain/test_operacao.py → src/forge/domain/operacao.py

## Import Cycles
- 1-file cycle: `src/forge/repositories/operacao.py -> src/forge/repositories/operacao.py`
- 2-file cycle: `src/forge/domain/operacao.py -> src/forge/repositories/operacao.py -> src/forge/domain/operacao.py`

## Hyperedges (group relationships)
- **Integridade de Evidência de Pesquisa** — pi_skills_ensaio_filosofico_politica_de_citacao_verificada, agents_pesquisa_exclusiva_no_acervo, agents_juiz_de_relevancia, docs_superpowers_plans_2026_09_06_verificar_e_lacunas_realimentacao_de_lacunas [INFERRED 0.85]
- **Produção de Mídia Retomável** — agents_broker_gpu_por_fase, agents_manifesto_retomavel, docs_superpowers_plans_2026_09_06_broker_midia_manifesto_runner_agrupado_por_tipo, docs_superpowers_plans_2026_09_12_forge_studio_worker_worker_com_lease_unico [INFERRED 0.85]
- **Determinismo em Limites Críticos** — docs_superpowers_plans_2026_07_23_k1_documento_chunking_hierarquico_chunking_hierarquico_deterministico, docs_superpowers_plans_2026_09_07_plano_de_midia_deterministico_fatiamento_deterministico, superpowers_sdd_2026_09_13_forge_studio_executors_task_5_report_gate_deterministico_de_roteiro [INFERRED 0.75]
- **Nine-Section Editorial Architecture** — src_forge_prompts_plan_nine_part_thesis_plan, src_forge_prompts_review_fact_verification_handoff, src_forge_prompts_write_nine_section_script_prompt, src_forge_skills_story_argumentative_progression, src_forge_skills_retention_open_loop_structure [EXTRACTED 1.00]
- **Resumable Media Execution** — docs_superpowers_specs_2026_09_06_video_pipeline_design_persistent_item_manifest, docs_superpowers_specs_2026_09_11_forge_video_studio_design_sqlite_operational_truth, docs_superpowers_plans_2026_09_13_forge_studio_executors_artifact_catalog, docs_superpowers_plans_2026_09_13_forge_studio_executors_conservative_reconciliation [INFERRED 0.95]
- **Source-Grounded Research** — docs_superpowers_specs_2026_09_06_video_pipeline_design_local_acervo_research, docs_superpowers_specs_2026_09_06_video_pipeline_design_relevance_judge, src_forge_prompts_queries_semantic_acervo_queries, src_forge_prompts_juiz_relevance_judgment_prompt, src_forge_prompts_research_canonical_path_research, src_forge_skills_fact_check_exact_quote_policy [INFERRED 0.95]

## Communities (127 total, 24 thin omitted)

### Community 0 - "Manifesto e Runner"
Cohesion: 0.07
Nodes (67): Executor, caminho(), carregar(), criar_ou_carregar(), _do_plano(), gravar(), Item, Manifesto (+59 more)

### Community 1 - "Catálogo e Reconciliação"
Cohesion: 0.06
Nodes (47): NamedTuple, ChildEventProjector, ChildProtocolError, Exception, Row, Path, Reconciliador, ReconciliationReport (+39 more)

### Community 2 - "Geração de Áudio"
Cohesion: 0.07
Nodes (43): AudioGenerateClient, AudioOutcome, AudioRequest, classify_audio_failure(), Path, Safe adapter for the local audio-generate batch command., Classify known audio-generate exits without exposing unbounded stderr., _stderr_tail() (+35 more)

### Community 3 - "Operação e Worker"
Cohesion: 0.11
Nodes (15): JSON_OBJECT, Run, StageRun, _iso(), _json(), _now(), OperacaoRepository, Connection (+7 more)

### Community 4 - "Arquitetura Forge"
Cohesion: 0.04
Nodes (48): Arquitetura Atual do Forge, Broker GPU por Fase, Contrato LE dos Agentes, Juiz de Relevância, Loop LangGraph de Revisão, Manifesto Retomável por Item, Pesquisa Exclusiva no Acervo, Plano de Mídia com Cobertura Integral (+40 more)

### Community 5 - "Liberação de GPU"
Cohesion: 0.08
Nodes (29): _Proc, O audiocpp_cli morre sozinho ao terminar o trecho; não há o que descarregar., Ignorar VRAM após /free deixa o heap Vulkan disputar a placa com o TTS., tts_backend=cpu tira o TTS da disputa pela GPU — regressão aqui vira contenção…, Sem `timeout=`, um lms.exe travado pendura esta chamada DENTRO do lock da GPU e…, Mesmo `lms unload --all` travado, mas `/api/v0/models` já não reporta nada…, LM Studio VIVO e ocupado responde ReadTimeout, que é um HTTPError. Ler isso…, ConnectTimeout é irmã de ConnectError apesar de ser TimeoutException: nunca… (+21 more)

### Community 6 - "Contratos de Execução"
Cohesion: 0.15
Nodes (22): ABC, GateResult, StageChildResult, StageExecutionResult, StagePlan, _NoopBroker, Studio audio stage: synthesize, verify and gate every narration block., StageImplementation (+14 more)

### Community 7 - "Configuração e CLI"
Cohesion: 0.10
Nodes (34): BoundLogger, _cmd_roteiro(), _executar_grafo(), _forcar_stdout_utf8(), Path, Executa o grafo LangGraph e retorna o state final., Salva o que foi produzido ate agora em caso de crash., Emite UTF-8 no stdout/stderr independente do codepage do console. No Windows o… (+26 more)

### Community 8 - "Eventos do Control Plane"
Cohesion: 0.12
Nodes (27): Command, Event, _require_utc(), _event_from_row(), EventosRepository, _iso(), _json(), _now() (+19 more)

### Community 9 - "Estados do Worker"
Cohesion: 0.13
Nodes (27): StageName, StageResult, StageStatus, _enqueue(), SuccessExecutor, test_worker_recovery_interrupts_expired_run_and_allows_only_one_followup_claim(), enqueue(), FakeExecutor (+19 more)

### Community 10 - "Evidência de Pesquisa"
Cohesion: 0.08
Nodes (39): _bruto(), _bundle(), colher(), colher_por_query(), _fmt_passagens(), _fmt_passagens_curtas(), _fmt_pedido(), _fmt_pedido_juiz() (+31 more)

### Community 11 - "Esquema SQLite"
Cohesion: 0.16
Nodes (40): Database, init_db(), _index_columns(), _insert_chain(), parametrize, test_artifact_rejeita_run_inexistente(), test_artifact_rejeita_stage_run_de_outro_run(), test_artifact_rejeita_stage_run_inexistente() (+32 more)

### Community 12 - "Executor de Pesquisa"
Cohesion: 0.09
Nodes (23): AcervoIndisponivel, RuntimeError, O acervo não respondeu. Levantar em vez de cair para busca web é deliberado: um…, FakeAcervo, FakeModel, OfflineAcervo, passage(), Path (+15 more)

### Community 13 - "Agente de Pesquisa"
Cohesion: 0.12
Nodes (35): pesquisar(), Quais passagens do acervo realmente respondem ao que se perguntou. Índices, não…, VeredictoRelevancia, _acervo_com_pool(), _passagem(), Índice inventado pelo modelo não pode estourar nem trazer passagem errada., Uma query que não achou NADA é uma lacuna real, mas o acervo já a registrou…, Sem passagem aprovada não há o que sintetizar — e a síntese é a chamada mais… (+27 more)

### Community 14 - "Modelos LLM"
Cohesion: 0.08
Nodes (26): BaseChatModel, build_chat_model(), extract_thinking(), _finish_reason(), invoke_structured(), invoke_with_thinking(), Wrapper que captura thinking e salva progresso., Invoke structured output, retrying only a truncated empty parse. A parser error… (+18 more)

### Community 15 - "Qualidade de Roteiro"
Cohesion: 0.10
Nodes (29): NarrativeSection, BaseModel, Narrative contract shared by planning, writing and deterministic gates., One of the nine stable narrative functions of a script. The object is frozen…, avaliar_roteiro(), _coerce_roteiro(), conferir_roteiro(), conferir_secao() (+21 more)

### Community 16 - "Fatiamento de Narração"
Cohesion: 0.09
Nodes (34): dividir_frases(), extrair_rubrica(), fatiar(), Corta o roteiro em blocos de narração — sem LLM, por construção. Fatiar é…, A rubrica de cena da seção, sem os parênteses. Vazio se não houver. Não é…, O que a voz de fato diz: sem rubrica, sem ênfase markdown., Blocos de 1 a `max_frases` frases, mirando `alvo_palavras` por bloco. O alvo é…, texto_narravel() (+26 more)

### Community 17 - "Comandos Idempotentes"
Cohesion: 0.15
Nodes (26): CommandStatus, CommandType, StrEnum, ComandosRepository, _command_from_row(), IdempotencyConflict, _iso(), _json() (+18 more)

### Community 18 - "Registro de Lacunas"
Cohesion: 0.11
Nodes (29): Registra uma lacuna nos dois arquivos, ou só no nosso. `so_evidencia=True` pula…, registrar_lacuna(), _passagem(), Bytes que não decodificam como utf-8 são um caso real: o arquivo é escrito por…, A linha existente pode ter espaçamento interno irregular (escrita por outro…, Busca vazia não vai para o arquivo do acervo: ele já registrou sozinho. Ver…, O caso que o acervo NÃO detecta: a busca teve sucesso para ele, e as passagens…, O modo "a" do Windows é seek-then-write, não atômico entre processos: medido… (+21 more)

### Community 19 - "Beats Visuais"
Cohesion: 0.15
Nodes (33): propor_beats(), Os beats que o modelo propõe para uma seção, filtrados — sem id. Devolve…, BeatProposto, BeatsDaSecao, O que o modelo devolve por seção: em qual bloco a imagem entra e o quê. `id`…, _blocos(), Dois beats no mesmo bloco não têm como ser distinguidos no tempo — um Beat só…, A trava do plano inteiro: o que a voz diz tem de ser o roteiro inteiro. (+25 more)

### Community 20 - "Grafo de Roteiro"
Cohesion: 0.10
Nodes (28): ReviewResult, build_graph(), node_write(), rotear(), _draft(), grafo_com_acervo(), _passagem(), Pedido de pesquisa do escritor não pode executar review em paralelo. (+20 more)

### Community 21 - "Configuração Validada"
Cohesion: 0.11
Nodes (28): BaseSettings, Settings, propor_beats divide por esse valor para estimar quantas imagens uma seção…, test_acervo_tem_defaults_locais(), test_api_key_fallback(), test_api_key_generica_vence(), test_arquivos_de_lacuna_apontam_para_o_acervo(), test_audio_generation_defaults_and_resolved_paths_stay_under_tool_dir() (+20 more)

### Community 22 - "Domínio Operacional"
Cohesion: 0.14
Nodes (19): field_validator, Artifact, dependentes_de(), ItemStatus, BaseModel, Video, WorkItem, _artifact_from_row() (+11 more)

### Community 23 - "Executor de Preparação"
Cohesion: 0.13
Nodes (20): M, GateFinding, BaseModel, StudioPreset, PreparationExecutor, PreparationInput, BaseModel, Preparation stage: freeze run input before any expensive work. (+12 more)

### Community 24 - "Plano de Mídia"
Cohesion: 0.12
Nodes (29): CoberturaInsuficiente, _conferir_cobertura_relativa(), _conferir_narracao_absoluta(), planejar_midia(), RuntimeError, Prova que o FATIADOR não perdeu nada do que `texto_narravel` produziu. Só isso:…, Prova que a NARRAÇÃO ainda é o roteiro, olhando o texto bruto da seção. É o…, Os blocos não reproduzem o roteiro palavra por palavra. Existe por causa de um… (+21 more)

### Community 25 - "Revisão de Roteiro"
Cohesion: 0.11
Nodes (28): alegacoes_reais(), Descarta o que não é alegação factual. O prompt já pede afirmações, mas o…, _render(), revisar(), `**Sim** (carro volta)` é payload real do run de 2026-09-06. `_PONTUACAO_BORDA`…, Aspas curvas bloqueavam o strip: o modelo local as emite no lugar das retas, e…, Em `1. Sim, o carro volta` a palavra de abertura era o marcador, não a…, O teto NÃO muda: `Não encontrei problemas factuais no roteiro.` tem exatamente… (+20 more)

### Community 26 - "Executor Plano de Mídia"
Cohesion: 0.12
Nodes (16): FailureDetail, LMStudioManager, Small adapter for loading the one local model used by Studio runs., Load the configured model with a fixed, auditable command line., _artifact_value(), hash_json(), MediaPlanExecutor, _NoopBroker (+8 more)

### Community 27 - "Transições do Control Plane"
Cohesion: 0.23
Nodes (24): RunStatus, artifact_for(), count_rows(), enqueue(), parametrize, save_run_status(), stage_for(), test_claim_emits_exact_event_payload_and_empty_queue_has_no_event() (+16 more)

### Community 28 - "Supervisão de Subprocesso"
Cohesion: 0.15
Nodes (24): Run an argv without a shell and translate its bounded JSONL output., SubprocessExecutor, child(), parametrize, repeated_child(), slow_child(), test_callback_failure_is_propagated_after_stdout_is_drained(), test_cancellation_event_terminates_child_after_lease_loss() (+16 more)

### Community 29 - "Executor de Áudio"
Cohesion: 0.22
Nodes (9): GateFinding, RunSnapshot, WorkItemPlan, AudioExecutor, Any, Path, Return every detectable WAV gate failure for one run-local output., Generate one canonical WAV per ``BlocoNarracao`` without shell execution. (+1 more)

### Community 30 - "CLI de Roteiro"
Cohesion: 0.11
Nodes (23): main(), _cli_com_roteiro_aprovado(), _log_limpo(), _monta_run(), Monta um `forge roteiro` que chega ao plano de mídia com roteiro aprovado., O laço não vigiado precisa saber que este erro não muda ao ser repetido.…, Plano já em disco é o comportamento correto de `gravar_plano`, não falha. Em…, Timeout / `Model unloaded by user`: vale retentar, ao contrário da cobertura. (+15 more)

### Community 31 - "Testes do Broker GPU"
Cohesion: 0.11
Nodes (23): _broker(), Estado corrompido significa que ALGO foi reivindicado e perdemos o registro de…, O oposto do teste acima: sem arquivo, ninguém reivindicou nada e liberar seria…, O estado é reescrito exatamente quando um modelo ESTÁ carregado. Uma escrita…, Remover a recuperação de PID morto deixaria o modelo do crash na VRAM., Remover as probes externas deixaria um Comfy iniciado à mão na VRAM., Trocar por item pagaria um reload de modelo por item — o slot é por fase., O modelo continua carregado no serviço externo depois que o forge sai. (+15 more)

### Community 32 - "Liberadores de GPU"
Cohesion: 0.13
Nodes (24): CompletedProcess, LiberacaoFalhou, Slot exclusivo de GPU. Uma RX 580 de 8 GB, três consumidores que não cabem…, O serviço respondeu mas não confirmou a VRAM livre., _base_lm_studio(), diagnose_gpu_orphans(), _esperar(), liberar_imagem() (+16 more)

### Community 33 - "Escrita de Roteiro"
Cohesion: 0.15
Nodes (19): escrever(), _fmt_notas(), Fonte, Nota, BaseModel, RoteiroDraft, RoteiroState, _ler_fontes() (+11 more)

### Community 34 - "Tags de Narração"
Cohesion: 0.14
Nodes (23): _categorias(), _nomes(), _problema(), ValueError, As 43 tags de controle do higgs-tts-3-4b. Espelho de `C:\\dev\\audio-…, Tag fora do catálogo. Descobrir isso na GPU custaria minutos por trecho., Por que `tag` não vale, ou None se ela vale. Um único lugar decide o que é uma…, Remove as tags fora do catálogo e devolve quais foram removidas. Preferido a… (+15 more)

### Community 35 - "Domínio de Mídia"
Cohesion: 0.14
Nodes (22): Beat, BlocoNarracao, PlanoMidia, BaseModel, O plano de mídia: a ponte entre o roteiro aprovado e a execução do vídeo. É o…, Um trecho de 1 a 3 frases, com as tags de controle do TTS., Uma imagem e o ponto da narração em que ela entra., _model() (+14 more)

### Community 36 - "Executor de Roteiro"
Cohesion: 0.14
Nodes (13): Typed research result with the raw passages used by the stage gate.…, ResearchBundle, _NoopBroker, Path, Studio executor that resumes the narrative graph after typed research., ScriptExecutor, _render(), test_research_markdown_artifacts_use_atomic_replace() (+5 more)

### Community 37 - "Persistência Operacional"
Cohesion: 0.20
Nodes (20): artifact_for(), create_run(), parametrize, O guard de run ativa precisa valer também fora de uma transação do service., test_artifact_fk_invalida_propaga_integrity_error(), test_artifact_tardio_de_etapa_invalidada_eh_persistido_como_nao_atual(), test_artifacts_registro_invalidacao_e_filtro_current_only(), test_claim_next_autocommit_nao_reivindica_duas_runs_apos_guardas_concorrentes() (+12 more)

### Community 38 - "Política de Retry"
Cohesion: 0.17
Nodes (14): ExecutionFailure, Any, Exception, RuntimeError, Bounded retries for stage operations., An operation failure carrying its stable detail and class., RetryPolicy, T (+6 more)

### Community 39 - "Broker de GPU"
Cohesion: 0.14
Nodes (12): Recurso, Broker, GPUOcupada, GPUState, _Ilegivel, BaseModel, RuntimeError, Quem ocupa a placa: o recurso, `None` se ninguém, `ILEGIVEL` se o arquivo… (+4 more)

### Community 40 - "Processo de Etapa"
Cohesion: 0.16
Nodes (11): Path, Parent adapter that runs one typed stage in an isolated child process., StageProcessExecutor, StageContext, Path, SeenSubprocess, stage_context(), test_process_executor_rejects_secret_preparation_snapshot_before_disk_touch() (+3 more)

### Community 41 - "Job Object Windows"
Cohesion: 0.17
Nodes (4): Popen, Any, Best-effort Windows containment with kill-on-close semantics., _WindowsJobObject

### Community 42 - "Integração FFmpeg"
Cohesion: 0.15
Nodes (16): build_ken_burns_filter(), concat_files(), MediaProbe, probe_media(), Path, Safe FFmpeg adapter: argv lists, bounded stderr, timeout, no shell., Run ffmpeg with argv list (shell=False), bounded stderr, timeout., Build a zoompan/Ken Burns filter string: scale=7680:4320 -> 1920x1080, yuv420p. (+8 more)

### Community 43 - "Planejamento Narrativo"
Cohesion: 0.18
Nodes (13): planejar(), Plano, carregar(), _chave(), load_skills(), _parse_frontmatter(), _parse_secoes(), Normaliza título de seção: sem acento, sem pontuação de borda, minúsculo. O… (+5 more)

### Community 44 - "Reuso de Artefatos"
Cohesion: 0.19
Nodes (9): A parent-verified prior-stage artifact safe for child reuse., ReusableOutput, CatalogoArtefatos, Connection, Path, Parent-owned artifact catalog; children submit only run-relative events., Return only a prior succeeded item with an intact current file., _resolved_run_file() (+1 more)

### Community 45 - "Conexão SQLite"
Cohesion: 0.15
Nodes (13): _validate_schema_version(), _validate_schema_version_table(), create_run(), db(), parametrize, test_after_filtra_run_sem_mudar_semantica_do_cursor_global(), test_after_rejeita_cursor_negativo(), test_after_rejeita_limit_fora_do_intervalo() (+5 more)

### Community 46 - "Montagem do Broker"
Cohesion: 0.12
Nodes (16): Broker, liberar_tts(), montar_broker(), montar_liberadores(), probe_comfy(), Path, O audiocpp_cli é um processo por trecho: sai e devolve a VRAM sozinho., O broker real, montado a partir de Settings — contraparte do injetado. (+8 more)

### Community 47 - "Protocolo de Subprocesso"
Cohesion: 0.19
Nodes (11): _bounded_lines(), _BoundedText, EventSink, Protocol, Executor adapter for trusted JSONL subprocesses. The child process communicates…, Yield lines while retaining at most ``limit`` characters per line., invalid_event(), read_stderr() (+3 more)

### Community 48 - "Fixtures Compartilhadas"
Cohesion: 0.14
Nodes (12): acervo_fake(), FakeAcervo, lacunas_em_tmp_path(), Acervo falso: passagens fixas, sem rede. Registra as queries recebidas.…, r"""Nenhum teste pode alcançar `C:\dev\research\dados\` por omissão. Os dois…, scripted(), _fixture(), db() (+4 more)

### Community 49 - "Validação de Domínio"
Cohesion: 0.28
Nodes (15): build_model(), Any, parametrize, test_artifact_accepts_safe_relative_paths(), test_artifact_rejects_unsafe_relative_paths(), test_dependentes_de_roteiro_inclui_tudo_apos_roteiro(), test_enums_serializam_com_valores_estaveis(), test_json_fields_accept_nested_json_values() (+7 more)

### Community 50 - "Encerramento de Descendentes"
Cohesion: 0.19
Nodes (15): descendant_child(), process_exists(), Path, root_exits_descendant_child(), terminate_process_tree(), test_cancellation_kills_descendant_after_root_exits_before_teardown(), is_set(), run() (+7 more)

### Community 51 - "Persistência Plano de Mídia"
Cohesion: 0.19
Nodes (14): FileExistsError, caminho_plano(), carregar_plano(), gravar_plano(), _normalizar_bloco_id(), PlanoJaExiste, Path, Deriva o plano de mídia do roteiro aprovado. Roda com o LLM ainda residente, no… (+6 more)

### Community 52 - "Cliente ComfyUI"
Cohesion: 0.17
Nodes (8): ComfyClient, Any, Path, ComfyUI client: mock-enabled for tests, real for production., Any, Testes para ComfyUI client., test_cache_key_is_sha256(), test_client_uses_mock_when_offline()

### Community 53 - "Cliente do Acervo"
Cohesion: 0.16
Nodes (4): Acervo, Client, Obras que o acervo *poderia* ter mas não tem. Usado só para relatar a lacuna ao…, test_integration_research_service_available()

### Community 54 - "Transações SQLite"
Cohesion: 0.15
Nodes (12): BaseException, InterruptTest, test_connection_configura_row_factory_e_isolation_level(), test_connection_cria_diretorio_pai_ausente(), test_connection_fecha_conexao_ao_sair_do_contexto(), test_connection_habilita_wal_foreign_keys_e_busy_timeout(), test_connection_passa_busy_timeout_para_sqlite_connect(), test_connection_usa_busy_timeout_padrao_de_5000_ms() (+4 more)

### Community 55 - "Arquitetura de Conhecimento"
Cohesion: 0.15
Nodes (13): Pipeline Multiagente de Vídeo, Aprendizado Contínuo por Métricas, Arquitetura Departamental Multiagente, Memória Persistente Poliglota, Sistema Operacional de Conteúdo, Normalização unaccent, Retriever Híbrido, Aquisição Remota em Duas Fases (+5 more)

### Community 56 - "Serviço do Acervo"
Cohesion: 0.19
Nodes (10): integration, Cliente da API `acervo` — a única fonte de material de pesquisa do forge. O…, _anexar_evidencia(), _anexar_pergunta(), _append_deduplicado(), Path, Devolve ao acervo as perguntas que ele não soube responder. Duas escritas com…, Corpo do append. Só é chamado com o lock do arquivo em mãos. (+2 more)

### Community 57 - "Validação Final"
Cohesion: 0.29
Nodes (11): _artifact(), FakeArtifact, Path, Testes para executor de validação final., _snapshot(), test_all_sample_frames_must_be_extractable(), test_final_gate_cross_checks_plan_items_and_artifacts(), test_gate_approved_for_complete_run() (+3 more)

### Community 58 - "Falhas Job Object"
Cohesion: 0.15
Nodes (3): test_windows_job_assignment_failure_fails_closed_without_resume(), test_windows_job_unavailable_fails_closed_without_resume(), fail_resume()

### Community 59 - "Prompts de Tema"
Cohesion: 0.26
Nodes (8): gerar_tema(), load_prompt(), parametrize, test_load_prompt(), test_research_prompt_tem_placeholder_tema(), test_tema_fornecido_nao_chama_modelo(), test_tema_gerado(), test_texto_lista_de_blocos_de_conteudo()

### Community 60 - "Entrypoint de Executores"
Cohesion: 0.23
Nodes (8): _absolute_context(), emit(), _implementation(), main(), Any, Path, Allowlisted child-process dispatcher for Studio stages., test_entrypoint_rejects_stage_flag_mismatch_before_importing_executor()

### Community 61 - "Estilo Visual SDXL"
Cohesion: 0.20
Nodes (6): CosmosInteriorPreset, inspect_lora(), LoraInspection, Path, Visual style: Cosmos Interior preset, SDXL LoRA validation., Testes para estilo visual e validação SDXL LoRA.

### Community 62 - "Executor de Pesquisa"
Cohesion: 0.24
Nodes (5): _gravar_texto_atomico(), _NoopBroker, Path, Replace a markdown artifact atomically in its destination directory., ResearchExecutor

### Community 63 - "Arquitetura de Agentes"
Cohesion: 0.20
Nodes (10): Forge Roteiro Pipeline, Review Circuit Breaker, Writer Orchestrator Separation, Dynamic Agent Handoff, Curated Run Artifacts, Declared State Isolation, Global Step Budget, Canonical-Path Research Prompt (+2 more)

### Community 64 - "Armazenamento de Roteiro"
Cohesion: 0.38
Nodes (9): gravar_roteiro(), Path, O caminho canônico é o que torna a citação verificável no acervo., _roteiro(), test_fonte_sem_caminho_sai_sem_parenteses_vazio(), test_fontes_do_acervo_saem_com_caminho_canonico(), test_frontmatter_aprovado_none_quando_nao_informado(), test_grava_arquivo_com_secoes_e_frontmatter() (+1 more)

### Community 65 - "Bootstrap do Studio"
Cohesion: 0.36
Nodes (8): build_control_plane(), build_stage_executors(), build_worker(), Protocol, StageExecutor, enqueue(), test_build_control_plane_duas_vezes_preserva_run_existente(), test_build_control_plane_inicializa_schema_local_e_enfileira_run()

### Community 66 - "Projeção de Áudio"
Cohesion: 0.40
Nodes (8): Path, _run_with_audio_item(), test_audio_child_events_project_without_invalid_transitions_or_duplicate_terminals(), synthesize_batch(), test_catalog_find_reusable_output_requires_intact_prior_current_item(), test_projector_rejects_path_escape_without_creating_artifact(), test_worker_projects_audio_artifact_to_current_catalog_before_audit_event(), _wav()

### Community 67 - "Classes de Falha"
Cohesion: 0.22
Nodes (7): FailureClass, StrEnum, test_failure_classes_are_stable_strings(), test_gate_rejected_requires_findings(), test_recommended_preset_matches_approved_snapshot_and_rejects_secrets(), test_run_snapshot_rejects_run_dir_outside_output_root(), test_stage_plan_requires_stable_unique_item_keys()

### Community 69 - "Skills Narrativas"
Cohesion: 0.39
Nodes (8): Agent Skill Ownership, Owner-Only Skill Procedure, Nine-Part Thesis Plan Prompt, Disputable Theme Prompt, Nine-Section Script Prompt, Retention Through Open Loops, Argumentative Story Progression, Concrete-First Writing Style

### Community 70 - "Chunking de Conhecimento"
Cohesion: 0.25
Nodes (8): Small-to-Big Retrieval, Content-Stable Chunk Identity, Deterministic Structural Pipeline, Two-Tree Knowledge Architecture, Accumulating Semantic Studies, Comprehension Pyramid, Paragraph-Level Study Call, Verified Literal Quote

### Community 71 - "Contrato de Validação"
Cohesion: 0.46
Nodes (3): ArtifactOutput, Gate final cruzado: checa mídia, gates anteriores, WAV, imagens, ffprobe,…, ValidationExecutor

### Community 72 - "Retomada por Artefato"
Cohesion: 0.33
Nodes (7): Artifact Catalog, FFmpeg Compose Executor, Media Plan Executor, Deterministic Narration Slicing, Persistent Item Manifest, SQLite Operational Source of Truth, Visual Beat Prompt

### Community 73 - "Pipeline de Vídeo GPU"
Cohesion: 0.29
Nodes (7): Audio Executor, Hardened GPU Ownership, Image Executor, Exclusive GPU Broker, Source-Grounded Video Pipeline, Audio Before Images, Single GPU Consumer

### Community 74 - "Aquisição de Fontes"
Cohesion: 0.29
Nodes (7): Best-Effort Acquisition, Project Gutenberg Source, Internet Archive Source, Raw HTTP Cache, Remote Source Protocol, Stanford Encyclopedia Source, Wikisource Source

### Community 76 - "Aceite de Executores"
Cohesion: 0.38
Nodes (4): FakeProcessExecutor, test_complete_fake_pipeline_persists_every_gate_and_completes(), test_partial_audio_blocks_compose_and_run_completion(), test_real_registry_has_exactly_the_eight_canonical_stages()

### Community 78 - "Máquina de Estados Studio"
Cohesion: 0.33
Nodes (6): Conservative Run Reconciliation, Script Quality Gate, Cooperative Pause, Dependency-Based Invalidation, Studio Quality Gates, Studio Run State Machine

### Community 79 - "Inspeção de Processos"
Cohesion: 0.40
Nodes (3): ProcessInspector, Path, Consulta conservadora de processo: dúvida nunca vira PID morto.

### Community 81 - "Resiliência do Juiz"
Cohesion: 0.33
Nodes (3): O juiz é opcional (`FORGE_JUIZ_RELEVANCIA`); o roteiro não é. Timeout de 10…, test_juiz_que_estoura_nao_derruba_a_pesquisa(), with_structured_output()

### Community 82 - "Executor de Imagens"
Cohesion: 0.47
Nodes (5): Path, Testes para executor de imagens., _snapshot(), test_image_gate_rejects_when_image_unreadable(), test_retry_uses_same_hash_images_and_renders_only_failed_beats()

### Community 83 - "Integração LM Studio"
Cohesion: 0.47
Nodes (3): Runner, test_lm_studio_loads_recommended_model_with_16k_context(), test_lm_studio_rejects_removed_model_before_running_lms()

### Community 84 - "Planos do Studio"
Cohesion: 0.50
Nodes (5): Typed Executor Contract, Forge Studio Executors Plan, Typed Child Process, Forge Studio Control Plane, Worker and Subprocess Isolation

### Community 85 - "Pesquisa com Fontes"
Cohesion: 0.40
Nodes (5): Autonomous Forge Channel, Local Acervo Research, Passage Relevance Judge, Relevance Judgment Prompt, Semantic Acervo Query Prompt

### Community 86 - "Modelo de Candidato"
Cohesion: 0.40
Nodes (5): _brief_lacuna(), Brief de acervo vazio. Relatar a lacuna é o comportamento correto: o modelo não…, Candidato, BaseModel, Espelha `CandidateOut` do `/discover`: obra sugerida, ainda não ingerida.

### Community 87 - "Limites de Configuração"
Cohesion: 0.40
Nodes (5): parametrize, Aceitar zero desliga silenciosamente timeout/diagnóstico de órfãos., test_audio_generation_limits_are_validated(), test_chave_faltando_falha_claro(), test_limites_de_processos_gpu_devem_ser_positivos()

### Community 93 - "Silêncio em Validação"
Cohesion: 1.00
Nodes (3): Final Validation Gate, Unexpected Silence Fixture, Accepted Silence Fixture

## Knowledge Gaps
- **34 isolated node(s):** `forge-videos`, `Tese Discutível`, `Contra-argumento Honesto`, `Protocolo stage.result`, `Redação de Segredos` (+29 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 568 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **24 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Settings` connect `Configuração Validada` to `Geração de Áudio`, `Liberação de GPU`, `Contratos de Execução`, `Configuração e CLI`, `Estados do Worker`, `Executor de Pesquisa`, `Agente de Pesquisa`, `Modelos LLM`, `Registro de Lacunas`, `Grafo de Roteiro`, `Domínio Operacional`, `Plano de Mídia`, `Executor Plano de Mídia`, `Executor de Áudio`, `CLI de Roteiro`, `Liberadores de GPU`, `Domínio de Mídia`, `Executor de Roteiro`, `Montagem do Broker`, `Cliente ComfyUI`, `Serviço do Acervo`, `Executor de Pesquisa`, `Armazenamento de Roteiro`, `Bootstrap do Studio`, `Projeção de Áudio`, `Aceite de Executores`, `Resiliência do Juiz`, `Executor de Imagens`, `Integração LM Studio`, `Limites de Configuração`, `Paths do TTS`, `Smoke Tests`, `Tipos Auxiliares`, `Tipos Genéricos`, `Validação de Heartbeat`, `Resolução de Modelo`, `Resolução de Credencial`, `Redação de Segredos`, `Isolamento de Testes`, `Defaults de Modelo`, `Isolamento de Chaves`?**
  _High betweenness centrality (0.180) - this node is a cross-community bridge._
- **Why does `StageName` connect `Estados do Worker` to `Catálogo e Reconciliação`, `Geração de Áudio`, `Operação e Worker`, `Contratos de Execução`, `Configuração e CLI`, `Eventos do Control Plane`, `Executor de Pesquisa`, `Comandos Idempotentes`, `Domínio Operacional`, `Executor de Preparação`, `Executor Plano de Mídia`, `Transições do Control Plane`, `Supervisão de Subprocesso`, `Executor de Áudio`, `Domínio de Mídia`, `Executor de Roteiro`, `Persistência Operacional`, `Processo de Etapa`, `Reuso de Artefatos`, `Validação de Domínio`, `Validação Final`, `Entrypoint de Executores`, `Executor de Pesquisa`, `Bootstrap do Studio`, `Projeção de Áudio`, `Classes de Falha`, `Contrato de Validação`, `Aceite de Executores`, `Executor de Imagens`?**
  _High betweenness centrality (0.090) - this node is a cross-community bridge._
- **Why does `Database` connect `Esquema SQLite` to `Bootstrap do Studio`, `Catálogo e Reconciliação`, `Operação e Worker`, `Heartbeat de Lease`, `Projeção de Áudio`, `Paths de Configuração`, `Eventos do Control Plane`, `Processo de Etapa`, `Conexão SQLite`, `Fixtures Compartilhadas`, `Comandos Idempotentes`, `Transações SQLite`, `Domínio Operacional`, `Transições do Control Plane`, `Contextos de Conexão`?**
  _High betweenness centrality (0.050) - this node is a cross-community bridge._
- **Are the 123 inferred relationships involving `Settings` (e.g. with `AudioExecutor` and `AudioGenerateClient`) actually correct?**
  _`Settings` has 123 INFERRED edges - model-reasoned connections that need verification._
- **Are the 38 inferred relationships involving `OperacaoRepository` (e.g. with `Artifact` and `ItemStatus`) actually correct?**
  _`OperacaoRepository` has 38 INFERRED edges - model-reasoned connections that need verification._
- **Are the 83 inferred relationships involving `StageName` (e.g. with `RunSnapshot` and `StagePlan`) actually correct?**
  _`StageName` has 83 INFERRED edges - model-reasoned connections that need verification._
- **Are the 18 inferred relationships involving `RunSnapshot` (e.g. with `Artifact` and `StageName`) actually correct?**
  _`RunSnapshot` has 18 INFERRED edges - model-reasoned connections that need verification._