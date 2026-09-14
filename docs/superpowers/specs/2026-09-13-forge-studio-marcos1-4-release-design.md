# Forge Studio — Entrega Técnica Marcos 1–4

**Data:** 2026-09-13
**Status:** aprovado para planejamento
**Escopo:** tornar os Marcos 1–4 entregáveis e verificáveis localmente, sem antecipar o Marco 5.

## Objetivo

Entregar o Forge Studio como produto técnico local testável: control plane persistente, worker, executores simuláveis, API FastAPI e dashboard Next.js integrados ao mesmo estado SQLite. A entrega deve provar o comportamento contratado com serviços falsos; não deve alegar que executou uma produção real de vídeo.

## Limite da entrega

Inclui:

- Marcos 1–3: fila, máquina de estados, lease, pausa, retomada, invalidação, executores, catálogo e gates de qualidade simuláveis.
- Marco 4: API local, SSE com replay, preview seguro, saúde/configuração e dashboard operacional.
- Regressão completa sem rede, GPU ou serviços externos.

Exclui, por decisão explícita:

- `scripts/start-studio.ps1` e `stop-studio.ps1`;
- importador de runs antigas;
- verificação de pré-requisitos de máquina;
- testes de integração reais com research, LM Studio, áudio, ComfyUI e FFmpeg;
- run real completo e MP4 final.

Esses itens continuam sendo Marco 5. A entrega será nomeada **Entrega técnica M1–M4**, não V1 completa.

## Diagnóstico confirmado

1. A página do dashboard falha ao passar callbacks de um Server Component para um componente cliente, e a raiz constrói estado estático em vez de chamar `useDashboard`.
2. As rotas de vídeo/run/comando retornam placeholders; os serviços da API não são construídos a partir do control plane.
3. O endpoint de eventos responde JSON, não SSE; não há replay por `Last-Event-ID`.
4. Saúde/configuração não são registradas no app e ainda são stubs.
5. A build web falha por dependência de teste ausente e mock incompatível com o contrato `Video`.
6. Há regressões na paginação de eventos, reconciliação de artefatos órfãos, fixtures de consulta Studio e testes de montagem. Parte da suíte ainda usa marcadores `assert False` em vez de provas executáveis.

## Arquitetura de correção

O backend permanece proprietário do estado. `ControlPlaneService`, `StudioQueryService` e os repositórios SQLite serão injetados no `ApiServices`; as rotas só validam HTTP, chamam esses serviços e serializam contratos Pydantic. O stream SSE lê eventos persistidos por cursor, faz replay antes de aguardar novos eventos e nunca usa logs como fonte de estado.

O dashboard será uma fronteira cliente única: instancia o cliente HTTP tipado, chama `useDashboard` e entrega seu estado aos componentes de apresentação. Formulário, ações e preview não duplicam regra do backend. Em indisponibilidade, o painel exibe erro acionável e estado real, nunca dados inventados.

## Ordem de implementação

1. Consertar infraestrutura de testes e regressões M1–M3.
2. Implementar contratos, injeção de serviços e rotas REST reais.
3. Implementar eventos históricos e SSE replayável.
4. Implementar saúde, GPU e configuração mascarada.
5. Conectar cliente web, hook e componentes; remover mocks estáticos.
6. Trocar todos os testes RED por testes de comportamento e validar browser.
7. Executar gates e documentar resultados/exclusões.

## Critérios de aceite — Entrega técnica M1–M4

1. Três vídeos podem ser enfileirados; a prioridade e o histórico sobrevivem ao reinício da API sobre o mesmo SQLite.
2. Um único worker reivindica uma única run; lease vencido interrompe a run.
3. Pausa ocorre somente no limite seguro do item; retomada não refaz artefato válido.
4. Falha parcial, áudio ou imagem incompleta não permite montagem nem `completed`.
5. Retry cria tentativa nova, invalida dependentes, preserva histórico; retry de áudio reexecuta apenas itens falhos.
6. API fornece criação, fila, histórico, detalhe, pause/resume/retry idempotentes, erro `409` de transição, artefatos e preview por ID.
7. Eventos são paginados sem lacunas; SSE respeita `Last-Event-ID` e atualiza o painel sem reload.
8. Preview aceita somente MIME permitido, contém paths dentro da run e suporta `Range` para áudio/vídeo.
9. Saúde de research, LM Studio, ComfyUI, TTS, FFmpeg e GPU é real ou `unavailable`; configuração não expõe segredos.
10. Dashboard renderiza sem erro e mostra serviços, formulário, run ativa, ações, fila, histórico, log, falha e preview; cria vídeo e envia comandos pelo cliente HTTP.
11. `pytest -q`, `python -m compileall -q src/forge`, Vitest, lint, build Next e teste browser passam; não há referência de runtime/teste a `_pipeline-poc`.
12. README e status registram comandos, contagens de teste, commit de entrega e as exclusões explícitas do Marco 5.

## Evidências exigidas

- Um teste de aceite backend cruza criação de três vídeos, restart de API, prioridade, comando idempotente, eventos e preview Range.
- Um teste de aceite do dashboard usa API falsa e EventSource falso para provar composição, ação e atualização ao vivo.
- Um teste browser carrega a tela inicial e executa criação/comando contra API local de teste.
- A suíte padrão não inicia serviços externos nem toma GPU.

## Riscos e contenção

- Não flexibilizar gates de mídia para fazer a suíte passar.
- Não converter endpoints em mocks de apresentação; todo dado vem do SQLite ou probe real/injetado.
- Não iniciar Marco 5 durante a correção. Se um teste exigir serviço externo, usar fake ou marcador de integração.
- Não apagar artefatos durante retry ou reconciliação.
