# Plano de implementação · Fase 1 do Board Criativo

**Objetivo.** Escolher uma proposta para o próximo vídeo do canal e retomar o trabalho salvo.

**Arquitetura.** O Studio reaproveita a autorização de canal, a sincronização e os relatórios da Fase 0. SQLite persiste o rascunho e as ideias guardadas por conta e canal. FastAPI valida referências do modelo antes de mostrá-las. Next.js mantém a experiência dentro da navegação do canal.

## Implementação

- [x] Migrar para o schema 8 e persistir o rascunho por conta e canal. Cobrir isolamento, recuperação e conflito de revisão na API.
- [x] Reusar catálogo e relatórios em `services/board_contexto.py`. Amostrar perguntas de comentários públicos sem nomes de autores. Validar campos, categorias e referências no agente. Reusar o rascunho quando o histórico for sincronizado. Uma análise em voo por rascunho pode ser retomada após expiração. [Contrato de comentários do YouTube](https://developers.google.com/youtube/data/reference/rest/v3/commentThreads/list)
- [x] Integrar `web/app/canais/[canal]/proximo-video/page.tsx` à navegação do canal. Mostrar fonte, comparação de campos, pauta manual e ações de desenvolvimento, guarda, descarte e combinação. Cobrir as transições na API e na interface.
- [x] Conferir a jornada visual em navegador com uma sessão autorizada no canal de teste.
- [x] Corrigir o que o aceite visual encontrou: a data das fontes do Board segue o fuso do catálogo (`dataPublicacao`), e a API libera ao subir as reservas de análise deixadas por um processo que parou.

## Contratos para as próximas fases

- `GET /api/canais/{canal}/board` devolve revisão, rascunho, propostas, ideias guardadas, candidata e condição das fontes. A leitura usa a autorização de canal da sessão e agenda a atualização do histórico quando necessário.
- `PUT /api/canais/{canal}/board` recebe um comando com a revisão esperada. Uma versão vencida retorna `409 revisao_board`. A pauta inicial conserva a referência da proposta desenvolvida. Editar, sincronizar o histórico ou gerar outras propostas preserva as ideias guardadas.
- `POST /api/canais/{canal}/board/analises` solicita sugestões ou combinação. Uma reserva por rascunho controla execução concorrente. A conclusão grava contra a versão mais recente da pauta. A atualização de sugestões existentes exige pedido explícito. A combinação permanece candidata até o usuário decidir aplicá-la.
- O modelo recebe os títulos recentes, observações autorizadas da Fase 0 e uma amostra de perguntas. Duração média e percentual médio assistido vêm do cache de detalhe quando disponíveis no mesmo período. As fontes persistidas recebem identificadores verificados no servidor. Uma autorização de Analytics revogada oculta a evidência protegida.

O rascunho expõe as primeiras decisões editoriais. Edição completa, conversa, aprovação e jobs de produção seguem o recorte das fases subsequentes.

## Verificação

- Pytest aprovou 227 casos de API, repositórios e fontes do YouTube. Vitest aprovou 121 casos. Build standalone concluído e lint com zero erros e oito avisos preexistentes.
- A chamada real ao Codex retornou três hipóteses válidas para um canal fictício. Os cenários com histórico, comentário de origem, revogação de Analytics, combinação e falha de geração foram exercitados com fontes simuladas.
- O Studio local subiu com o schema SQLite 8 após backup. O permalink do Board respondeu com HTTP 200 e a API exigiu sessão também pelo endereço web. Aceite visual em 22/11/2026 com o canal Conquistas Cósmicas: rascunho recuperado sem nova análise, justificativas com fonte, guardar, comparação antes de substituir a pauta, combinação real pelo modelo, recarga e nova leitura do histórico preservando o rascunho, e layout em 375 px sem rolagem horizontal.
- Pendências conhecidas para a Fase 2: ideias guardadas ainda não podem ser removidas pela interface, e o controle Descartar tem 17 px de altura no celular.

[Design do Board Criativo](../specs/2026-11-21-board-criativo-design.md)
