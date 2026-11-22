# Plano de implementação · Fase 3 do Board Criativo

> **Para agentes:** use superpowers:executing-plans tarefa a tarefa. Passos com checkbox.

**Objetivo.** Aprovar a pauta e iniciar o roteiro: uma aprovação congela a revisão e cria exatamente uma execução; a pesquisa recebe as perguntas, confronta a pauta com o Acervo e pausa em contradição; o roteiro recebe o recorte decidido.

**Arquitetura.** A aprovação vive numa tabela própria (`aprovacoes_pauta`, schema 9) com chave única por conta, canal e revisão. A mesma transação SQLite grava a aprovação, cria vídeo e execução (`OperacaoRepository.create_video_and_run`) e abre o próximo rascunho; repetir a chamada devolve a mesma execução. O briefing viaja em `config_snapshot["pauta_aprovada"]`. A pausa por contradição reaproveita o checkpoint editorial do worker (`aguardando_editorial`) com o novo tipo `conflito_pauta`.

**Stack.** FastAPI, SQLite, LangChain, worker do Studio, Next.js.

**Spec.** [Design do Board Criativo](../specs/2026-11-21-board-criativo-design.md) — "Experiência de edição" itens 4–5, "Persistência e contratos" (Aprovação), "Fase 3" e "Compatibilidade dos fluxos".

## Restrições globais

- Uma aprovação corresponde a uma execução, mesmo após duplo clique, duas abas ou resposta perdida.
- Uma aba com revisão superada volta à decisão da Fase 2 (`409 revisao_board`).
- A ideia escolhida antes da pesquisa e a decisão editorial com fontes do Acervo ficam distintas: a pauta aprovada nunca é alterada; a decisão posterior é registrada na execução.
- A geração direta por tema (`POST /api/videos`) segue funcionando; runs antigas sem board continuam consultáveis.
- Todo fluxo cadastrado passa pela pesquisa e pela escrita; por isso nenhum entrega o briefing direto ao planejamento. Runs do Board não passam pela seleção de recortes (`revisao_editorial`), porque a pauta já fixa o recorte.

## Foco de revisão

1. Resposta da aprovação perdida e novo clique depois que o rascunho já avançou: devolve a mesma execução, não 409.
2. Duas abas aprovando a mesma revisão ao mesmo tempo: uma execução.
3. Falha técnica na conferência da pauta (modelo fora do ar): a pesquisa conclui e a execução segue, com aviso; não trava a execução.
4. Conferência citando passagem fora da pesquisa: tratada como falha técnica, não como contradição.
5. Cancelar no conflito: execução `cancelled`, pauta aprovada preservada na tabela e no snapshot.

---

### Tarefa 1: Aprovação idempotente

**Arquivos:** `src/forge/repositories/migrations.py`, `src/forge/repositories/schema.py`, `src/forge/repositories/board_criativo.py`, `src/forge/services/control_plane.py`, `src/forge/api/routes/board.py`, `src/forge/domain/board_criativo.py`, teste `tests/api/test_board_aprovacao.py`.

**Interfaces:**
- Tabela `aprovacoes_pauta(id TEXT PK, conta_id, canal_id, revisao INTEGER, pauta TEXT, fluxo_id TEXT, run_id TEXT, criada_em TEXT, UNIQUE(conta_id, canal_id, revisao))`.
- `ControlPlaneService.enfileirar(conn, *, tema, tese, priority, config_snapshot, workflow_version, git_commit, canal_id) -> tuple[Video, Run]`; `enqueue_video` passa a usá-lo.
- `BoardRepository.aprovar(revisao, validar: Callable[[RascunhoBoard], None], criar_run: Callable[[conn, RascunhoBoard], str]) -> tuple[dict, bool]` (aprovação, criada agora).
- `RascunhoBoard.ultima_aprovacao: dict | None` (`id`, `run_id`, `revisao`, `titulo`). O rascunho novo mantém posicionamento e ideias guardadas e limpa pauta, conversa, propostas, candidata, origem e fluxo.
- `POST /api/canais/{canal}/board/aprovacoes` com `{"revisao", "fluxo_id"}` → 201 `{"aprovacao", "run_id", "board"}`; repetida → 200 com a mesma `run_id`.
- Snapshot da execução: `preset`, `fluxo_geracao`, `pauta_aprovada` (`aprovacao_id`, `revisao`, campos da pauta). `tema = pauta.tema`, `tese = pauta.promessa`.

- [x] Teste `test_aprovar_cria_uma_execucao_e_abre_novo_rascunho`: pauta completa + fluxo → 201; run com `canal_id == "UC1"`, `config_snapshot["pauta_aprovada"]["revisao"]`; board novo sem pauta, com guardadas e `ultima_aprovacao.run_id`.
- [x] Teste `test_repetir_aprovacao_devolve_mesma_execucao`: segunda chamada com a mesma revisão → 200, mesma `run_id`, uma linha em `runs`.
- [x] Teste `test_aprovacao_com_revisao_vencida_ou_pendente`: revisão antiga sem aprovação → 409 `revisao_board`; pauta sem blocos → 422 com a pendência.
- [x] Teste `test_geracao_direta_continua`: `POST /api/videos` com tema cria run sem `pauta_aprovada`.
- [x] Implementar, rodar, commit `feat(studio): aprovar a pauta e criar uma execução`.

### Tarefa 2: Briefing na pesquisa, conferência e pausa por contradição

**Arquivos:** novo `src/forge/agents/pauta.py`, `src/forge/domain/pauta.py`, `src/forge/executors/pesquisa.py`, `src/forge/services/worker.py`, `src/forge/services/control_plane.py`, `src/forge/api/routes/runs.py`, `src/forge/domain/execucao.py`, testes `tests/agents/test_pauta.py`, `tests/services/test_conflito_pauta.py`.

**Interfaces:**
- `PautaEpisodio` (domínio): campos da pauta + `aprovacao_id`, `revisao`; `briefing_pesquisa() -> str` (recorte, promessa e perguntas) e `diretrizes() -> str` (todas as seções para plan/write).
- `ConferenciaPauta`: `compativel: bool`, `explicacao`, `evidencias: list[str]` (caminhos do acervo), `recorte_proposto`, `promessa_proposta`.
- `conferir_pauta(model, pauta, bundle, run_dir=None) -> ConferenciaPauta` — caminho fora da pesquisa levanta `ValueError`.
- Pesquisa com `pauta_aprovada`: `pesquisar(..., pedido=pauta.briefing_pesquisa())`; incompatível → artefato `conflito_pauta` (`video/conflito-pauta.json`, metadata com promessa, recorte, explicação, evidências com título e trecho, propostas). Falha da conferência → evento `warning` e segue.
- Worker: checkpoint de PESQUISA aceita `propostas_editoriais` ou `conflito_pauta`, também quando o snapshot tem `pauta_aprovada`.
- `DecisaoConflitoPauta`: `artefato_id`, `acao: "aceitar" | "editar" | "cancelar"`, `promessa`, `recorte` (obrigatório um deles em `editar`).
- `ControlPlaneService.decidir_conflito_pauta(run_id, decisao) -> Run`: grava `snapshot["decisao_pauta"]` e `snapshot["pauta_decidida"]` e enfileira; `cancelar` leva a run a `cancelled`. Rota `POST /api/runs/{run_id}/conflito-pauta`.
- `RunSnapshot.pauta_episodio` = `pauta_decidida` ou `pauta_aprovada`.

- [x] Teste `test_conferir_pauta_recusa_caminho_inventado` e `test_conferir_pauta_devolve_contradicao`.
- [x] Teste `test_pesquisa_com_pauta_usa_briefing_e_pausa_em_contradicao` (executor com modelo e acervo fakes): `pedido` contém a pergunta de pesquisa; artefato `conflito_pauta` emitido.
- [x] Teste `test_decisoes_de_conflito`: aceitar grava `pauta_decidida.recorte == recorte_proposto` e volta a `queued`; editar usa o texto do criador; cancelar → `cancelled` e `pauta_aprovada` intacta; artefato de outra run → `TransicaoInvalida`.
- [x] Implementar, rodar, commit `feat(studio): confrontar a pauta com o acervo antes da escrita`.

### Tarefa 3: Roteiro recebe o recorte decidido

**Arquivos:** `src/forge/orchestration/graph.py`, `src/forge/executors/roteiro.py`, teste `tests/orchestration/test_graph_pauta.py` (ou junto dos testes do grafo existentes).

**Interfaces:** `build_graph(..., pauta_episodio: PautaEpisodio | None = None)` inclui `pauta_episodio.diretrizes()` nas diretrizes de plan/write; o executor passa `context.pauta_episodio`.

- [x] Teste: diretrizes do grafo contêm o recorte decidido e a abertura da pauta; sem pauta, nada muda.
- [x] Implementar, rodar, commit `feat(studio): roteiro usa a pauta decidida`.

### Tarefa 4: Interface de aprovação e de conflito

**Arquivos:** `web/lib/board-criativo.ts`, `web/hooks/use-board-criativo.ts`, `web/components/board-criativo.tsx`, `web/components/board-decisao.tsx`, `web/components/dashboard.tsx`, `web/hooks/use-dashboard.ts`, `web/lib/api.ts`, `web/lib/contracts.ts`, novo `web/components/pauta-execucao.tsx`, testes `web/components/board-aprovacao.test.tsx`, `web/components/pauta-execucao.test.tsx`.

**Interfaces:**
- `aprovar(revisao, fluxo_id)` no hook: POST; sucesso navega para `/canais/{canal}/producao#/producao?run=<id>`; falha de rede mostra "Tentar de novo" com a mesma revisão; 409 recarrega e volta à revisão final.
- Dashboard: hash `#/producao?run=<id>` seleciona a execução.
- `PautaExecucao`: mostra pauta aprovada (revisão), decisão posterior e recorte recebido; em `aguardando_editorial == "conflito_pauta"`, mostra promessa, evidências e recorte proposto com Aceitar, Editar (promessa e recorte) e Cancelar.

- [x] Teste `criar roteiro aprova e abre a execução`; `repetir após falha usa a mesma revisão`.
- [x] Teste `conflito oferece aceitar, editar e cancelar` (POST com o corpo certo para cada ação).
- [x] Rodar vitest e lint; commit `feat(studio): aprovar a pauta e decidir conflitos no painel`.

## Contratos para a Fase 4

- `aprovacoes_pauta` liga aprovação → `run_id`; `runs.canal_id` é o canal aprovado e a publicação já usa esse canal como destino.
- `config_snapshot["pauta_aprovada"]["abertura"]` e `previa_aprovada_sha256` identificam a versão da abertura do episódio.

## Verificação

- Pytest cobre aprovação idempotente, revisão vencida, pendência, geração direta, conferência da pauta, pausa por contradição e as três decisões; Vitest cobre aprovar, repetir após falha e o painel de conflito.
- Navegador (cópia do banco): Criar roteiro abriu `#/producao?run=<id>` com o painel Pauta do Board; repetir a aprovação da revisão 9 devolveu 200 e a mesma execução; o rascunho novo manteve a ideia guardada.
- Não exercitado de ponta a ponta: a pausa por contradição com Acervo e modelo reais (coberta por testes com modelo e acervo falsos).
