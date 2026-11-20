# Integração Codex com assinatura

**Objetivo:** disponibilizar Codex CLI autenticado com ChatGPT como backend de texto e imagens, usando o caminho de imagem validado em `output/validations/codex-image-20261020`.

**Arquitetura:** um serviço encapsula execução sem shell, sessão ChatGPT, prazo, contenção de processos e artefatos por chamada. Um adaptador LangChain atende os agentes existentes; um cliente de imagens atende `ImageExecutor`. Nenhum token OAuth é lido pelo forge. O Codex continua responsável pela autenticação.

**Decisões:** CLI oficial foi escolhido por já ter produzido uma imagem nesta máquina. API paga exige outro faturamento; o fluxo externo Sign in with ChatGPT não suporta geração de imagens. App-server é alternativa futura, sem necessidade para este recorte. Defaults públicos existentes permanecem compatíveis; configuração local pode selecionar Codex explicitamente.

## Restrições

- Backend `codex`, modelo de agente padrão `gpt-6-astra`; modelo de imagem desconhecido, sem alegar GPT Image 2.5.
- Nenhuma leitura de `auth.json`, nenhum fallback para API, nenhuma execução via shell.
- Uma chamada de imagem por beat; imagem original e logs preservados; PNG final normalizado para resolução configurada.
- Codex remoto não toma slot de GPU nem inicia ComfyUI.
- Falha, timeout, saída incompleta e arquivo inválido nunca produzem artefato aprovado.
- Alterações preexistentes em prompts e skills não pertencem a esta implementação.

## Execução

- [x] Testes do serviço: autenticação ChatGPT, argumentos e UTF-8, schema, falha de modelo, timeout, conclusão ausente.
- [x] Serviço Codex: reaproveitar contenção de processos existente; gravar prompt, JSONL, stderr e saída final por chamada, sem credenciais no ambiente filho.
- [x] Adaptador de texto: `BaseChatModel`, texto e JSON validado por schema; provider selecionável sem API key.
- [x] Cliente de imagens: chamada nativa, recusa de saída ausente/corrompida, normalização com Pillow, cache e metadados do backend.
- [x] Integrar seleção em configurações, CLI, executor, doctor e configuração efetiva; cobrir backend remoto sem GPU.
- [x] Documentar ativação, login, limites, retomada e diagnóstico.
- [x] Executar testes focados e suíte padrão sem rede; smoke real de texto e de um beat pela integração, sem executar roteiro completo.

## Aceite

Testes com modelo/processo simulado não acessam rede. Smoke real comprova que o adaptador entrega texto e imagem válida para o mesmo contrato consumido pelo pipeline. Uma chamada concluída não comprova disponibilidade de GPT-6.1 nem identidade do modelo de imagem. Não é necessário alterar interface visual, acervo, áudio ou montagem.

## Evidência final

Adaptadores de texto e imagem passaram nos smokes reais; a retomada reaproveitou o PNG. A suíte completa teve 810 testes aprovados e 8 falhas anteriores em `writing.md`; os 16 testes da escrita/grafo passam com os recursos originais carregados separadamente. As alterações locais do usuário nesses recursos foram preservadas. Testes focados da integração: 154 aprovados; cobertura unitária final: 83 aprovados; contratos específicos de diagnóstico/API: 4 aprovados. Relatório em `output/validations/codex-integration-20261020/report.json`. `.env` local foi configurado para Codex; API e worker precisam reiniciar.
