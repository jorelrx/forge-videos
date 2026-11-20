# Codex com assinatura ChatGPT — transporte CLI histórico

> O padrão atual é **HTTP/OAuth nativo e independente**, documentado em
> [codex-native.md](codex-native.md). As instruções abaixo descrevem somente
> o adaptador anterior, que exige `FORGE_CODEX_TRANSPORT=cli`. As limitações
> de acesso a GPT-6.1 Sol relatadas aqui foram observadas no CLI, não no
> transporte nativo: este último já foi validado com o modelo exato.

O forge pode usar o Codex CLI oficial para roteiro, análise da pesquisa, revisão, planejamento visual e geração nativa de imagens. O Codex gerencia a sessão da assinatura; o forge não lê `auth.json` e não armazena tokens OAuth.

## Ativação

Instale o Codex CLI e execute `codex login`, escolhendo login com ChatGPT. `codex login status` deve informar `Logged in using ChatGPT`. Login por API key é recusado neste backend.

No `.env`:

```dotenv
FORGE_PROVIDER=codex
FORGE_MODEL=gpt-6-astra
FORGE_IMAGE_PROVIDER=codex
FORGE_CODEX_MODEL=gpt-6-astra
FORGE_CODEX_EFFORT=low
```

`FORGE_MODEL` escolhe o agente de texto. `FORGE_CODEX_MODEL` escolhe o agente que chama a ferramenta nativa de imagens, e não o modelo gerador de imagens. `FORGE_CODEX_BIN` permite informar o caminho do executável se `codex` não estiver no PATH. `FORGE_CODEX_RUNS_DIR` define a pasta dos logs de texto, por padrão `output/codex`.

Depois de editar `.env`, reinicie API e worker do Studio para carregar a configuração. O comando de roteiro também aceita `uv run forge roteiro --provider codex --tema "Resiliência"`. `uv run forge-studio-doctor` verifica a sessão e deixa de consultar LM Studio/ComfyUI quando esses serviços foram substituídos pelo Codex.

É possível usar apenas parte da integração: `FORGE_PROVIDER=codex` com `FORGE_IMAGE_PROVIDER=comfyui`, ou manter o provider de texto atual e selecionar `FORGE_IMAGE_PROVIDER=codex`.

## Alternar para modelos locais

Para usar LM Studio no texto e ComfyUI nas imagens, altere apenas estas opções no `.env`:

```dotenv
FORGE_PROVIDER=lm-studio
FORGE_MODEL=google/gemma-4-e4b
FORGE_IMAGE_PROVIDER=comfyui
```

Use em `FORGE_MODEL` o identificador do modelo carregado no LM Studio. Para voltar à assinatura, use `FORGE_PROVIDER=codex`, `FORGE_MODEL=gpt-6-astra` e `FORGE_IMAGE_PROVIDER=codex`. Reinicie API e worker depois da troca.

`FORGE_MODEL` sobrepõe o modelo padrão de qualquer provider. Portanto, trocar somente `--provider` enquanto o `.env` fixa um modelo do outro backend não troca também o modelo. Remova a linha `FORGE_MODEL` para cada provider usar seu próprio padrão. A pesquisa continua na mesma API `research/acervo` em todas as combinações.

## Pesquisa

A fonte continua sendo o projeto `research`, consumido pelo serviço de acervo em `FORGE_ACERVO_URL`. Não há fallback para pesquisa web. O Codex recebe os prompts e passagens que os agentes existentes já utilizam; não ingere livros, não substitui o acervo e não pesquisa por conta própria. Busca web fica desabilitada nas chamadas do CLI.

O revisor recebe a síntese acumulada e os trechos originais com seus caminhos canônicos, inclusive nas verificações dirigidas. A validação reconhece nomes catalogados como `James, William` na ordem natural `William James`; sobrenome isolado exige também a citação do caminho exato daquela fonte.

## Execução e retomada

Cada chamada usa processo isolado, prazo e contenção da árvore de processos. Chamadas de texto rodam com sandbox somente leitura. Ferramentas de shell e busca web ficam desabilitadas em todas as chamadas. A configuração pessoal do Codex não é carregada; a sessão de autenticação continua sendo usada. Não há fallback automático para API paga nem troca automática de modelo após rejeição.

Para cada beat, o agente deve chamar a ferramenta nativa uma vez e retornar o caminho do PNG original. O forge só aceita arquivo recente dentro da pasta da chamada ou do diretório `generated_images` do Codex; verifica conclusão do CLI, JSON final e imagem, e faz a cópia por código. A imagem final é ajustada por recorte central e redimensionamento para `FORGE_IMAGE_WIDTH` x `FORGE_IMAGE_HEIGHT` (padrão 1024 x 576); o original permanece em `video/images/.codex/`. O backend remoto não toma o slot de GPU local nem inicia o ComfyUI.

O recibo `<beat>.codex.json` registra a identidade do pedido, o hash do PNG final e metadados. Repetir a etapa reaproveita uma imagem somente quando pedido, resolução e hash ainda correspondem. Arquivo ausente ou corrompido, mudança de prompt ou de modelo do agente gera uma nova chamada. A seed é apenas parte da identidade do pedido; a ferramenta nativa não expõe seed determinística, e os metadados registram `seed_applied=false`.

Os diretórios das chamadas contêm prompt, schema quando aplicável, eventos JSONL, stderr e resposta final. Falhas indicam o caminho desses logs. `llm_timeout` limita cada chamada de texto e `image_timeout` limita cada chamada de imagem; os limites externos de etapa continuam valendo. Geração consome limites da assinatura.

Quando o CLI informa cota esgotada, a etapa de imagens para na primeira rejeição por cota, com código `codex_usage_limit` e classe `capacity`. Os beats seguintes permanecem pendentes; imagens concluídas e recibos são preservados. A falha não permite repetição automática: aguarde a renovação da cota ou verifique os créditos em https://chatgpt.com/codex/settings/usage e depois repita a etapa. O horário retornado pelo CLI fica no diagnóstico original, sem conversão presumida de fuso. Falhas isoladas de imagem continuam permitindo a execução dos demais beats.

Ao repetir a etapa de roteiro, um plano e um rascunho completos posteriores à pesquisa podem voltar diretamente à revisão. Pesquisa posterior invalida essa retomada. Retomar uma run interrompida também revoga comandos de pausa ainda pendentes da execução anterior.

## Limites verificados

GPT-6 Astra foi aceito pelo CLI desta máquina. A tentativa com GPT-6.1 Sol foi rejeitada antes da geração; o nome permanece configurável, sem garantir disponibilidade. A ferramenta nativa não informou o modelo exato da imagem: esta integração não promete GPT Image 2.5. O JSONL do CLI não exporta os eventos internos da ferramenta nativa, portanto o modelo relatado pelo agente não deve ser tratado como atestado independente de roteamento.

Fontes oficiais: [geração de imagens](https://learn.chatgpt.com/docs/image-generation), [comandos do CLI](https://learn.chatgpt.com/docs/developer-commands). A integração não usa o fluxo externo Sign in with ChatGPT, cujas [limitações](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations) são diferentes das capacidades do próprio Codex.
