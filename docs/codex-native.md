# Codex nativo no Forge — independente do Hermes

O Forge implementa HTTP, OAuth, renovação de sessão, texto e imagens dentro do próprio projeto. **Não exige Hermes, proxy, processo de agente nem Codex CLI instalado/em execução.** O transporte antigo via CLI continua disponível apenas com seleção explícita.

## Assinatura: texto e imagens

Configuração no `.env`:

```dotenv
FORGE_PROVIDER=codex
FORGE_MODEL=gpt-6.1-sol
FORGE_CODEX_TRANSPORT=native
FORGE_IMAGE_PROVIDER=codex
FORGE_CODEX_IMAGE_MODEL=gpt-image-2
FORGE_CODEX_IMAGE_QUALITY=medium
```

São modelos diferentes. `gpt-6.1-sol` escreve, planeja e revisa. O endpoint de imagens recebe `gpt-image-2`; não precisa de um agente de texto para chamar a geração. A qualidade aceita `low`, `medium` ou `high`.

O backend de imagem pode **não honrar** modelo, qualidade e tamanho pedidos. Os artefatos registram separadamente `requested_model`, `image_model` (somente se o servidor informar), `requested_quality`, `reported_quality`, `requested_size`, `reported_size` e tamanho real do PNG. Não se inventa identidade de modelo nem se apresenta qualidade pedida como confirmada.

### Login próprio

```powershell
uv sync
uv run forge auth codex login
uv run forge auth codex status
```

Login abre o navegador da conta ChatGPT, usa PKCE/S256 e valida um estado aleatório. O callback registrado usa `http://localhost:1455/auth/callback`, mas o servidor escuta somente em `127.0.0.1`. Porta ocupada ou login não concluído falham com diagnóstico, sem fallback. Tokens e códigos de autorização não são impressos ou registrados.

O armazenamento padrão é `~/.forge/codex/auth.json`, fora do repositório. O Forge renova OAuth automaticamente perto do vencimento, serializa acesso entre processos com lock e grava a rotação de tokens por troca atômica de arquivo. Em Unix os arquivos novos usam modo `0600`; no Windows mantenha a pasta no perfil privado do usuário, protegida por ACL. Não coloque tokens em `.env`, Git ou relatórios.

### Reusar login existente sem copiar credenciais

Opcionalmente aponte diretamente ao arquivo oficial do Codex já autenticado:

```dotenv
FORGE_CODEX_AUTH_FILE=C:/Users/SEU_USUARIO/.codex/auth.json
```

Isso não executa o CLI nem lê qualquer arquivo do Hermes. O Forge lê/renova **esse mesmo arquivo**; não duplica o refresh token em outro armazenamento. O lock do Forge serializa os processos Forge, mas não controla outro aplicativo que use o arquivo simultaneamente. Para isolamento completo de sessão e evitar disputas de renovação com CLI/VS Code, remova essa opção e faça o login próprio acima. A troca de `FORGE_CODEX_AUTH_FILE` troca também a autoridade de autenticação; não há adoção silenciosa de logins de outros apps.

## Alternar para modelos locais

```dotenv
FORGE_PROVIDER=lm-studio
FORGE_MODEL=qwen3.8-9b-distill
FORGE_IMAGE_PROVIDER=comfyui
FORGE_LM_STUDIO_BASE_URL=http://localhost:1234/v1
```

Use o identificador exato do modelo servido pelo LM Studio. Também pode remover `FORGE_MODEL` para usar o padrão do provider. Texto e imagem são independentes: Codex + ComfyUI e LM Studio + Codex funcionam com a mesma seleção de adaptadores. Reinicie API e worker após mudar `.env`; processos já abertos guardam sua configuração.

A pesquisa continua exclusivamente no acervo em `FORGE_ACERVO_URL=http://127.0.0.1:8000`, com trechos e caminhos canônicos citáveis. Nenhuma busca web ou ferramenta é habilitada na chamada de texto. Áudio/TTS e montagem FFmpeg permanecem inalterados. Imagens remotas não tomam slot de GPU nem iniciam ComfyUI.

## Execução, diagnóstico e retomada

```powershell
uv run forge roteiro --provider codex --tema "Liberdade e responsabilidade"
uv run forge-studio-doctor
uv run pytest
```

O `doctor` verifica credenciais utilizáveis, não garante acesso a um modelo sem uma chamada real. Quando os providers correspondentes são Codex, LM Studio e ComfyUI deixam de ser pré-requisitos. `/api/config/effective` informa transporte e modelos pedidos, nunca tokens.

Texto usa Responses SSE com `store=false`, ferramentas vazias, mensagens com papéis preservados e schemas estritos para saídas estruturadas. Resposta sem conclusão, incompleta, recusada ou de modelo diferente falha explicitamente. O Forge não envia `temperature`/`max_output_tokens`, rejeitados por esse endpoint; parâmetros locais de limite de tokens não controlam o backend Codex nativo.

Chamadas não têm retries automáticos de gasto, troca de modelo ou fallback para OpenAI API paga. HTTP 401/403 dá erro de autenticação/acesso; 429 dá `CodexUsageLimitError`. Em imagem, cota interrompe o lote no primeiro item e deixa os seguintes pendentes. A renovação OAuth não repete uma geração.

Cada imagem salva original, PNG normalizado (`FORGE_IMAGE_WIDTH` × `FORGE_IMAGE_HEIGHT`), metadados e recibo `.codex.json`. Hash, prompt, qualidade, modelo pedido e resolução vinculam o cache; corrupção ou mudança de entrada força nova chamada. Um lock por imagem impede gasto duplicado entre processos Forge. Cache válido não exige autenticação nem rede. Seed não é enviada: `seed_applied=false`.

Logs de texto ficam em `FORGE_CODEX_RUNS_DIR` (padrão `output/codex`); originais/logs de imagem em `video/images/.codex-native`. Prompts e respostas contêm material de pesquisa: trate-os como conteúdo do projeto. Eventos de raciocínio não são persistidos.

## Verificação reproduzível

```powershell
uv run python scripts/verify-codex-native.py --research --image
```

Usa as configurações atuais; exige `provider=codex` e transporte nativo. Executa texto com `gpt-6.1-sol`, contrato estruturado Pydantic, opcionalmente pesquisa real e uma imagem. Grava relatório sem credenciais em `output/validations/codex-native-20261023/report.json`. A imagem de smoke é reutilizada se o recibo for válido. Não gera um vídeo inteiro nem reinicia serviços.

## Transporte antigo, opcional

```dotenv
FORGE_CODEX_TRANSPORT=cli
FORGE_MODEL=gpt-6-astra
FORGE_CODEX_MODEL=gpt-6-astra
```

Somente esse modo exige `codex login` e executável Codex. `FORGE_CODEX_MODEL`, `FORGE_CODEX_EFFORT` e `FORGE_CODEX_BIN` são opções do transporte CLI, não selecionam o gerador nativo de imagens. A documentação histórica está em [codex-assinatura.md](codex-assinatura.md).

## Evidência desta implementação

A chamada HTTP nativa e o adaptador LangChain confirmaram `gpt-6.1-sol` com texto e JSON. A geração real pediu qualidade `medium`, mas o servidor reportou `low`; pedido `1536x1024`, original retornado `1672x940`, PNG final `1024x576`. Isso é registrado, não ocultado. Disponibilidade e limites continuam sujeitos à conta e ao backend; funcionamento não significa uso ilimitado ou SLA de API pública.

Referência de protocolo: Hermes Agent, licença MIT, revisão indicada em `THIRD_PARTY_NOTICES.md`. Nenhum código do Hermes é importado em runtime.
