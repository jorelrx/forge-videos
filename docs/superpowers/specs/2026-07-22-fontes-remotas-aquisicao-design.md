# Fontes remotas de aquisição — design

**Data:** 2026-07-22
**Escopo:** camada de aquisição de textos de fontes remotas (Project Gutenberg,
Internet Archive, Wikisource, Stanford Encyclopedia of Philosophy) para a base de
conhecimento. Busca por tema, sem filtro de idioma. Alimenta o pipeline de
ingestão existente sem alterá-lo.

## Objetivo

Dado um tema/autor, buscar em cada fonte, pegar os top-N candidatos, baixar o
texto completo de cada um e produzir `Documento(tipo="livro")` — que segue pelo
pipeline `enriquecer` → `persistir` já existente (`knowledge/ingest.py`).

Este ciclo cobre **apenas a aquisição**. Embeddings, persistência e retrieval já
existem e não são tocados aqui.

## Decisões travadas (brainstorming)

- **Modo de descoberta:** busca por tema (não por identificador).
- **Idioma:** aceita qualquer idioma; idioma vira metadado, não filtro.
- **Escopo:** interface comum + as 4 fontes no mesmo ciclo.
- **Abordagem:** protocolo `FonteRemota` comum, duas fases `buscar`→`baixar`,
  HTTP+cache compartilhado, parsers puros separados da rede.

## Arquitetura

Novo pacote `src/forge/knowledge/sources/remote/`:

```
sources/remote/
  __init__.py        # registry {"gutenberg": Gutenberg, ...}; resolve --source
  base.py            # FonteRemota protocol, Referencia, orquestrador buscar_e_baixar
  http.py            # cliente HTTP compartilhado + cache raw em disco
  gutenberg.py
  internet_archive.py
  wikisource.py
  sep.py
```

### Contrato

```python
class Referencia(BaseModel):
    fonte: str            # "gutenberg"
    id_externo: str       # id na fonte (gutenberg id, IA identifier, título wiki, slug SEP)
    titulo: str
    autor: str | None = None
    url: str              # de onde baixar o texto completo
    idioma: str | None = None

class FonteRemota(Protocol):
    nome: str
    def buscar(self, query: str, *, limite: int, http) -> list[Referencia]: ...
    def baixar(self, ref: Referencia, *, http) -> Documento: ...
```

- `http` é injetado → testes passam um fake, sem rede.
- Parse fica em funções livres puras (`_parse_gutendex(json) -> list[Referencia]`),
  testadas por fixture salva. A rede vive só em `buscar`/`baixar`.
- Duas fases (`buscar` retorna candidatos leves; `baixar` puxa texto completo)
  permitem capar N e deduplicar **antes** do download caro.

### Orquestrador (`base.py`)

```python
def buscar_e_baixar(fontes, query, *, limite, http) -> list[Documento]:
    # para cada fonte: buscar (best-effort — fonte que falha não mata as outras)
    # dedupe das referências por id_deterministico(fonte, id_externo)
    # baixar cada ref (best-effort — ref que falha loga e pula)
```

`id_deterministico("gutenberg", id_externo)` garante ingestão idempotente:
reingerir sobrescreve os mesmos pontos, não duplica.

## As 4 fontes

### Gutenberg (Gutendex, sem chave)

- **buscar:** `GET https://gutendex.com/books?search=<query>` → JSON `results[]`
  (`id`, `title`, `authors[].name`, `languages[]`, `formats{mime:url}`).
- **baixar:** escolhe o format `text/plain; charset=utf-8` (fallback `text/plain`),
  baixa. Remove o boilerplate do Project Gutenberg (corta entre os marcadores
  `*** START OF … ***` e `*** END OF … ***`).
- idioma: `languages[0]`. autoridade `1.0` (fonte primária).

### Internet Archive

- **buscar:** `GET https://archive.org/advancedsearch.php?q=<query>&fl[]=identifier&fl[]=title&fl[]=creator&fl[]=language&rows=<N>&output=json`
  → `response.docs[]`.
- **baixar:** `GET https://archive.org/metadata/<identifier>` → acha um arquivo
  `*_djvu.txt` (ou `*.txt`), baixa de `https://archive.org/download/<id>/<file>`.
  Item só com PDF/DjVu sem camada txt → pula e loga.
- autoridade `1.0`.

### Wikisource (MediaWiki, multi-subdomínio)

- config `wikisource_langs = ["pt", "en"]` — a busca varre esses subdomínios;
  "qualquer idioma" = adicionar langs aqui.
- **buscar:** por lang, `GET https://<lang>.wikisource.org/w/api.php?action=query&list=search&srsearch=<query>&format=json`
  → `query.search[].title`.
- **baixar:** `action=query&prop=extracts&explaintext=1&titles=<title>` → plaintext.
- autoridade `1.0`.

### SEP — Stanford Encyclopedia of Philosophy (scraping, sem API)

- **buscar:** `GET https://plato.stanford.edu/search/searcher.py?query=<query>`
  → parse do HTML, extrai links `/entries/<slug>/` (BeautifulSoup).
- **baixar:** `GET https://plato.stanford.edu/entries/<slug>/` → extrai
  `div#article-content` (navegação/bibliografia/TOC fora).
- idioma `"en"`. autoridade `0.9` (enciclopédia = fonte terciária, ainda alta).

Cada resposta é parseada por uma função pura testada com fixture salva.

## Modelo de domínio

`Proveniencia` (`knowledge/domain/models.py`) ganha:

- campo `idioma: str | None = None`
- classmethod `de_fonte_remota(fonte, autor, obra, url, idioma, autoridade)`
  → `tipo="livro"` (SEP incluso, autoridade alta).

Nenhuma outra mudança no domínio.

## HTTP e cache (`http.py`)

- `httpx.Client` — User-Agent `forge-videos/knowledge (+github)`, timeout `30s`,
  retry/backoff 3x em 429/5xx, sleep educado entre requests
  (`remote_rate_delay`, default `1.0s`).
- `get_json(url)`, `get_text(url)`.
- **Cache raw em disco:** `output/knowledge_cache/<fonte>/<id_externo>.<ext>`.
  Se o corpo já existe → lê do disco e pula a rede (reingest offline + poupa o
  servidor). Só o corpo baixado é cacheado, não os resultados de busca.

## Config (`KnowledgeSettings`, novos campos)

```
remote_top_n: int = 3
remote_rate_delay: float = 1.0
remote_timeout: float = 30.0
wikisource_langs: list[str] = ["pt", "en"]
cache_dir: str = "output/knowledge_cache"
```

## CLI (`forge ingest`, `--path` intacto)

Novos flags:

```
forge ingest --source gutenberg --query "estoicismo" --limite 3
forge ingest --source all --query "estoicismo"
```

- `--source {gutenberg,internet_archive,wikisource,sep,all}`
- `--query <tema>` (exigido junto com `--source`)
- `--limite <N>` (default `remote_top_n`)

Nova função `ingerir_busca_remota(fontes, query, settings)` em `ingest.py`:
resolve as fontes pelo registry, chama `buscar_e_baixar`, passa os docs para
`ingerir_documentos` existente. Reusa `_montar` para model/embed_fn/stores.

## Dependências

Extra `knowledge`: adicionar `httpx`. `beautifulsoup4` já é usado (`sources/book.py`,
caminho epub) — garantir que está declarado no extra `knowledge` também.

## Erros — best-effort em toda parte

Mesmo ethos da camada de conhecimento (falha de store nunca quebra geração):

- fonte que falha na busca não derruba as outras (`--source all` continua);
- referência que falha no download loga e é pulada;
- cache miss nunca é fatal;
- item sem texto extraível (só PDF/DjVu) é pulado com log, não erro.

## Testes

- **parsers puros:** fixture JSON/HTML salva por fonte → asserta `list[Referencia]`
  e texto limpo. Sem rede.
- **`buscar_e_baixar`:** fake http + fakes de fonte → testa dedupe e best-effort
  (fonte/ref que falha não derruba o lote).
- **casos puros:** strip do boilerplate Gutenberg; extração do artigo SEP.
- **integração real (rede):** gated em credenciais/flag como `tests/test_integration.py`
  já é hoje.

## Fora de escopo

- Embeddings, persistência, retrieval (já existem).
- Descoberta por identificador/URL direto.
- Filtro/normalização de idioma além de gravar o metadado.
- Otimização do retriever de 8 sinais (plano separado).
