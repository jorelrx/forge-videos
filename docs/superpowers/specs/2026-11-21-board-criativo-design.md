# Forge Videos Studio · Estúdio por canal e Board Criativo do próximo vídeo

**Spec para revisão · 21 de novembro de 2026**

## Objetivo e resultado esperado

O criador entra no Studio, acessa um canal autorizado e acompanha seus resultados em **Vídeos e insights**. Ao abrir **Próximo vídeo**, o criador encontra três propostas para o canal que já usa na publicação. Consegue investigar o motivo das sugestões, conversar sobre alternativas, montar uma pauta e iniciar a geração pelo fluxo escolhido. Depois de publicar, os resultados desse episódio passam a informar as próximas propostas. A unidade de trabalho é uma pauta de episódio por canal, com histórico dos episódios enviados à produção.

## Base verificada no checkout

Revisão de 21/11/2026 sobre a árvore de trabalho em `f2c5eb2`, incluindo alterações locais em desempenho e revisão editorial. A inspeção cobre contratos de código. Permissões reais do canal e disponibilidade de métricas dependem da conexão usada na validação.

| Área | Comportamento encontrado | Consequência para o design |
|---|---|---|
| Conta e canal | `src/forge/services/youtube_canais.py` mantém credenciais por canal e um catálogo local com canal padrão. O login em `api/routes/youtube.py` inicia a conexão do YouTube. | A fase 0 precisa definir a sessão da pessoa e seu vínculo com o canal. Escolher o canal padrão local não comprova acesso. |
| Publicação | `src/forge/services/publicacao.py` registra o vídeo na execução, inicia o upload como privado e admite registros antigos sem canal. | Confirmar o canal pelo identificador do vídeo antes de associar registros legados. A data do upload privado não inicia a janela de desempenho público. |
| Métricas | `src/forge/services/desempenho.py` guarda uma medição manual por janela de 7 ou 28 dias em `video/desempenho.json`. Outra entrada na mesma janela substitui a anterior. O registro traz a data de digitação. | Preservar a medição manual ao importar dados automáticos. Data de digitação, sozinha, não comprova cobertura nem data de publicação. Vídeos externos precisam de histórico independente de execução. |
| Fluxos e fila | `src/forge/api/routes/runs.py` resolve o fluxo escolhido, copia sua configuração e chama `ControlPlaneService.enqueue_video`, que abre transação em `src/forge/services/control_plane.py`. | Aprovar a pauta pelo mesmo caminho de criação. Vincular a aprovação à execução na mesma unidade de persistência e recuperar o vínculo em nova tentativa. |
| Recorte e escrita | O checkpoint de proposta editorial passa por `escolher_proposta` e grava `proposta_editorial` no snapshot da execução. Pesquisa e escrita têm executores próprios em `src/forge/executors/`. | Manter distintas a ideia escolhida antes da pesquisa e a decisão editorial tomada com fontes do Acervo. |
| Interface | `web/app/page.tsx` e `web/components/dashboard.tsx` são entradas do Studio. O formulário de novo vídeo, a publicação e o desempenho têm componentes próprios. | Integrar catálogo e Board à navegação, preservar a criação direta e aplicar o contexto de canal também aos acessos existentes. |

## Fase 0 — Layout, login e desempenho do canal

**Entrega independente.** Ao entrar, o criador identifica qual canal está usando, vê os episódios publicados e investiga um resultado até o vídeo de origem. Essa jornada deve funcionar antes de habilitar as sugestões do Board.

### Entrada e contexto da sessão

1. A entrada pública oferece login. A proposta para o MVP é **Entrar com Google**. Conferir o mecanismo de autenticação já existente no checkout e reaproveitar a sessão do Studio quando possível. A identidade da pessoa controla o acesso ao Studio; a conexão de publicação identifica os canais do YouTube que ela pode operar.
2. Após o login, o servidor lista os canais vinculados e autorizados para a conta. Com um canal, abri-lo diretamente. Com vários, restaurar a última seleção ainda autorizada ou mostrar o seletor. Com nenhum, oferecer **Vincular canal** pelo fluxo de publicação existente. Uma conexão legada só fica disponível depois de verificar sua associação com a conta.
3. O cabeçalho exibe avatar e nome do canal, seletor e menu da conta com **Sair**. Toda rota interna e toda consulta de dados valida a sessão e o acesso ao canal no servidor. URLs de detalhe identificam o canal e o vídeo. Link de outro canal exige autorização para ambos.
4. Trocar de canal atualiza navegação, catálogo, indicadores, permissões e rascunho do Board. Descartar respostas atrasadas do canal anterior e manter jobs já iniciados vinculados ao canal de origem. Ao sair ou expirar a sessão, limpar o estado privado da interface e voltar ao login. Se a conexão do YouTube expirar com sessão válida, permitir reconectar o canal e identificar quando ocorreu a última leitura.

### Estrutura da interface

| Região | Comportamento |
|---|---|
| Navegação do Studio | Barra lateral no desktop e menu recolhível em telas menores. Agrupar **Vídeos e insights** e, quando entregue, **Próximo vídeo**, com os acessos existentes de produção e publicação. |
| Cabeçalho persistente | Identidade do canal ativo e da conta. O seletor permanece disponível ao navegar entre catálogo, detalhe e produção. |
| Conteúdo inicial | **Vídeos e insights** é a página inicial após selecionar o canal. No topo, período, data da atualização e ação de sincronizar. Em seguida, resumo do canal e lista paginada de vídeos. |
| Detalhe de vídeo | Selecionar uma linha abre o desempenho do episódio e suas evidências. Voltar à lista restaura período, busca e ordenação. No celular, priorizar título e resultado e mover métricas secundárias para o detalhe. |

### Página Vídeos e insights

**Canal.** Propor os últimos 28 dias como período inicial, com comparação ao período anterior equivalente quando houver cobertura. Mostrar visualizações, tempo de exibição e evolução diária quando disponíveis. Indicar o período efetivamente coberto e destacar observações investigáveis, por exemplo quais vídeos mais contribuíram para o tempo de exibição. Usar agregados do canal ou uma agregação válida de dados do período completo. A paginação da lista não altera o total. Um vídeo antigo que recebeu visualizações no período pode contribuir para o resumo.

**Catálogo.** Incluir vídeos publicados pelo Studio e diretamente no YouTube. Mostrar miniatura, título, data de publicação, visualizações do período quando disponíveis e acesso ao detalhe. Pesquisar por título, ordenar por data ou resultado e carregar páginas adicionais. O período governa os indicadores. Um filtro separado por data de publicação restringe a lista de episódios.

**Episódio.** Mostrar evolução no período e, quando disponíveis, duração média assistida, percentual médio assistido, retenção e resultados D+7/D+28. Para cada insight, indicar medida, janela, base de comparação e origem. Distinguir o que foi observado da interpretação editorial. Reutilizar essas mesmas observações como insumo do Board na fase seguinte.

**Cobertura parcial.** Identificar canal sem publicações, falta de permissão para analytics, período sem dados, falha temporária e histórico desatualizado. Oferecer a ação pertinente — alterar período, sincronizar ou reconectar. Exibir zero apenas quando a fonte retornar zero.

### Critérios de aceite da fase 0

| Verificação | Resultado esperado |
|---|---|
| Abrir uma rota interna deslogado, entrar e depois sair | Login precede o acesso aos dados. Após sair, recarregar a URL exige nova sessão. |
| Entrar com zero, um ou vários canais | A interface apresenta vínculo, abertura direta ou seleção conforme os canais autorizados. |
| Alternar A para B durante uma leitura de A | Cabeçalho e resultados passam a B. Uma resposta tardia de A não reaparece na tela. Uma conta sem vínculo com A recebe recusa também ao chamar a API diretamente. |
| Abrir a página e investigar uma publicação externa ao Forge | O vídeo aparece no catálogo do canal, abre o detalhe correto e permite voltar à lista com os filtros preservados. |
| Mudar período e navegar para outra página da lista | Resumo e detalhe usam o período indicado. O total do canal permanece consistente ao paginar. Métricas ausentes exibem sua condição de disponibilidade. |
| Usar desktop e celular | Login, seletor, navegação, catálogo e detalhe continuam operáveis por teclado e em tela estreita. |

## Abordagem

A página dedicada aceita exploração antes de existir uma execução. Embutir o brainstorm na criação de uma execução exigiria administrar jobs que ainda são ideias. Um chat isolado seria mais simples de construir, mas deixaria a versão aceita da pauta dispersa entre mensagens. A proposta escolhida reúne pauta editável e conversa lateral, e só cria a execução quando o criador seleciona **Criar roteiro**.

## Experiência de edição

1. **Contexto do canal.** Mostrar identidade, última sincronização e até três observações com período, amostra e vídeo de origem. Abrir a página recupera primeiro o rascunho. No primeiro acesso, iniciar sincronização e geração das sugestões automaticamente, com estados visíveis de carregamento e nova tentativa.
2. **Três propostas.** Apresentar uma continuação de tema, uma pergunta do público e uma experiência editorial. Cada card traz título de trabalho, pergunta central, recorte, diferença em relação ao catálogo e justificativa. Com evidência insuficiente, apresentar a proposta como hipótese e adaptar a categoria ao material disponível. Permitir desenvolver, guardar no banco de ideias do canal, combinar duas ou descartar com motivo opcional.
3. **Pauta central.** Campos editáveis de tema, título provisório, público/pergunta, promessa, abertura, sequência de blocos, desfecho, perguntas de pesquisa e referências. Selecionar uma ideia preenche um rascunho. Combinar ideias mostra uma nova proposta para aceitar. Na conversa lateral, a IA sugere alterações em campos identificados; o usuário vê o antes e o depois e escolhe o que aplicar. Salvar edição e conversa ao sair. Em conflito entre abas, mostrar a versão mais recente e permitir reaplicar a edição.
4. **Decisão.** Exibir resumo, pendências e seletor de fluxo. Exigir tema, promessa, uma pauta com pelo menos um bloco e um fluxo disponível. Ao aprovar, congelar a versão e abrir a execução criada. O próximo episódio começa em outro rascunho, com acesso às ideias guardadas.
5. **Pesquisa.** Usar as perguntas e o recorte aprovados como entrada. Na seleção de recorte existente, pré-selecionar a opção compatível quando houver. Se a pesquisa contrariar a promessa, exibir evidência e proposta de ajuste para decisão do criador. Registrar o ajuste na execução, preservando a versão aprovada no board.

## Evidências e uso do modelo

Sincronizar uploads paginados da conexão de publicação e identificar cada vídeo por canal e video_id. Associar a run somente quando já houver vínculo de publicação. Usar o catálogo para avaliar novidade mesmo sem acesso às métricas privadas. Ler permissões efetivamente concedidas e solicitar acesso adicional apenas para a função que precisa dele. Canal desconectado remete à conexão existente. Falha de leitura preserva rascunho e último histórico válido com data visível.

Calcular comparações no servidor. Comparar formato e faixa de duração semelhantes dentro da mesma janela de idade. D+7 e D+28 são janelas desde a publicação; registrar a data pública confirmada e a cobertura efetiva da fonte. Registrar período, fonte, unidade, denominador e cobertura. Totais atuais não preenchem retrospectivamente janelas históricas. Medida indisponível fica ausente. Manter valores importados manualmente com procedência e resolver discrepâncias na visualização. Para o MVP, priorizar catálogo, visualizações comparáveis, duração média ou percentual médio assistido e perguntas presentes em comentários disponíveis. CTR, impressões e curva de retenção entram quando a integração fornecer a combinação de métrica, período e vídeo necessária.

Enviar ao modelo observações calculadas, títulos recentes e amostras relevantes de comentários com identificadores de origem. Conteúdo do canal serve como material de análise. Validar no servidor os campos da resposta e cada referência contra o contexto fornecido. A interface distingue observação medida, interpretação e experimento. Não atribuir causalidade a uma correlação. Canal novo pode ter três hipóteses baseadas no posicionamento editorial informado pelo criador, com indicação de que ainda faltam dados. Se a IA falhar, liberar pauta manual e nova tentativa. Atualizar sugestões exige ação explícita quando já há trabalho salvo.

## Persistência e contratos propostos

Reusar as entidades e os serviços equivalentes encontrados no checkout. Os nomes abaixo descrevem responsabilidades, não nomes obrigatórios de tabelas ou rotas.

| Registro ou operação | Contrato |
|---|---|
| Sessão e canais autorizados | Resolver usuário, canais acessíveis e preferência de canal ativo. Verificar o vínculo a cada operação e isolar o cache por conta, canal, período e permissões. |
| Catálogo e observações | Chave canal + vídeo. Métricas por vídeo, janela, medida e origem. Importação incremental idempotente, com data de última sincronização bem-sucedida. |
| Board | Pertence ao canal e ao espaço autorizado do criador. Um rascunho ativo por canal nesse espaço. Guarda revisão, pauta, conversa, propostas e decisões. Ideias guardadas ficam disponíveis entre episódios. |
| Sugestão | Guarda insumos referenciados, data da análise, campos propostos e estado. Abrir novamente reutiliza o resultado. |
| Aprovação | Recebe revisão esperada e fluxo. Gera snapshot imutável e vincula uma única execução à aprovação. Duplo clique ou retry devolve a mesma execução. Usar transação ou outbox recuperável quando fila e banco forem separados. |
| Retorno da publicação | run → aprovação → board e publicação → video_id. Conservar decisões e versão da abertura usadas para interpretar D+7/D+28. |

Autorizar cada leitura e mutação no servidor para o canal correspondente. Nunca entregar tokens ao navegador ou ao modelo. Alterações de esquema devem aceitar execuções antigas sem board. Manter o custo de leitura e IA controlado com paginação, cache por canal e reutilização de solicitações em andamento.

## Fases e passos de design

Cada fase termina com uma jornada que o criador consegue percorrer e um contrato que a próxima fase consome. Os passos abaixo orientam a revisão do produto e delimitam os futuros planos de implementação.

### Fase 0 · Entrar no canal e investigar um vídeo

1. Desenhar o percurso do login à seleção de canal, incluindo primeiro vínculo, troca, reconexão e saída. Para reivindicar uma conexão legada, exigir login no Studio e nova autorização do YouTube que confirme o mesmo canal. Até confirmar a associação, manter dados privados fora da sessão.
2. Descrever a sequência de telas em desktop e celular: seleção, resumo do período, catálogo, detalhe e retorno com filtros preservados. Incluir carregamento, catálogo vazio e leitura parcial.
3. Definir o que cada número representa. O resumo considera atividade no período, o catálogo tem filtro próprio de publicação e a janela D+7/D+28 começa na publicação pública confirmada. Usar uma janela histórica em comparações apenas quando a fonte confirmar definição, intervalo e cobertura compatíveis.
4. **Saída para revisão.** Percurso navegável em termos de telas e estados, matriz de acesso e contrato da observação (canal, vídeo quando aplicável, medida, unidade, janela, cobertura, fonte). Aceitar a fase pelos cenários da seção “Critérios de aceite da fase 0”. Ela constitui a primeira entrega utilizável sozinha.

### Fase 1 · Escolher uma proposta para o próximo episódio

1. Partir do canal e das observações da fase 0. Ao abrir **Próximo vídeo**, recuperar o trabalho salvo antes de considerar nova geração. Na primeira visita sem histórico, colher o posicionamento editorial do criador para fundamentar hipóteses.
2. Descrever o caminho de cada card até sua justificativa e a fonte. Uma pergunta atribuída ao público exige comentário de origem. Com pouca evidência, identificar a pergunta como hipótese editorial. Uma falha do modelo oferece abertura de pauta manual.
3. Especificar o efeito de desenvolver, guardar, descartar e combinar. Desenvolver inicia a pauta no mesmo rascunho. Combinar exibe uma candidata e aguarda aceite. Quando a pauta já contém edições, mostrar as mudanças propostas antes de substituir campos.
4. **Saída para revisão.** Três propostas distinguíveis para um canal com histórico e três hipóteses para um canal novo com posicionamento informado. O criador consegue inspecionar a justificativa, guardar uma ideia entre episódios e recuperar o rascunho após nova leitura do histórico.

### Fase 2 · Editar e fechar a pauta

1. Dispor pauta e conversa lado a lado no desktop. Em tela estreita, alternar entre as duas preservando campo em edição, texto e conversa.
2. Definir a revisão salva como base de cada sugestão da IA. Mostrar o valor anterior e o proposto por campo. Aplicar somente a escolha do criador. Se outra aba já salvou, recuperar a revisão atual e permitir reaplicar a edição sobre ela.
3. Desenhar a revisão final com tema, promessa, blocos, perguntas de pesquisa e fluxo escolhido. Indicar o campo obrigatório pendente ou o motivo de incompatibilidade do fluxo junto à ação **Criar roteiro**.
4. **Saída para revisão.** Pauta persistente com revisão identificável. O criador recarrega a página, recupera a conversa, aceita só a alteração de abertura e chega à confirmação com pelo menos um bloco e um fluxo compatível.

### Fase 3 · Aprovar a pauta e iniciar o roteiro

1. A confirmação identifica canal, revisão e fluxo. Congelar a pauta aprovada e abrir a execução vinculada. Se a resposta se perder, repetir a mesma aprovação recupera a execução. Uma aba com revisão superada volta à decisão da fase 2.
2. Mapear o briefing até seu primeiro consumidor em cada fluxo compatível. Com pesquisa, entregar perguntas ao Acervo e confrontar o recorte com as fontes. Sem pesquisa, entregar a pauta ao planejamento ou à escrita conforme o fluxo.
3. Desenhar a pausa por contradição: apresentar promessa, evidência e recorte proposto. Aceitar ou editar registra a decisão na execução e retoma o mesmo trabalho. Cancelar encerra esse encaminhamento e preserva a pauta aprovada no histórico.
4. **Saída para revisão.** Uma aprovação corresponde a uma execução mesmo após duplo clique ou falha de resposta. O criador consegue identificar a pauta original, a decisão posterior e o recorte recebido pela escrita. A geração direta por tema segue disponível.

### Fase 4 · Relacionar publicação e resultado à próxima análise

1. Seguir um episódio da aprovação até o vídeo publicado. Na publicação originada do Board, manter o canal aprovado como destino. Para vídeo publicado fora do Forge, abrir catálogo e detalhe pela identidade do YouTube, sem exigir pauta ou execução.
2. Descrever três momentos do episódio: upload privado ou agendado, publicação pública confirmada e janela de medição completa. Exibir a condição disponível em cada momento. Uma publicação concluída invalida o histórico em cache do canal.
3. Reutilizar observações com procedência na próxima análise solicitada. Permitir voltar da justificativa ao detalhe do episódio e consultar a janela e a versão da abertura quando registradas.
4. **Saída para revisão.** Um episódio do Forge fecha o percurso da pauta à evidência. Um episódio externo contribui para o mesmo catálogo. Nova sincronização preserva cards e edições já salvos.

## Passagem para os planos de implementação

Revisar primeiro a jornada independente da fase 0. As fases 1 e 2 compartilham o rascunho do canal. A fase 3 consome sua revisão aprovada. A fase 4 depende tanto da identificação de vídeos da fase 0 quanto do vínculo de aprovação da fase 3. Cada futuro plano herda os contratos de entrada, a saída para revisão e os cenários correspondentes abaixo.

Na revisão de produto, confirmar duas escolhas propostas para a fase 0: login Google para a pessoa e nova autorização para associar canais legados. Na preparação do plano dessa fase, verificar com canal de teste quais permissões e combinações de métricas estão disponíveis. A ausência de uma métrica aciona o estado de cobertura parcial já especificado.

### Cenários de aceite entre fases

| Cenário de aceite | Resultado observável |
|---|---|
| Canal com histórico | Abrir a página apresenta três ideias distintas. Uma recomendação baseada em desempenho permite consultar vídeos, janela, amostra e medida. |
| Dados insuficientes, comentários fechados ou analytics sem permissão | Exibir cobertura real, manter criação de ideias e permitir editar a pauta. Nenhuma métrica é inventada. |
| Rascunho alterado, página recarregada e histórico atualizado | Recuperar edição e conversa. Nova análise preserva alterações manuais e ideias guardadas. |
| IA propõe mudar somente a abertura | Mostrar diferença e aplicar apenas após aceite. O restante da pauta conserva seu conteúdo. |
| Duas abas aprovam a mesma versão ou há falha temporária na fila | Produzir no máximo uma execução para a aprovação e permitir retomar até enfileirar. |
| Canal A e canal B vinculados | Trocar de canal muda histórico e board. Tentativa de acessar um board sem autorização é rejeitada. |
| Geração e publicação | Pesquisa recebe as perguntas, roteiro recebe o recorte decidido e publicação fecha o vínculo. A próxima análise consegue citar o episódio com a janela disponível. |
| Geração direta anterior ao recurso | Iniciar por tema segue funcionando. Runs históricas continuam consultáveis. |

## Limite da primeira entrega

A primeira entrega utilizável é a fase 0. A task completa também cobre o planejamento de um episódio até o encaminhamento ao fluxo existente e o vínculo com seus resultados. Calendário editorial, ranking entre canais, publicação automática a partir do brainstorm e novos geradores de áudio ou imagem ficam para tarefas próprias. A nomenclatura interna, a rota exata e o mecanismo de fila seguem as convenções verificadas no repositório.

## Decisões de integração para o MVP

- **Atualização do histórico.** Ao abrir Vídeos e insights ou o board, servir o cache e sincronizar em segundo plano se a última leitura tiver mais de 24 horas. A ação Atualizar histórico força nova leitura. Uma publicação concluída pelo Forge invalida o cache desse canal. Uma visita posterior pode, assim, incorporar uploads externos e janelas recém-completadas. Atualizar o histórico e recalcular os cards salvos são ações independentes.
- **Compatibilidade dos fluxos.** Oferecer fluxos ativos capazes de consumir a pauta na escrita do roteiro. Quando um fluxo pular a pesquisa ou seleção de recorte, entregar o briefing diretamente ao planejamento ou à escrita. Indicar a razão de indisponibilidade para fluxos que não gerem roteiro. Se houver conflito vindo da pesquisa, pausar antes da escrita e permitir aceitar o recorte revisado, editar a promessa à luz das fontes ou cancelar. Salvar a decisão e retomar a mesma execução.
- **Conflito de métricas.** Para a mesma definição, janela completa e vídeo, a leitura válida da API é o padrão analítico. Conservar a importação manual com origem visível. Se a medida automática estiver ausente, usar a manual identificada; se as definições ou períodos divergirem, apresentar separadamente e excluir a comparação incompatível.
