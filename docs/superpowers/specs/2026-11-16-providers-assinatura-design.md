# Frente 3 — Claude e Google por assinatura

## Intenção

O pedido original: o forge pode usar as assinaturas Claude, OpenAI e Google
que já existem na máquina para gerar texto (sempre a partir do acervo — nunca
sem fonte), imagens e vídeos. OpenAI já entra pelo Codex (texto por OAuth,
imagem por `gpt-image-2`). Esta frente traz Claude e Google para o mesmo
patamar, sem cobrança por chave de API e sem afrouxar a regra da fonte.

O usuário pediu para seguir direto, sem rodada de perguntas. As decisões
abaixo marcadas "decisão minha" são propostas, não acordos.

## Metas

- `FORGE_PROVIDER=claude`: o pipeline inteiro (tema, pesquisa, plano,
  escrita, revisão, plano de mídia, embalagem) roda na assinatura Claude.
- Revisor de outro provider (decisão minha): `FORGE_REVIEW_PROVIDER`
  opcional faz o agente `review` rodar num provider diferente do escritor.
  Modelo que revisa o próprio texto tende a aprová-lo; um segundo modelo é a
  forma mais barata de trazer olhar independente. Vazio = mesmo provider.
- `FORGE_PROVIDER=gemini` (fase B): texto pela assinatura Google, pelo
  Gemini CLI.

## Não-metas

- Imagem e vídeo pelo Google. Imagen/"Nano Banana" e Veo por programa exigem
  chave da API Gemini, cobrada à parte; a assinatura não dá acesso
  programático. Fica fora até o usuário decidir pagar a API.
- Fallback automático entre providers quando a cota acaba. Mesma regra do
  Codex: cota esgotada falha a etapa com mensagem clara; o usuário troca o
  provider e repete a etapa. Fallback silencioso mudaria a cobrança e o
  modelo no meio de um roteiro.

## Anti-metas

- Usar o token OAuth do Claude em HTTP direto (como o Codex nativo faz com o
  da OpenAI). A Anthropic proíbe o uso do login de assinatura fora das
  ferramentas dela. O único caminho é o `claude -p` oficial.
- Chamada que herde do usuário CLAUDE.md, hooks, plugins, skills ou MCP: o
  prompt do roteiro chegaria contaminado (o modo terso deste repositório, por
  exemplo, entraria no texto narrado).
- Chave de API herdada do ambiente mudando a cobrança sem aviso.

## Restrições medidas nesta máquina

- Claude Code 2.1.289, `claude auth status` → `loggedIn: true`,
  `authMethod: claude.ai`. Mesmo assim, a sonda real de `claude -p`
  respondeu `Failed to authenticate: OAuth session expired and could not be
  refreshed`: o usuário precisa rodar `claude auth login` num terminal antes
  da primeira run. O `status` sozinho não prova que a sessão funciona.
- Erro chega com `subtype: "success"` e `is_error: true`, exit 1. O parser
  decide por `is_error`, nunca por `subtype`.
- `--bare` isolaria tudo, mas aceita só `ANTHROPIC_API_KEY` — inútil para
  assinatura. O isolamento vem de `--safe-mode` (desliga CLAUDE.md, skills,
  plugins, hooks, MCP, estilos) + `--strict-mcp-config` + `--tools ""`.
- Gemini CLI não instalado; só o Antigravity, sem API pública. Node 24
  disponível.

## Abordagens

1. **CLI oficial por assinatura** (escolhida). `claude -p` e `gemini -p`
   como subprocesso, igual ao `codex_transport=cli`. Custo: um processo por
   chamada (segundos de partida), cota da assinatura em janelas de 5 h.
2. **OAuth em HTTP direto.** Mais rápido, mas proibido para Claude e frágil
   para Google. Descartada.
3. **Chave de API.** Já existe (`anthropic`). Cobra por token, fora da
   assinatura — não é o que o pedido descreve.

## Desenho

### Provider `claude` (fase A)

- `services/claude_cli.py` — `ClaudeCLI.run(prompt, *, system, model,
  timeout, schema=None) -> ClaudeResponse(text, structured, work_dir,
  usage)`. Erros: `ClaudeError`; `ClaudeUsageLimitError` (cota);
  `ClaudeAuthError` (sessão expirada, com a instrução `claude auth login`).
- argv: `claude -p --output-format json --model <m> --effort <e>
  --safe-mode --strict-mcp-config --tools "" --no-session-persistence
  --exclude-dynamic-system-prompt-sections --system-prompt <system>
  [--json-schema <schema>]`; mensagens não-system em stdin; `cwd` num
  diretório vazio por chamada em `output/claude/call-*`, onde ficam
  `prompt.txt`, `response.json` e `stderr.log` como evidência.
- Ambiente sem `*_API_KEY`, `ANTHROPIC_AUTH_TOKEN` e `ANTHROPIC_BASE_URL`:
  a cobrança fica sempre na assinatura.
- Prazo e encerramento pelo `SubprocessExecutor`, como o Codex.
- `llms/claude.py` — `ClaudeChatModel(BaseChatModel)` no formato do
  `CodexChatModel`: `with_structured_output` passa o schema por
  `--json-schema` e lê `structured_output`; `finish_reason` vem de
  `stop_reason` para o `invoke_structured` continuar distinguindo truncado
  de defeito.
- Config: `Provider` ganha `"claude"`; `MODELO_PADRAO["claude"] =
  "claude-opus-5-5"`; `claude_bin`, `claude_effort` (default `high`),
  `claude_runs_dir`. `resolved_api_key` devolve `None` para `claude`.
- Preflight, `saude` e `GET /api/system`: checam o login. Além do
  `auth status`, uma chamada mínima de verdade — o status mente quando o
  refresh já morreu (medido acima).

### Revisor de outro provider

- `review_provider: Provider | None` e `review_model: str | None`.
- `build_graph(model, settings, revisor=None)`: o nó `review` usa
  `revisor or model`. O executor do roteiro e a CLI constroem o revisor só
  quando `review_provider` está definido e é diferente do principal.
- O artefato de revisão registra provider e modelo de quem revisou.

### Provider `gemini` (fase B)

- Depende de o usuário instalar e logar: `npm install -g
  @google/gemini-cli`, depois `gemini` com a conta Google.
- Mesmo formato (`services/gemini_cli.py`, `llms/gemini.py`). As flags de
  isolamento e de saída estruturada são sondadas na máquina antes do
  código, como foi feito com o Claude; se não houver saída estruturada
  nativa, o schema vai no prompt e a validação Pydantic decide.
- Só texto.

## Fica para quem constrói

- Texto exato das mensagens de erro, nomes internos de helpers.
- Como serializar o histórico de mensagens no stdin (o Codex CLI usa JSON
  de papéis; serve aqui também).
- Teste de integração real do `claude -p` atrás da mesma trava de
  credencial do `tests/test_integration.py`.
