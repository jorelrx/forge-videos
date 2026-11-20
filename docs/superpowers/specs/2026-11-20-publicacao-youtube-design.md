# Publicação no YouTube (frente 5) — design

## Intenção

O dono do canal assiste aos vídeos prontos e quer, só para os que aprovar,
mandá-los ao YouTube sem baixar arquivo nem copiar campo. A revisão final
continua dele: o vídeo sobe **privado** ou **agendado**, com tudo preenchido, e
ele libera no YouTube Studio.

## Objetivos

1. `forge auth youtube login|status`: login OAuth da conta Google uma vez,
   com o cliente OAuth (tipo desktop) que o usuário cria no Google Cloud.
2. Upload pela YouTube Data API v3: vídeo, título escolhido, descrição, tags,
   categoria, idioma, "não é para crianças", marca de conteúdo sintético,
   privacidade privada ou `publishAt`; depois thumbnail e legenda `.srt`.
3. Retomável: o estado vive em `<run>/video/publicacao.json`. Cair no meio do
   envio não sobe o vídeo duas vezes; repetir o comando continua de onde parou.
4. Disparo pelo painel (aba Publicação) e pela CLI (`forge publicar`).

## Não-objetivos

- Publicar público direto. Liberar é do usuário no Studio — e só funciona
  depois que o projeto do Google Cloud passa pela auditoria da API do YouTube:
  antes dela, todo vídeo enviado pela API fica travado em privado, inclusive
  para o dono, e `publishAt` não dispara. A auditoria é formulário do usuário,
  fora do código.
- Fixar comentário: a API não fixa. Segue manual, com o texto pronto no painel.
- Shorts, playlists, várias contas, editar vídeo já enviado.

## Anti-objetivos

- Subir o mesmo vídeo duas vezes (cota e canal poluído).
- Publicar run que não passou na validação final.
- Token ou código OAuth em log, URL de painel ou resposta da API.

## Abordagem

Escolhida: cliente HTTP próprio (httpx), no molde de `codex_auth.py` — PKCE,
callback em loopback, `FileLock`, gravação atômica. Sem dependência nova.
Descartadas: `google-api-python-client` + `google-auth-oauthlib` (três pacotes
pesados para quatro chamadas REST) e automação do YouTube Studio pelo navegador
(frágil e fora dos termos).

Execução no painel: a API abre uma thread por run (I/O de rede, não GPU; não
passa pelo worker nem vira etapa da máquina de estados — a run já terminou).
O estado em arquivo é a verdade; se a API reiniciar no meio, o próximo clique
retoma a sessão de upload.

## Decisões

- Credenciais: `FORGE_YOUTUBE_CLIENT_SECRETS` (default
  `~/.forge/youtube/client_secret.json`, o JSON baixado do Google Cloud) e
  `FORGE_YOUTUBE_CANAIS_DIR` (default `~/.forge/youtube/canais/`, ver adendo).
- Escopos: `youtube.upload` e `youtube.force-ssl` (legenda exige o segundo).
  `access_type=offline` + `prompt=consent` para vir refresh token.
- Metadados: `categoryId` de `FORGE_YOUTUBE_CATEGORIA` (default `27`,
  Educação); `defaultLanguage`/`defaultAudioLanguage` `pt-BR`;
  `selfDeclaredMadeForKids=false`; `containsSyntheticMedia` de
  `FORGE_YOUTUBE_SINTETICO` (default verdadeiro: voz e imagens são geradas).
- Agendamento: `publishAt` precisa estar no futuro (mínimo 15 min); vai em UTC.
- Upload retomável em trechos de 8 MiB, estado regravado a cada trecho
  (progresso visível no painel). Erro de rede ou 5xx: consulta a sessão
  (`Content-Range: bytes */total`) e continua.
- Thumbnail e legenda falhando não desfazem o upload: viram avisos
  (`thumbnail_recusada` — canal não verificado por telefone; `legenda_recusada`).
- Cota esgotada (`quotaExceeded`), sessão Google inválida e run não aprovada
  são erros tipados com mensagem de ação.

## Contratos

- `GET /api/runs/{id}/publication` → estado (ou `{"etapa": null}`).
- `POST /api/runs/{id}/publication` `{titulo, publicar_em?}` → 202 com o
  estado; 409 com `error.code` em `publication_running`, `already_published`,
  `publication_refused` (run não aprovada, título ou agenda inválidos) ou
  `youtube_auth_missing`.
- `forge publicar <run_dir> [--titulo N] [--agendar ISO8601]`.

## Deixado ao implementador

Nomes internos, formato exato das mensagens, layout do painel dentro da aba
Publicação existente.

## Adendo: login e canal pelo painel (aprovado em 2026-11-20)

Sem login, a aba Publicação conecta a conta pelo navegador e escolhe o canal.

- O canal é escolhido na tela do Google ("Escolha uma conta ou canal"); o
  token vale para aquele canal. Um token por canal em
  `FORGE_YOUTUBE_CANAIS_DIR` (default `~/.forge/youtube/canais/`), com
  `canais.json` guardando nome, foto e o padrão. `channels.list?mine=true`
  identifica o canal depois do login.
- O login parte da API: ela abre o callback em loopback numa thread (mesmo
  `GoogleCredentials.login`) e devolve a URL; o painel abre a URL e consulta
  `GET /api/youtube` até o canal aparecer. Painel e API estão na mesma máquina.
- Opção (a): sem cliente OAuth configurado, o painel aceita o
  `client_secret.json` por upload; a API valida (cliente desktop, `client_id`)
  antes de gravar em `FORGE_YOUTUBE_CLIENT_SECRETS`.
- A publicação recebe `canal_id` (vazio = padrão) e grava `canal_id` e
  `canal_titulo` no estado; a retomada usa o canal gravado, porque a sessão de
  upload pertence ao token daquele canal.
- `FORGE_YOUTUBE_TOKEN_FILE` sai: o token único virou um por canal.
- Desconectar apaga o token local do canal (não revoga no Google).

Contrato:

- `GET /api/youtube` → `{cliente_configurado, canais: [{id, titulo,
  thumbnail, padrao}], login: {status: inativo|aguardando|concluido|falhou,
  url, erro, canal_id}}`.
- `POST /api/youtube/client {conteudo}` → visão; 422 `youtube_client_invalid`.
- `POST /api/youtube/login` → 202 visão com `login.url`; 409
  `youtube_client_missing`.
- `POST /api/youtube/channels/{id}/default` e `.../disconnect` → visão; 404.
