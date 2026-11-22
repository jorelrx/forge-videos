# Plano de implementação · Fase 2 do Board Criativo

> **Para agentes:** use superpowers:executing-plans (ou subagent-driven-development) tarefa a tarefa. Passos com checkbox.

**Objetivo.** Editar e fechar a pauta do próximo vídeo: pauta completa, conversa com a IA que propõe mudanças por campo, conflito entre abas recuperável e revisão final com fluxo e pendências junto de **Criar roteiro**.

**Arquitetura.** O rascunho continua sendo um JSON em `boards_criativos.dados` com revisão otimista (Fase 1). A pauta ganha campos com valor padrão, então rascunhos antigos validam sem migração. A conversa entra no rascunho; cada resposta da IA guarda a revisão-base e o valor anterior de cada campo. A IA roda pela mesma reserva da Fase 1 (`tipo: "conversa"`). Pendências e fluxos compatíveis são calculados no servidor e expostos em `GET /board`.

**Stack.** FastAPI + Pydantic, SQLite, LangChain (`invoke_structured`), Next.js/React, Vitest, Pytest.

**Spec.** [Design do Board Criativo](../specs/2026-11-21-board-criativo-design.md) — "Experiência de edição" itens 3–4 e "Fase 2".

## Restrições globais

- Campos da pauta: tema, título provisório, público/pergunta, recorte, promessa, abertura, sequência de blocos, desfecho, perguntas de pesquisa e referências.
- Aprovação exige tema, promessa, pelo menos um bloco e um fluxo disponível.
- A IA só altera campos identificados; o criador vê antes e depois e escolhe o que aplicar.
- Conflito entre abas: mostrar a versão mais recente e permitir reaplicar a edição.
- Salvar edição e conversa ao sair. Tokens nunca vão ao navegador ou ao modelo.
- Log com `structlog`, nomes de domínio em português.

## Foco de revisão

1. Rascunho gravado antes desta fase (pauta com 5 campos, sem `conversa`) abre sem erro e mantém os valores.
2. Sugestão da IA feita sobre a revisão N aplicada depois que outra aba salvou N+1: 409, recarga e reaplicação sobre N+1 sem perder o resto da pauta.
3. Resposta da IA com campo desconhecido, lista em campo de texto ou texto acima do limite: rejeitada no servidor, conversa preservada, erro visível.
4. Fechar a aba logo depois de digitar: a edição pendente é enviada (`keepalive`) e reaparece ao reabrir.
5. Tela estreita: alternar Pauta ↔ Conversa preserva texto digitado em ambos.

---

### Tarefa 1: Pauta completa, comandos novos e pendências

**Arquivos:** `src/forge/domain/board_criativo.py`, `src/forge/services/board_criativo.py`, `src/forge/api/routes/board.py`, teste `tests/api/test_board_criativo.py`.

**Interfaces produzidas:**
- `Pauta(PautaInicial)`: `abertura: Texto = ""`, `blocos: list[Texto] (max 12)`, `desfecho: Texto = ""`, `perguntas_pesquisa: list[Curto] (max 8)`, `referencias: list[Curto] (max 10)`. `RascunhoBoard.pauta: Pauta | None`. Listas descartam itens vazios.
- `CAMPOS_PAUTA: tuple[str, ...]` (ordem acima) e `CAMPOS_LISTA = {"blocos", "perguntas_pesquisa", "referencias"}`.
- `RascunhoBoard.fluxo_id: str | None = None`.
- Comandos novos: `{"acao": "fluxo", "fluxo_id"}`, `{"acao": "remover_guardada", "ideia_id"}`.
- `pendencias(board, fluxos) -> list[dict]` com `{"campo", "mensagem"}` para tema, promessa, blocos, fluxo (ausente ou indisponível).
- `fluxos_compativeis(db, canal) -> list[dict]` com `id, nome, descricao, disponivel, motivo` (todo fluxo cadastrado gera roteiro; `motivo` explica quando não).
- `GET /board` expõe `pendencias` e `fluxos`.

- [x] Teste `test_pauta_antiga_abre_com_campos_novos_vazios`: grava `dados` com pauta de 5 campos direto no banco; `GET` devolve `blocos == []`, `abertura == ""` e os 5 valores.
- [x] Teste `test_pendencias_e_fluxo`: pauta só com título → pendências contêm `tema`, `promessa`, `blocos`, `fluxo`; após pauta completa e `{"acao": "fluxo", "fluxo_id": "padrao"}` → `pendencias == []`; `fluxo_id` inexistente → 422.
- [x] Teste `test_remover_guardada`: guardar, remover, `guardadas == []`.
- [x] Rodar e ver falhar; implementar; rodar `uv run pytest tests/api/test_board_criativo.py -q`.
- [x] Commit `feat(studio): pauta completa e pendências do Board`.

### Tarefa 2: Conversa com sugestões por campo

**Arquivos:** `src/forge/domain/board_criativo.py`, `src/forge/agents/board_criativo.py`, `src/forge/services/board_criativo.py`, `src/forge/api/routes/board.py`, teste `tests/api/test_board_criativo.py`.

**Interfaces:**
- `AlteracaoCampo`: `campo` (um de `CAMPOS_PAUTA`), `anterior: str | list[str]`, `valor: str | list[str]` (tipo conforme o campo).
- `MensagemBoard`: `id`, `autor: "criador" | "ia"`, `texto`, `criada_em`, `base_revisao: int | None`, `alteracoes: list[AlteracaoCampo]`, `aplicadas: list[str]`. `RascunhoBoard.conversa: list[MensagemBoard]` (mantém as últimas 60).
- Pedido `{"tipo": "conversa", "revisao", "mensagem"}` (1–2000 caracteres). A reserva grava a mensagem do criador antes de chamar o modelo, e o erro da IA não a apaga.
- `responder_conversa(model, pauta, conversa, fontes) -> RespostaConversa` com `resposta` e `alteracoes` (`campo`, `valor`). Valida campo conhecido e tipo; `anterior` vem da pauta da revisão-base, no servidor.
- Comando `{"acao": "aplicar_sugestao", "mensagem_id", "campos": [...]}`: aplica só os campos escolhidos que a mensagem propõe, registra em `aplicadas`. Revisão vencida → `409 revisao_board`.

- [x] Teste `test_conversa_propoe_so_abertura_e_aplica_so_ela` (cenário "IA propõe mudar somente a abertura"): modelo fake devolve alteração de `abertura`; `GET` mostra a mensagem da IA com `anterior` e `valor`; aplicar `["abertura"]` muda só a abertura.
- [x] Teste `test_sugestao_sobre_revisao_vencida_reaplica`: outra gravação após a sugestão → aplicar com revisão antiga dá 409; com a revisão atual aplica e preserva o campo editado pela outra aba.
- [x] Teste `test_resposta_invalida_preserva_mensagem`: alteração com campo `inventado` → `erro == "analise_indisponivel"` e a mensagem do criador continua na conversa.
- [x] Implementar; rodar a suíte do Board; commit `feat(studio): conversa do Board com sugestões por campo`.

### Tarefa 3: Interface de edição, conversa e revisão final

**Arquivos:** `web/lib/board-criativo.ts`, `web/hooks/use-board-criativo.ts`, `web/components/board-criativo.tsx`, `web/components/board-pauta.tsx`, novo `web/components/board-conversa.tsx`, novo `web/components/board-decisao.tsx`, `web/app/globals.css`, testes `web/components/board-criativo.test.tsx`, novo `web/components/board-conversa.test.tsx`.

**Interfaces:**
- Tipos TS espelham `Pauta`, `MensagemBoard`, `pendencias`, `fluxos`, `fluxo_id`.
- `useBoardCriativo` ganha `pendente` (pauta local não salva), autosave com atraso de 1200 ms, envio com `keepalive` em `visibilitychange`/`pagehide`, e `conflito: {local: Pauta, atual: Board} | null` em 409.
- `EditorPauta` edita listas (adicionar, remover, reordenar blocos; uma linha por pergunta/referência).
- `ConversaBoard`: histórico, campo de mensagem, para cada sugestão a tabela campo · antes (base) · atual (quando mudou) · proposta, com checkbox por campo e "Aplicar selecionadas".
- `DecisaoPauta`: resumo, lista de pendências, seletor de fluxo (indisponível com motivo) e botão **Criar roteiro** desabilitado com o motivo ao lado. Nesta fase o botão chama `onCriar` (Tarefa 1 da Fase 3 liga à aprovação).
- Layout: `.board-workspace` com pauta e conversa lado a lado a partir de 1024 px; abaixo, abas Pauta/Conversa que só ocultam (`hidden`), sem desmontar.
- Ideia guardada ganha "Remover"; "Descartar" com alvo de toque de 24 px ou mais.

- [x] Teste `aplica só a abertura proposta pela IA`: render com mensagem IA propondo abertura; marcar e aplicar → PUT com `{"acao": "aplicar_sugestao", "campos": ["abertura"]}`.
- [x] Teste `conflito mostra a versão atual e reaplica a edição`: PUT devolve 409, GET devolve revisão nova; tela mostra o valor atual e "Reaplicar minha edição" faz PUT com a revisão nova e a pauta local.
- [x] Teste `revisão final aponta pendência ao lado de Criar roteiro`: pauta sem blocos → botão desabilitado e texto "Inclua pelo menos um bloco".
- [x] Teste `abas preservam o texto digitado`: digitar na mensagem, trocar para Pauta e voltar, texto continua.
- [x] Rodar `npx vitest run`, `npx eslint . -c eslint.config.mjs`; commit `feat(studio): edição, conversa e revisão final da pauta`.

### Tarefa 4: Verificação da fase

- [x] `uv run pytest -q`, `npx vitest run`, `npm run build`.
- [x] Navegador: recarregar recupera conversa e pauta; aceitar só a abertura; chegar à revisão final com um bloco e um fluxo.
- [x] Registrar resultado neste plano e marcar as caixas.

## Contratos para a Fase 3

- `GET /board` devolve `pauta` completa, `fluxo_id`, `fluxos` e `pendencias`. A Fase 3 aprova uma `revisao` cujo `pendencias == []`.
- `DecisaoPauta.onCriar(revisao, fluxo_id)` é o ponto de entrada da aprovação.

## Verificação

- Pytest e Vitest cobrem pauta antiga, pendências, conversa com revisão-base, revisão vencida, resposta inválida, conflito entre abas, autosave e abas em tela estreita.
- Navegador (Studio desta árvore com cópia do banco, 22/11/2026): o rascunho da Fase 1 (revisão 5, cinco campos) abriu com os campos novos vazios; bloco salvo por autosave; a IA real propôs só a abertura; aplicar mudou só a abertura; recarregar recuperou conversa e pauta; Criar roteiro liberado com um bloco e o fluxo Padrão.
