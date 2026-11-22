# Plano de implementação · Fase 4 do Board Criativo

> **Para agentes:** use superpowers:executing-plans tarefa a tarefa. Passos com checkbox.

**Objetivo.** Relacionar publicação e resultado à próxima análise: o Board acompanha cada episódio aprovado até a janela de medição, a próxima análise cita o episódio com janela e versão da abertura, e o detalhe do vídeo mostra a pauta que o originou.

**Arquitetura.** Nada novo é persistido. O percurso é derivado por leitura: `aprovacoes_pauta` → `runs` (status e snapshot) → `video/publicacao.json` (upload, agendamento, `video_id`, `abertura_sha256`) → `catalogo_canal` (só vídeos públicos confirmados, com `publicado_em`) → cache do detalhe (`janelas.d7`/`d28`, já calculadas desde a publicação pública pela Fase 0). A publicação já usa `runs.canal_id` como destino e já invalida o catálogo do canal ao concluir.

**Stack.** FastAPI, SQLite, Next.js.

**Spec.** [Design do Board Criativo](../specs/2026-11-21-board-criativo-design.md) — "Fase 4", "Retorno da publicação" e "Atualização do histórico".

## Restrições globais

- D+7 e D+28 contam da publicação pública confirmada (`catalogo_canal.publicado_em`), nunca do upload privado.
- Medida indisponível fica ausente; nenhuma janela incompleta é exibida como resultado.
- Autorização de Analytics revogada oculta a observação protegida, mas não a identidade do episódio.
- Episódio publicado fora do Forge continua no catálogo sem pauta nem execução.
- Nova sincronização preserva cards e edições já salvos (já coberto na Fase 1).

## Foco de revisão

1. Execução aprovada ainda sem `publicacao.json`, ou com publicação que falhou: momento "em produção", sem erro.
2. Upload concluído mas vídeo ainda privado/agendado (fora do catálogo público): momento "enviado" ou "agendado", sem janelas.
3. `publicacao.json` ilegível: o episódio aparece como "em produção" e o board abre.
4. Vídeo público há 10 dias: D+7 completa, D+28 pendente.
5. Analytics revogado: fonte do episódio na análise sem observação.

---

### Tarefa 1: Percurso dos episódios no Board e fonte para a próxima análise

**Arquivos:** novo `src/forge/services/episodios_board.py`, `src/forge/domain/board_criativo.py` (`FonteBoard.tipo` ganha `"episodio"`), `src/forge/services/board_criativo.py`, `src/forge/agents/board_criativo.py`, `src/forge/api/routes/board.py`, teste `tests/api/test_board_episodios.py`.

**Interfaces:**
- `episodios(ctx, *, limite=10, hoje: date | None = None) -> list[dict]` com `aprovacao_id`, `revisao`, `titulo`, `run_id`, `run_status`, `momento` (`em_producao` | `cancelado` | `enviado` | `agendado` | `publico` | `janela_completa`), `publicar_em`, `video_id`, `publicado_em`, `janelas` (`d7`/`d28`: `completa`, `observacoes`), `abertura`, `abertura_sha256`, `promessa`, `recorte`, `url` (detalhe do vídeo no Studio).
- `fontes_de_episodios(lista, pode_exibir_analytics) -> list[FonteBoard]` — só episódios públicos; `id = "episodio:<video_id>"`, `texto` com promessa e abertura aprovadas, `observacao` = visualizações da janela completa mais longa.
- `GET /board` expõe `episodios`; `GerarSugestoes` envia as fontes de episódio ao modelo; uma continuação que cita episódio conta como fundamentada.

- [x] Teste `test_percurso_do_episodio`: aprovar; sem publicação → `em_producao`; `publicacao.json` concluída com `publicar_em` → `agendado`; vídeo no catálogo com `publicado_em` de 10 dias → `janela_completa`, `d7.completa` e não `d28.completa`; `abertura` igual à da pauta aprovada.
- [x] Teste `test_publicacao_ilegivel_nao_derruba_board`.
- [x] Teste `test_episodio_publicado_vira_fonte_da_analise`: modelo fake registra as fontes; contém `episodio:<video_id>` com a abertura no texto; continuação que o cita tem `hipotese == False`.
- [x] Teste `test_publicacao_do_board_mantem_canal_aprovado`: publicar a run com `canal_id` de outro canal → 404.
- [x] Implementar, rodar, commit `feat(studio): acompanhar episódios do Board até a medição`.

### Tarefa 2: Detalhe do vídeo mostra a pauta de origem; Board mostra episódios

**Arquivos:** `src/forge/api/routes/insights.py`, `web/lib/insights.ts`, `web/components/insights-video.tsx`, `web/lib/board-criativo.ts`, novo `web/components/board-episodios.tsx`, `web/components/board-criativo.tsx`, `web/components/board-ideia.tsx`, testes `tests/api/test_board_episodios.py`, `web/components/board-episodios.test.tsx`.

**Interfaces:**
- `GET /api/canais/{canal}/videos/{video_id}` ganha `episodio_board` (`revisao`, `titulo`, `promessa`, `recorte`, `abertura`, `decisao`, `abertura_sha256`) quando o vídeo veio de uma execução aprovada no Board; `null` para vídeo externo.
- `EpisodiosBoard`: lista com momento em texto, data pública, estado de D+7/D+28 e links para a execução e o detalhe do vídeo.
- `FonteEditorial` mostra fonte `episodio` com o texto da abertura e a janela da observação.

- [x] Teste API: detalhe de vídeo do Board traz `episodio_board.abertura`; vídeo externo traz `null`.
- [x] Teste web: episódio `janela_completa` mostra "D+7 completa" e link "Ver resultado".
- [x] Implementar, rodar vitest/lint/pytest, commit `feat(studio): pauta de origem no vídeo e episódios no Board`.

### Tarefa 3: Verificação final da spec

- [x] `uv run pytest -q`, `npx vitest run`, `npm run build`.
- [x] Revisão do ramo por um revisor independente; corrigir achados.
- [x] Navegador com o Studio desta árvore: jornada da pauta à execução.
- [x] Marcar caixas e registrar a verificação nos planos das Fases 2–4.

## Verificação

- Pytest cobre o percurso (em produção, agendado, janela completa), publicação ilegível, fonte de episódio na análise, destino da publicação e a pauta de origem no detalhe do vídeo; Vitest cobre a lista de episódios.
- Navegador (cópia do banco): o episódio aprovado aparece como "em produção" no Board. Publicação real e janelas D+7/D+28 de um episódio do Board dependem de um vídeo publicado e não foram exercitadas ao vivo.

## Revisão independente do ramo

Um revisor leu `c3826b4..HEAD` e apontou oito problemas, todos corrigidos com teste:
- Salvamento automático sem fim quando um texto terminava em espaço: a normalização do painel agora apara os textos como o servidor.
- Edição comparada com a pauta salva atual, não com a base: uma gravação de outra aba parecia edição local e podia ser sobrescrita. A edição agora mede contra a sua base e, sem nada pendente, adota a versão salva.
- Gravação com keepalive ao trocar de aba deixava revisão e base defasadas: só a saída da página usa keepalive; trocar de aba grava pelo caminho normal.
- Mensagem da conversa perdida durante outra análise: o envio fica bloqueado e a API responde 409 `analise_em_andamento`.
- Repetir uma etapa posterior pulava o conflito da pauta: a repetição exige refazer a pesquisa, que volta a conferir a pauta.
- Cancelamento sem `finished_at`.
- Medida de episódio chegava ao modelo com Analytics revogado.
- Janelas D+7/D+28 só liam o cache de um período que muda a cada dia: o Board agora agenda a leitura deduplicada do detalhe.
