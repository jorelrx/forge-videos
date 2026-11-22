# Plano de implementação · Fase 0 do Studio por canal

> Para execução por agentes, usar `superpowers:executing-plans` na sessão ou `superpowers:subagent-driven-development` se o responsável escolher delegação. Marcar os passos conforme a evidência obtida.

**Objetivo.** Entrar no Studio com Google, selecionar um canal autorizado e partir de um indicador de desempenho até o vídeo e sua evidência. Esta fase entrega **Vídeos e insights**, junto aos acessos atuais de produção e publicação.

**Arquitetura.** FastAPI valida a sessão e resolve a autorização de cada recurso. SQLite mantém identidade, vínculos, catálogo e observações. O servidor consulta o YouTube por canal e serve a última leitura válida durante a atualização. Next.js compartilha cabeçalho e navegação entre catálogo, detalhe e produção.

**Base.** Checkout `75fb65f`, Python 3.12+, FastAPI, Pydantic, SQLite com migrações versionadas, httpx, Next.js App Router, React, pytest e Vitest. O commit já inclui a revisão editorial, as medições manuais e os fluxos selecionáveis. [Design de origem](../specs/2026-11-21-board-criativo-design.md)

## Restrições e decisões de trabalho

- Adotar as duas propostas da especificação: login Google para a pessoa e nova autorização do mesmo canal para reivindicar conexão legada. A chave da pessoa é o identificador Google estável. Nome, avatar e e-mail são atributos de apresentação.
- Preservar a geração direta por tema, workers, retomada, medições manuais e artefatos existentes. A conta opera somente recursos com vínculo comprovado. A fase termina antes das sugestões e da pauta do Board.
- Proposta de transporte: navegador e API sob a mesma origem através de um rewrite do Next para o FastAPI local. Usar URLs relativas inclusive para SSE, downloads e mídia com `Range`. Hoje `web/lib/api.ts` usa porta 8765 e o CORS não envia credenciais. Validar a configuração no lançamento standalone do Studio.
- Período inicial de 28 dias. Calcular a comparação para os 28 dias anteriores quando a cobertura for equivalente. Sincronizar cache com mais de 24 horas em segundo plano. Atualização explícita antecipa a leitura. Usar a data civil e o fuso do relatório, inclusive em D+7/D+28.
- Sessão Google web e credenciais para publicação têm ciclos de vida distintos. Credenciais e códigos OAuth ficam no servidor. Para a identidade, configurar cliente web e URI de retorno registrada. Reaproveitar a integração instalada para o vínculo de canal. [OpenID Connect do Google](https://developers.google.com/identity/openid-connect/openid-connect)

## Ordem de trabalho e contratos

| Tarefa | Entrega verificável | Depende de |
|---|---|---|
| 1 | Sessão pessoal e logout pela origem do Studio | Base atual |
| 2 | Vínculos, seleção e reconexão por conta | 1 |
| 3 | Isolamento de produção, eventos e arquivos | 2 |
| 4 | Catálogo paginado sincronizado com o YouTube | 2 |
| 5 | Indicadores, janelas e evidências | 4 |
| 6 | Login, seletor e navegação compartilhada | 1–3 |
| 7 | Catálogo e detalhe navegáveis | 4–6 |
| 8 | Aceite da fase pelo fluxo real | 1–7 |

Os caminhos novos abaixo são propostas. Executar os comandos Python na raiz e os comandos npm em `web/`. Em cada tarefa, executar primeiro os casos novos, confirmar que falham pela ausência do comportamento, implementar, repetir os casos e registrar em commit apenas os arquivos da tarefa.

### 1. Identidade e sessão

**Arquivos.** Alterar `src/forge/repositories/migrations.py`, `src/forge/infrastructure/config.py`, `src/forge/api/app.py`, `web/next.config.ts`, `web/lib/api.ts`, `pyproject.toml` e `uv.lock`. Criar `src/forge/services/sessao_studio.py`, `src/forge/api/routes/sessao.py` e `tests/api/test_sessao_studio.py`. Estender `tests/repositories/test_migrations.py`.

- [ ] Introduzir migração v3→v4 para contas, sessões e tentativas de login de uso único. Testar banco novo e cópia sintética v3 com execução, artefato e fluxo existentes. Para as tarefas seguintes, usar migrações incrementais, testando a atualização desde v3 até a última versão.
- [ ] Definir `GET /api/sessao` (401 ou conta com nome/avatar), `GET /api/sessao/google` (redirecionamento), callback e `POST /api/sessao/sair` (204). Testar callback de outra tentativa, expirado ou repetido, login válido e cookie antigo após saída. Exemplo de asserção após logout: `assert cliente.get("/api/sessao").status_code == 401`.
- [ ] Usar cliente OIDC mantido, por exemplo Authlib com descoberta Google; fixar a resolução pelo uv. Validar assinatura, emissor, audiência, validade, nonce e state associado ao navegador. Aceitar retorno interno validado. Persistir somente digest do identificador opaco da sessão, expiração e revogação. Cookie HttpOnly, SameSite=Lax, Secure em HTTPS; HTTP apenas em loopback no ambiente local. Verificar origem/CSRF nas mutações de navegador.
- [ ] Configurar o rewrite `/api/:path*` para o backend e encaminhar cookies e respostas redirect pelo endereço público configurado. Injetar provedor de identidade falso nos testes. Conferir que identidade Google e tokens não aparecem no corpo de erro ou log. Registrar no README a configuração inicial do cliente web.
- [ ] Rodar `uv run pytest tests/api/test_sessao_studio.py tests/repositories/test_migrations.py`. Resultado esperado: sessão persiste no reload, expira, é revogada no logout e preserva os dados anteriores.

### 2. Vínculo da pessoa ao canal

**Arquivos.** Alterar `src/forge/services/youtube_canais.py`, `src/forge/services/youtube_auth.py`, `src/forge/api/routes/youtube.py` e migrações. Criar `src/forge/repositories/acesso_canais.py` e `tests/api/test_acesso_canais.py`. Reusar os doubles de `tests/services/test_youtube_canais.py`.

- [ ] Persistir vínculo único pessoa/canal e preferência de último canal por pessoa. Expor `GET /api/canais` com canais autorizados, estado da conexão e última seleção válida; `PUT /api/sessao/canal` recebe `{"canal_id":"A"}` e valida o vínculo. A preferência serve à próxima entrada; cada aba conserva seu contexto na URL.
- [ ] Adaptar o login de canal hoje compartilhado (`LoginGoogle`) para registrar iniciador, tentativa e canal esperado ao reconectar. Só concluir após identificar no YouTube o canal autorizado e revalidar a sessão iniciadora. Fluxo cancelado, expirado ou retorno para canal diferente conserva o vínculo e credenciais anteriores. Isolar resultado e consulta de progresso por tentativa.
- [ ] Escopar listagem, canal padrão e desconexão do painel à conta. Desvincular uma pessoa preserva credenciais ainda necessárias a outro vínculo ou publicação em andamento. Manter configuração do cliente OAuth da instalação sob controle do operador local; conta comum não pode consultar nem substituir configuração global.
- [ ] Testar conta sem vínculo com índice legado populado, uma conta com A e B, outra só com B, troca após revogação e dois logins simultâneos. Entrar sem canais retorna lista vazia mesmo com token local existente. Uma nova autorização confirmada libera apenas o canal identificado.
- [ ] Rodar `uv run pytest tests/api/test_acesso_canais.py tests/api/test_youtube_conta.py tests/services/test_youtube_canais.py tests/services/test_youtube_auth.py`.

### 3. Produção e publicação dentro do canal

**Arquivos.** Alterar `src/forge/api/app.py`, os routers `runs.py`, `events.py`, `artifacts.py`, `publication.py`, `system.py` em `src/forge/api/routes/`, `src/forge/services/control_plane.py`, `src/forge/services/studio_query.py`, migrações, `web/lib/api.ts` e `web/hooks/use-studio-events.ts`. Criar dependências em `src/forge/api/acesso.py` e casos em `tests/api/test_isolamento_canal.py`.

- [ ] Acrescentar vínculo da execução ao canal na mesma transação de `enqueue_video`. Receber canal explícito da tela. No contrato antigo sem esse campo, resolver canal inequívoco da sessão ou solicitar seleção. A fila do worker continua global; a fila exibida no Studio é filtrada no servidor antes de paginar ou contar.
- [ ] Centralizar verificação de sessão em todos os routers privados. Resolver recurso antes de autorizar: artefato pertence à run, publicação e medição pertencem ao vídeo daquela run. Para listas e SSE global usar canal explícito; para stream de run verificar também a run. Nas conexões longas revalidar acesso e encerrar em revogação. Para rotas globais de configuração restringir visão à informação operacional necessária, mantendo mutações administrativas locais.
- [ ] Vincular histórico com canal comprovado pela publicação; quando faltar canal, reconciliar o `video_id` com o catálogo confirmado da tarefa 4. Conservar histórico sem vínculo em disco/banco e disponível ao operador local. Nunca atribuí-lo à primeira conta que fizer login. Publicar, retomar upload ou acessar permalink exige resolver o canal original.
- [ ] Parametrizar testes de duas contas sobre lista, fila, paginação, comandos, fluxo editorial, medição, publicação, eventos, artefato direto e mídia parcial. Sem sessão retorna 401; recurso de outro canal retorna 404 sem conteúdo privado. SSE de A continua sem eventos de B mesmo se o job de B concluir durante a leitura. Repetir login e garantir que um stream anterior não volta a entregar dados.
- [ ] Atualizar fixtures existentes de `tests/api/conftest.py` para cliente autenticado com dados de teste associados, mantendo cliente anônimo explícito nos casos de acesso. Rodar `uv run pytest tests/api`. Resultado esperado: criação direta, histórico autorizado, retomada e mídia com Range seguem funcionando.

### 4. Sincronização e catálogo de publicados

**Arquivos.** Estender `src/forge/services/youtube.py` e `src/forge/services/publicacao.py`. Criar `src/forge/services/catalogo_canal.py`, `src/forge/repositories/catalogo_canal.py`, `src/forge/api/routes/insights.py`, `tests/services/test_catalogo_canal.py` e `tests/api/test_insights.py`. Registrar router, serviço e migração.

- [ ] Testar com duas páginas de uploads, IDs repetidos, publicação externa, upload privado, vídeo removido e canal B. Buscar a playlist de uploads do canal autenticado, percorrer `nextPageToken`, resolver detalhes dos vídeos em lotes e confirmar canal e visibilidade. Persistir título, miniatura, data pública confirmada e vínculo opcional à execução por identidade. [Paginação da playlist de uploads](https://developers.google.com/youtube/v3/docs/playlistItems/list)
- [ ] Chave do catálogo `(canal_id, video_id)`. Publicar uma geração de catálogo após leitura completa. Reconciliar remoções e mudanças de visibilidade após varredura bem-sucedida; falha na página 2 mantém a geração anterior e seu carimbo. Testar reinício entre páginas e retry com IDs repetidos.
- [ ] Expor `POST /api/canais/{canal}/sincronizacoes` (202) e estado no resumo. Coordenar uma leitura em andamento por canal e conjunto de permissões, com marca persistida e expiração para recuperar interrupção. Servir cache imediatamente, disparar atualização após 24 h e permitir forçar nova leitura. Invalidar o canal no caminho de sucesso da publicação; verificar visibilidade antes de inserir no catálogo público.
- [ ] Expor `GET /api/canais/{canal}/videos` com busca por título, filtro independente de publicação, ordenação e cursor estável com desempate por ID. Ordenação por resultado usa a medida do período entregue pela tarefa 5, com ausentes por último. Testar página seguinte sem repetição e garantir que vídeo externo abre sem run.
- [ ] Rodar `uv run pytest tests/services/test_catalogo_canal.py tests/api/test_insights.py tests/services/test_publicacao.py`. Conferir que duas visitas concorrentes reutilizam o trabalho e que o último sucesso só avança com dados válidos.

### 5. Medidas e evidências do canal e do episódio

**Arquivos.** Criar `src/forge/services/youtube_analytics.py`, `src/forge/services/insights_canal.py`, `src/forge/repositories/observacoes_canal.py` e `tests/services/test_insights_canal.py`. Estender migrações, `insights.py`, `tests/api/test_insights.py` e integração com `src/forge/services/desempenho.py`.

- [ ] Verificar escopos concedidos para leitura do catálogo e do Analytics. Solicitar permissões adicionais na ação de habilitar indicadores; preservar publicação se o usuário recusar. Consultar `reports.query` com canal autorizado, intervalo, relatório e filtro compatíveis: total de views/minutos do canal, série diária e detalhe por vídeo. Consultar duração média, percentual assistido e curva de retenção separadamente quando disponíveis. Validar cabeçalhos e unidades antes de gravar linhas. [Relatórios por canal](https://developers.google.com/youtube/analytics/channel_reports) · [Contrato e permissões da consulta](https://developers.google.com/youtube/analytics/reference/reports/query)
- [ ] Criar contrato de observação com canal, vídeo opcional, medida, valor anulável, unidade, denominador quando aplicável, origem, janela solicitada, intervalo efetivo, cobertura e instante de leitura. Usar chave de cache por conta, canal, intervalo, relatório e permissões efetivas. Revogação limita também o acesso às leituras privadas anteriores.
- [ ] Expor `GET /api/canais/{canal}/resumo?inicio=AAAA-MM-DD&fim=AAAA-MM-DD` e `GET /api/canais/{canal}/videos/{video_id}` com o mesmo período. Entregar resumo, comparação, série, estado da leitura e observações com links de evidência. Buscar total do canal independentemente de catálogo/páginas. Identificar contribuições de vídeos pela medida e cobertura efetivamente consultadas; um ranking parcial precisa informar a amostra.
- [ ] Para D+7/D+28, contar o dia civil da publicação pública como dia 1; fechar após 7/28 dias com cobertura confirmada. Preservar importação manual por janela e origem. Preferir API para definição e janela equivalentes; apresentar definições divergentes em separado. Totais atuais, dia de upload privado e data de digitação são insuficientes para reconstrução histórica.
- [ ] Fixar exemplos nos testes: total do período 120, primeira página de vídeos soma 70, resumo segue 120 em todas as páginas; vídeo antigo com atividade no período entra no total. Medida ausente retorna `null`, zero explícito retorna `0`. Janela de 28 dias com cobertura de 20 não gera comparação completa. Recusa de Analytics preserva catálogo e diferencia autorização, canal vazio, período sem dados, atraso e falha temporária.
- [ ] Rodar `uv run pytest tests/services/test_insights_canal.py tests/api/test_insights.py tests/api/test_publication.py`. Conferir rastreabilidade do indicador até a medida e o vídeo de origem.

### 6. Entrada e navegação compartilhada

**Arquivos.** Alterar `web/app/page.tsx`, `web/app/layout.tsx`, `web/app/globals.css`, `web/lib/api.ts`, `web/lib/contracts.ts`, `web/components/dashboard.tsx`, `web/components/publication.tsx` e hooks existentes de dashboard/eventos. Criar `web/components/sessao-studio.tsx`, `web/app/canais/[canal]/layout.tsx`, `web/app/canais/[canal]/producao/page.tsx` e `web/components/sessao-studio.test.tsx`.

- [ ] A entrada pública oferece **Entrar com Google**. Resolver sessão antes de montar componentes privados. Zero canais oferece vínculo; um abre diretamente; vários restauram a seleção válida ou exibem seletor. Uma URL interna autorizada mantém destino no retorno do login. Em link sem acesso, ocultar dados e permitir voltar aos canais autorizados.
- [ ] Montar cabeçalho com nome, avatar, seletor e menu **Sair**. Barra lateral desktop e menu recolhível em tela estreita incluem **Vídeos e insights**, produção e publicação. Montar dashboard legado no contexto do canal. Ao sair, revogar sessão, fechar stream e limpar estado privado; em 401 fazer a mesma limpeza local. Exibir reconexão do YouTube separadamente da expiração de sessão.
- [ ] Cancelar fetch e SSE anteriores ao trocar de canal. Remontar estado privado pela chave conta/canal e descartar resposta cujo contexto mudou. Testar com resposta A atrasada após navegação para B e job A ainda ativo. Refazer navegação por teclado com abertura, Escape e retorno de foco do menu.
- [ ] Rodar `npm test -- components/sessao-studio.test.tsx hooks/use-dashboard.test.tsx hooks/use-studio-events.test.tsx components/dashboard.test.tsx components/publication.test.tsx`. Conferir 0/1/vários canais, retorno por link, troca, reconexão e logout.

### 7. Vídeos e insights, do resumo ao detalhe

**Arquivos.** Criar `web/app/canais/[canal]/page.tsx`, `web/app/canais/[canal]/videos/[videoId]/page.tsx`, `web/components/insights-canal.tsx`, `web/components/insights-video.tsx` e testes homônimos `.test.tsx`. Estender cliente, contratos e CSS existentes. Reusar formatação de desempenho do Studio quando unidade e definição coincidirem.

- [ ] Página inicial do canal mostra período, última atualização válida, **Atualizar histórico**, views, tempo de exibição, evolução diária e comparação coberta. Abrir uma observação mostra fonte, janela, medida e episódio relacionado. Diferenciar leitura observada de interpretação editorial.
- [ ] Catálogo mostra miniatura, título, data de publicação e views do período, com busca, ordenação e paginação. Gravar período, filtro de publicação, busca, ordem e página na URL. Abrir detalhe compartilha o período e conserva destino de volta. O detalhe exibe evolução, duração média, percentual, retenção e D+7/D+28 disponíveis, com origem e cobertura.
- [ ] Exibir ação de vincular, reconectar, alterar período ou repetir sincronização conforme estado. Em falha transitória manter último sucesso datado. Em tela estreita priorizar título e resultado, com métricas secundárias acessíveis no detalhe. Disponibilizar série também em texto ou tabela, foco visível e controles rotulados.
- [ ] Testar ida e volta de um vídeo externo na segunda página com busca ativa; alteração de período; período sem dados; falha seguida de retry; zero versus ausência; resposta tardia ao navegar. Rodar `npm test -- components/insights-canal.test.tsx components/insights-video.test.tsx lib/api.contract.test.ts`.

### 8. Aceite e registro de evidências

**Arquivos.** Atualizar `README.md` com inicialização, consentimentos, reconexão e procedimento de aceite. Consolidar a verificação entre camadas em `tests/api/test_acceptance.py`. Para o ensaio, usar `scripts/start-studio.ps1` e `scripts/stop-studio.ps1` com armazenamento isolado. O lançador usa as portas 3100 e 8765; verificar se estão livres antes de iniciar a instância de teste.

- [ ] Rodar `uv run pytest`; em `web/`, rodar `npm test`, `npm run lint` e `npm run build`. Registrar resultado e eventuais falhas preexistentes separadamente.
- [ ] Subir build standalone e API pelo fluxo normal. Com sessão ausente, abrir permalink de vídeo; entrar, investigar o episódio, sair e recarregar o permalink. Conferir resposta da API, download com Range e stream em cada estado. Repetir troca A/B com resposta em voo e outra conta sem acesso a A.
- [ ] Com canal de teste autorizado, escolher um vídeo já publicado pelo Forge e outro publicado diretamente no YouTube. Sincronizar, comparar identidades e um indicador no mesmo intervalo do YouTube Studio. Registrar janela, unidade, cobertura e origem. Validar cenário sem Analytics com credencial de teste de permissões reduzidas. Se faltar canal, consentimento ou exemplo de publicação, manter especificamente esse aceite **pendente**, preservando o resultado dos testes offline.
- [ ] Percorrer login, seletor, catálogo, detalhe e retorno apenas por teclado, em desktop e viewport móvel. Paginando ou filtrando data de publicação, conferir que o total do canal fica estável; alterando o período, conferir que resumo e detalhe acompanham. Verificar também produção direta por tema e a titularidade do job depois de trocar de canal.
- [ ] Registrar versão testada, cenários aprovados e pendências. Encerrar a fase com a jornada completa até a evidência do episódio; o contrato de observações fica disponível para o próximo plano.

## Exemplo de contrato entre API e interface

Fixture de aceite para as tarefas 4, 5 e 7: período de 1 a 28 de outubro de 2026, canal A com 120 visualizações confirmadas, primeira página com 70. O vídeo externo `ext-1` foi publicado em setembro e recebeu zero visualizações explicitamente informadas pela fonte em outubro. A interface o inclui ao buscar o título sem filtro de publicação. O mesmo vídeo sai da lista ao filtrar publicações de outubro. Em ambos os casos o resumo mantém 120.

```json
{
  "canal_id": "A",
  "video_id": "ext-1",
  "medida": "visualizacoes",
  "valor": 0,
  "unidade": "visualizacoes",
  "denominador": null,
  "origem": "youtube_analytics",
  "janela": {"inicio": "2026-10-01", "fim": "2026-10-28"},
  "intervalo_efetivo": {"inicio": "2026-10-01", "fim": "2026-10-28"},
  "cobertura": "completa",
  "lido_em": "2026-11-01T12:00:00Z"
}
```

Repetir a fixture com relatório sem linhas. Nesse caso, retornar `valor: null` e cobertura indisponível. Se a leitura falhar depois de um sucesso, manter a observação anterior com seu `lido_em` e expor a falha no estado da sincronização.

## Registro de execução

- Implementação na branch `feat/studio-fase0`. O banco SQLite migra para a versão 6. O histórico com canal de publicação comprovado é associado durante a inicialização ou a sincronização. Registros sem associação comprovada seguem no armazenamento local.
- A checagem HTTP do build standalone usou banco isolado. Confirmou permalink e recursos estáticos, consulta sem sessão com 401, canal sem vínculo com 404, mídia com resposta parcial 206, eventos ao vivo pela API direta e pelo endereço web e revogação no logout.
- A suíte web exercita recuperação de permalink, foco do menu, troca de canal com resposta atrasada, conservação de filtros e distinção entre ausência de métrica e zero observado.
- O aceite com Google e YouTube reais depende de configurar o cliente OAuth web e autorizar um canal de teste com um vídeo publicado pelo Forge e um externo. O percurso visual em navegador móvel e a comparação com métricas reais permanecem pendentes neste registro.
- Validação automatizada: 215 testes Python do recorte da fase 0 e 108 testes web passaram. Build standalone concluído e lint com zero erros. A suíte Python completa registrou 1348 aprovações, 2 skips e uma falha intermitente na leitura de um JSON temporário no teste de cancelamento de subprocessos. Esse teste passou na repetição isolada.
