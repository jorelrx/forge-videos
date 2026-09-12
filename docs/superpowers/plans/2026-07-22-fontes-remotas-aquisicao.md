# Fontes Remotas de Aquisição — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Always using caveman. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar uma camada de aquisição que, dado um tema, busca em Project Gutenberg, Internet Archive, Wikisource e SEP, baixa o texto completo dos top-N candidatos e produz `Documento(tipo="livro")` para o pipeline de ingestão existente.

**Architecture:** Novo pacote `knowledge/sources/remote/` com protocolo `FonteRemota` comum. Cada fonte faz duas fases — `buscar(query)` devolve `Referencia` leve, `baixar(ref)` puxa o texto completo. Um cliente HTTP compartilhado (`http.py`) confina a rede e cacheia corpos em disco; os parsers de cada fonte são funções puras testáveis com fixture. Um orquestrador (`buscar_e_baixar`) deduplica e é best-effort. A saída alimenta `ingerir_documentos` sem alterá-lo.

**Tech Stack:** Python 3.12, httpx (novo), beautifulsoup4, pydantic v2, structlog, pytest. APIs: Gutendex, Internet Archive advancedsearch/metadata, MediaWiki, scraping SEP.

## Global Constraints

- Logging via `structlog`: `get_logger(__name__)`, campos key=value, **nunca f-strings** em chamadas de log.
- Nomes de domínio/estado e mensagens de log em português; identificadores misturam PT/EN conforme o arquivo vizinho.
- Testes mockam rede e não tocam servidores reais; testes de integração real ficam gated como `tests/test_integration.py`.
- Rede vive **só** em `http.py` e nos métodos `buscar`/`baixar`; parsers são funções puras.
- Best-effort: fonte que falha não derruba as outras; referência que falha loga e é pulada.
- Deps novas no extra `knowledge`: `httpx>=0.27`, `beautifulsoup4>=4.12`.
- **Commits:** o usuário dispensou commits neste ciclo. Os passos "Commit" abaixo são opcionais — pule-os.

---

## File Structure

Criar:
- `src/forge/knowledge/sources/remote/__init__.py` — registry + `construir_fontes`
- `src/forge/knowledge/sources/remote/base.py` — `Referencia`, `FonteRemota`, `buscar_e_baixar`, dedupe
- `src/forge/knowledge/sources/remote/http.py` — cliente HTTP + cache raw
- `src/forge/knowledge/sources/remote/gutenberg.py`
- `src/forge/knowledge/sources/remote/internet_archive.py`
- `src/forge/knowledge/sources/remote/wikisource.py`
- `src/forge/knowledge/sources/remote/sep.py`
- `tests/knowledge/__init__.py`, `tests/knowledge/sources/__init__.py`, `tests/knowledge/sources/remote/__init__.py`
- `tests/knowledge/sources/remote/test_http.py`
- `tests/knowledge/sources/remote/test_base.py`
- `tests/knowledge/sources/remote/test_gutenberg.py`
- `tests/knowledge/sources/remote/test_internet_archive.py`
- `tests/knowledge/sources/remote/test_wikisource.py`
- `tests/knowledge/sources/remote/test_sep.py`
- `tests/knowledge/test_proveniencia.py`

Modificar:
- `src/forge/knowledge/domain/models.py` — campo `idioma` + `de_fonte_remota`
- `src/forge/infrastructure/config.py` — novos campos em `KnowledgeSettings`
- `src/forge/knowledge/ingest.py` — `ingerir_busca_remota`
- `src/forge/cli.py` — flags `--source`/`--query`/`--limite`
- `pyproject.toml` — extra `knowledge`

---

## Task 1: Config, deps e modelo de domínio

**Files:**
- Modify: `pyproject.toml` (extra `knowledge`)
- Modify: `src/forge/infrastructure/config.py` (`KnowledgeSettings`)
- Modify: `src/forge/knowledge/domain/models.py` (`Proveniencia`)
- Create: `tests/knowledge/__init__.py` (vazio)
- Test: `tests/knowledge/test_proveniencia.py`
- Test: adicionar caso em `tests/test_config.py`

**Interfaces:**
- Produces: `Proveniencia.idioma: str | None`; `Proveniencia.de_fonte_remota(*, fonte, autor=None, obra=None, url=None, idioma=None, autoridade) -> Proveniencia`; campos de `KnowledgeSettings`: `remote_top_n:int=3`, `remote_rate_delay:float=1.0`, `remote_timeout:float=30.0`, `wikisource_langs:list[str]=["pt","en"]`, `cache_dir:str="output/knowledge_cache"`.

- [ ] **Step 1: Adicionar deps ao extra `knowledge` no `pyproject.toml`**

Localizar o bloco `knowledge = [ ... ]` e acrescentar duas linhas:

```toml
knowledge = [
    "qdrant-client>=1.9",
    "neo4j>=5.19",
    "psycopg[binary]>=3.1",
    "sentence-transformers>=3.0",
    "httpx>=0.27",
    "beautifulsoup4>=4.12",
]
```

Rodar: `uv sync --extra knowledge`
Esperado: instala httpx/bs4 sem erro.

- [ ] **Step 2: Escrever teste falho do modelo**

Criar `tests/knowledge/__init__.py` vazio e `tests/knowledge/test_proveniencia.py`:

```python
from forge.knowledge.domain.models import Proveniencia


def test_de_fonte_remota_preenche_idioma_e_tipo_livro():
    p = Proveniencia.de_fonte_remota(
        fonte="gutenberg", autor="Marco Aurélio", obra="Meditações",
        url="https://x/1", idioma="en", autoridade=1.0,
    )
    assert p.tipo == "livro"
    assert p.fonte == "gutenberg"
    assert p.idioma == "en"
    assert p.autoridade == 1.0


def test_idioma_default_none_em_de_livro():
    p = Proveniencia.de_livro(fonte="a.txt")
    assert p.idioma is None
```

- [ ] **Step 3: Rodar teste, verificar que falha**

Run: `uv run pytest tests/knowledge/test_proveniencia.py -v`
Esperado: FAIL (`AttributeError`/`TypeError` — `de_fonte_remota` e `idioma` não existem).

- [ ] **Step 4: Implementar mudança no modelo**

Em `src/forge/knowledge/domain/models.py`, na classe `Proveniencia` adicionar o campo (depois de `data`):

```python
    idioma: str | None = None
```

E adicionar a classmethod após `de_web`:

```python
    @classmethod
    def de_fonte_remota(
        cls,
        *,
        fonte: str,
        autor: str | None = None,
        obra: str | None = None,
        url: str | None = None,
        idioma: str | None = None,
        autoridade: float,
    ) -> Proveniencia:
        return cls(
            tipo="livro", fonte=fonte, autor=autor, obra=obra,
            url=url, idioma=idioma, autoridade=autoridade,
        )
```

- [ ] **Step 5: Rodar teste, verificar que passa**

Run: `uv run pytest tests/knowledge/test_proveniencia.py -v`
Esperado: PASS (2 testes).

- [ ] **Step 6: Escrever teste falho da config**

Adicionar ao final de `tests/test_config.py`:

```python
def test_knowledge_tem_defaults_de_fontes_remotas():
    from forge.infrastructure.config import KnowledgeSettings

    k = KnowledgeSettings()
    assert k.remote_top_n == 3
    assert k.remote_rate_delay == 1.0
    assert k.remote_timeout == 30.0
    assert k.wikisource_langs == ["pt", "en"]
    assert k.cache_dir == "output/knowledge_cache"
```

Run: `uv run pytest tests/test_config.py -k fontes_remotas -v`
Esperado: FAIL (`AttributeError`).

- [ ] **Step 7: Adicionar campos à `KnowledgeSettings`**

Em `src/forge/infrastructure/config.py`, dentro de `KnowledgeSettings`, junto aos demais campos (ex.: depois de `chunk_overlap`):

```python
    # Aquisição de fontes remotas
    remote_top_n: int = 3
    remote_rate_delay: float = 1.0
    remote_timeout: float = 30.0
    wikisource_langs: list[str] = ["pt", "en"]
    cache_dir: str = "output/knowledge_cache"
```

- [ ] **Step 8: Rodar testes da task**

Run: `uv run pytest tests/knowledge/test_proveniencia.py tests/test_config.py -v`
Esperado: PASS.

- [ ] **Step 9: Commit (opcional)**

```bash
git add pyproject.toml src/forge/infrastructure/config.py src/forge/knowledge/domain/models.py tests/knowledge/test_proveniencia.py tests/test_config.py
git commit -m "feat(knowledge): idioma na proveniência + config de fontes remotas"
```

---

## Task 2: Cliente HTTP compartilhado + cache

**Files:**
- Create: `src/forge/knowledge/sources/remote/__init__.py` (vazio por enquanto)
- Create: `src/forge/knowledge/sources/remote/http.py`
- Create: `tests/knowledge/sources/__init__.py`, `tests/knowledge/sources/remote/__init__.py` (vazios)
- Test: `tests/knowledge/sources/remote/test_http.py`

**Interfaces:**
- Produces: `Http(*, cache_dir, rate_delay=1.0, timeout=30.0, tentativas=3, cliente=None)` com métodos `get_json(url, *, params=None) -> dict`, `get_text(url, *, params=None) -> str`, `get_text_cacheado(url, *, fonte, id_externo, ext="txt") -> str`.
- Consumes: nada (base da pilha).

- [ ] **Step 1: Escrever teste falho do cache**

Criar os `__init__.py` vazios e `tests/knowledge/sources/remote/test_http.py`:

```python
import httpx

from forge.knowledge.sources.remote.http import Http


def _http_fake(handler, tmp_path):
    cliente = httpx.Client(transport=httpx.MockTransport(handler))
    return Http(cache_dir=tmp_path, rate_delay=0, cliente=cliente)


def test_cache_grava_e_relê_do_disco(tmp_path):
    chamadas = []

    def handler(request):
        chamadas.append(str(request.url))
        return httpx.Response(200, text="corpo do livro")

    http = _http_fake(handler, tmp_path)
    a = http.get_text_cacheado("https://x/1", fonte="gutenberg", id_externo="1")
    b = http.get_text_cacheado("https://x/1", fonte="gutenberg", id_externo="1")

    assert a == b == "corpo do livro"
    assert len(chamadas) == 1  # segunda leitura veio do disco


def test_get_json_desserializa(tmp_path):
    def handler(request):
        return httpx.Response(200, json={"ok": 1})

    http = _http_fake(handler, tmp_path)
    assert http.get_json("https://x/j") == {"ok": 1}


def test_retry_em_503_depois_sucesso(tmp_path):
    estado = {"n": 0}

    def handler(request):
        estado["n"] += 1
        if estado["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, text="ok")

    http = _http_fake(handler, tmp_path)
    assert http.get_text("https://x/r") == "ok"
    assert estado["n"] == 2
```

- [ ] **Step 2: Rodar teste, verificar que falha**

Run: `uv run pytest tests/knowledge/sources/remote/test_http.py -v`
Esperado: FAIL (`ModuleNotFoundError: http`).

- [ ] **Step 3: Implementar `http.py`**

Criar `src/forge/knowledge/sources/remote/__init__.py` vazio e `src/forge/knowledge/sources/remote/http.py`:

```python
"""Cliente HTTP compartilhado das fontes remotas + cache raw em disco.

A rede fica confinada aqui; os parsers de cada fonte são puros. O cache grava o
corpo baixado em disco para reingest offline e para poupar os servidores das
fontes. `cliente` é injetável para os testes rodarem com httpx.MockTransport,
sem rede.
"""
import re
import time
from pathlib import Path

import httpx

from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)

_UA = "forge-videos/knowledge (+https://github.com)"
_RETRIABLE = {429, 500, 502, 503, 504}


def _sanitizar(nome: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", nome)[:180]


class Http:
    def __init__(
        self,
        *,
        cache_dir,
        rate_delay: float = 1.0,
        timeout: float = 30.0,
        tentativas: int = 3,
        cliente: httpx.Client | None = None,
    ):
        self._cache_dir = Path(cache_dir)
        self._rate_delay = rate_delay
        self._tentativas = tentativas
        self._cliente = cliente or httpx.Client(
            headers={"User-Agent": _UA}, timeout=timeout, follow_redirects=True
        )

    def get_json(self, url: str, *, params: dict | None = None) -> dict:
        return self._request(url, params=params).json()

    def get_text(self, url: str, *, params: dict | None = None) -> str:
        return self._request(url, params=params).text

    def get_text_cacheado(self, url: str, *, fonte: str, id_externo: str, ext: str = "txt") -> str:
        caminho = self._cache_dir / fonte / f"{_sanitizar(id_externo)}.{ext}"
        if caminho.exists():
            logger.debug("Cache hit", fonte=fonte, id=id_externo)
            return caminho.read_text(encoding="utf-8")
        texto = self.get_text(url)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(texto, encoding="utf-8")
        logger.debug("Cache gravado", fonte=fonte, id=id_externo, chars=len(texto))
        return texto

    def _request(self, url: str, *, params: dict | None = None) -> httpx.Response:
        ultimo: Exception | None = None
        for tentativa in range(self._tentativas):
            try:
                resp = self._cliente.get(url, params=params)
                if resp.status_code in _RETRIABLE:
                    raise httpx.HTTPStatusError(
                        "status retriável", request=resp.request, response=resp
                    )
                resp.raise_for_status()
                if self._rate_delay:
                    time.sleep(self._rate_delay)
                return resp
            except httpx.HTTPError as e:
                ultimo = e
                logger.debug("Request falhou, retry", url=url, tentativa=tentativa)
                if self._rate_delay:
                    time.sleep(self._rate_delay * (tentativa + 1))
        assert ultimo is not None
        raise ultimo
```

- [ ] **Step 4: Rodar teste, verificar que passa**

Run: `uv run pytest tests/knowledge/sources/remote/test_http.py -v`
Esperado: PASS (3 testes).

- [ ] **Step 5: Commit (opcional)**

```bash
git add src/forge/knowledge/sources/remote/ tests/knowledge/sources/
git commit -m "feat(knowledge): cliente HTTP compartilhado com cache raw"
```

---

## Task 3: Contrato e orquestrador (`base.py`)

**Files:**
- Create: `src/forge/knowledge/sources/remote/base.py`
- Test: `tests/knowledge/sources/remote/test_base.py`

**Interfaces:**
- Consumes: `Http` (Task 2); `Documento`, `id_deterministico` (`domain/models.py`).
- Produces: `Referencia(BaseModel)` com campos `fonte,id_externo,titulo,autor=None,url,idioma=None` e `@property chave -> str`; `FonteRemota` (Protocol) com `nome:str`, `buscar(query,*,limite,http)->list[Referencia]`, `baixar(ref,*,http)->Documento`; `buscar_e_baixar(fontes, query, *, limite, http) -> list[Documento]`.

- [ ] **Step 1: Escrever teste falho do orquestrador**

Criar `tests/knowledge/sources/remote/test_base.py`:

```python
from forge.knowledge.domain.models import Documento, Proveniencia
from forge.knowledge.sources.remote.base import Referencia, buscar_e_baixar


def _doc(ref):
    return Documento(
        id=ref.chave, titulo=ref.titulo, texto="t",
        proveniencia=Proveniencia.de_fonte_remota(fonte=ref.fonte, autoridade=1.0),
    )


class FonteOk:
    nome = "ok"

    def buscar(self, query, *, limite, http):
        return [
            Referencia(fonte="ok", id_externo="1", titulo="A", url="u1"),
            Referencia(fonte="ok", id_externo="1", titulo="A", url="u1"),  # duplicata
            Referencia(fonte="ok", id_externo="2", titulo="B", url="u2"),
        ]

    def baixar(self, ref, *, http):
        return _doc(ref)


class FonteQuebraBusca:
    nome = "quebra"

    def buscar(self, query, *, limite, http):
        raise RuntimeError("api fora")

    def baixar(self, ref, *, http):
        return _doc(ref)


class FonteQuebraBaixar:
    nome = "baixar_ruim"

    def buscar(self, query, *, limite, http):
        return [Referencia(fonte="baixar_ruim", id_externo="9", titulo="Z", url="u9")]

    def baixar(self, ref, *, http):
        raise RuntimeError("download 404")


def test_dedupe_por_chave():
    docs = buscar_e_baixar([FonteOk()], "tema", limite=10, http=None)
    assert len(docs) == 2  # duplicata de id_externo=1 removida


def test_fonte_que_quebra_na_busca_nao_derruba_lote():
    docs = buscar_e_baixar([FonteQuebraBusca(), FonteOk()], "tema", limite=10, http=None)
    assert len(docs) == 2  # só as refs da FonteOk


def test_ref_que_quebra_no_download_e_pulada():
    docs = buscar_e_baixar([FonteQuebraBaixar(), FonteOk()], "tema", limite=10, http=None)
    assert len(docs) == 2  # a ref da FonteQuebraBaixar pulada, FonteOk mantém 2
```

- [ ] **Step 2: Rodar teste, verificar que falha**

Run: `uv run pytest tests/knowledge/sources/remote/test_base.py -v`
Esperado: FAIL (`ModuleNotFoundError: base`).

- [ ] **Step 3: Implementar `base.py`**

Criar `src/forge/knowledge/sources/remote/base.py`:

```python
"""Contrato das fontes remotas + orquestrador buscar->baixar.

`buscar` devolve candidatos leves (Referencia) para capar N e deduplicar antes
do download caro. Tudo best-effort: fonte ou referência que falha loga e é
pulada, nunca derruba o lote (mesmo ethos da camada de conhecimento).
"""
from typing import Protocol

from pydantic import BaseModel

from forge.infrastructure.logging import get_logger
from forge.knowledge.domain.models import Documento, id_deterministico

logger = get_logger(__name__)


class Referencia(BaseModel):
    fonte: str
    id_externo: str
    titulo: str
    autor: str | None = None
    url: str
    idioma: str | None = None

    @property
    def chave(self) -> str:
        return id_deterministico(self.fonte, self.id_externo)


class FonteRemota(Protocol):
    nome: str

    def buscar(self, query: str, *, limite: int, http) -> list[Referencia]: ...

    def baixar(self, ref: Referencia, *, http) -> Documento: ...


def _dedupe(refs: list[Referencia]) -> list[Referencia]:
    visto: set[str] = set()
    saida: list[Referencia] = []
    for r in refs:
        if r.chave in visto:
            continue
        visto.add(r.chave)
        saida.append(r)
    return saida


def buscar_e_baixar(fontes, query: str, *, limite: int, http) -> list[Documento]:
    refs: list[Referencia] = []
    for fonte in fontes:
        try:
            achados = fonte.buscar(query, limite=limite, http=http)
            refs.extend(achados)
            logger.info("Fonte buscada", fonte=fonte.nome, achados=len(achados))
        except Exception as e:
            logger.warning("Fonte falhou na busca", fonte=fonte.nome, error=str(e))

    refs = _dedupe(refs)
    por_fonte = {f.nome: f for f in fontes}
    docs: list[Documento] = []
    for ref in refs:
        fonte = por_fonte.get(ref.fonte)
        if fonte is None:
            continue
        try:
            docs.append(fonte.baixar(ref, http=http))
        except Exception as e:
            logger.warning("Download falhou", fonte=ref.fonte, id=ref.id_externo, error=str(e))
    logger.info("Aquisição concluída", refs=len(refs), docs=len(docs))
    return docs
```

- [ ] **Step 4: Rodar teste, verificar que passa**

Run: `uv run pytest tests/knowledge/sources/remote/test_base.py -v`
Esperado: PASS (3 testes).

- [ ] **Step 5: Commit (opcional)**

```bash
git add src/forge/knowledge/sources/remote/base.py tests/knowledge/sources/remote/test_base.py
git commit -m "feat(knowledge): contrato FonteRemota + orquestrador buscar_e_baixar"
```

---

## Task 4: Fonte Gutenberg

**Files:**
- Create: `src/forge/knowledge/sources/remote/gutenberg.py`
- Test: `tests/knowledge/sources/remote/test_gutenberg.py`

**Interfaces:**
- Consumes: `Referencia` (Task 3); `Http.get_json`, `Http.get_text_cacheado` (Task 2); `Proveniencia.de_fonte_remota`, `Documento`, `id_deterministico`.
- Produces: `Gutenberg` (`nome="gutenberg"`); funções puras `parse_busca(payload) -> list[Referencia]`, `limpar_boilerplate(texto) -> str`.

- [ ] **Step 1: Escrever teste falho (parse + boilerplate)**

Criar `tests/knowledge/sources/remote/test_gutenberg.py`:

```python
from forge.knowledge.sources.remote.gutenberg import (
    Gutenberg,
    limpar_boilerplate,
    parse_busca,
)


def test_parse_busca_extrai_url_texto_plano():
    payload = {
        "results": [
            {
                "id": 1497,
                "title": "The Republic",
                "authors": [{"name": "Plato"}],
                "languages": ["en"],
                "formats": {
                    "text/html": "https://x/1497.html",
                    "text/plain; charset=utf-8": "https://x/1497.txt",
                },
            },
            {  # sem formato texto -> descartado
                "id": 2,
                "title": "Só imagem",
                "authors": [],
                "languages": ["fr"],
                "formats": {"image/jpeg": "https://x/2.jpg"},
            },
        ]
    }
    refs = parse_busca(payload)
    assert len(refs) == 1
    r = refs[0]
    assert r.fonte == "gutenberg"
    assert r.id_externo == "1497"
    assert r.autor == "Plato"
    assert r.idioma == "en"
    assert r.url == "https://x/1497.txt"


def test_limpar_boilerplate_corta_marcadores():
    bruto = (
        "cabeçalho legal\n"
        "*** START OF THE PROJECT GUTENBERG EBOOK THE REPUBLIC ***\n"
        "corpo real\n"
        "*** END OF THE PROJECT GUTENBERG EBOOK THE REPUBLIC ***\n"
        "rodapé licença"
    )
    assert limpar_boilerplate(bruto) == "corpo real"


def test_baixar_usa_cache_e_limpa():
    class FakeHttp:
        def get_text_cacheado(self, url, *, fonte, id_externo, ext="txt"):
            return "*** START OF THE PROJECT GUTENBERG EBOOK X ***\noi\n*** END OF THE PROJECT GUTENBERG EBOOK X ***"

    from forge.knowledge.sources.remote.base import Referencia

    ref = Referencia(fonte="gutenberg", id_externo="1497", titulo="The Republic", url="https://x/1497.txt", idioma="en")
    doc = Gutenberg().baixar(ref, http=FakeHttp())
    assert doc.texto == "oi"
    assert doc.proveniencia.fonte == "gutenberg"
    assert doc.proveniencia.idioma == "en"
    assert doc.titulo == "The Republic"
```

- [ ] **Step 2: Rodar teste, verificar que falha**

Run: `uv run pytest tests/knowledge/sources/remote/test_gutenberg.py -v`
Esperado: FAIL (`ModuleNotFoundError: gutenberg`).

- [ ] **Step 3: Implementar `gutenberg.py`**

Criar `src/forge/knowledge/sources/remote/gutenberg.py`:

```python
"""Project Gutenberg via API Gutendex. Parse puro; rede via http injetado."""
import re

from forge.infrastructure.logging import get_logger
from forge.knowledge.domain.models import Documento, Proveniencia, id_deterministico
from forge.knowledge.sources.remote.base import Referencia

logger = get_logger(__name__)

_API = "https://gutendex.com/books"
_AUTORIDADE = 1.0
_RE_START = re.compile(
    r"\*\*\* ?START OF TH(E|IS) PROJECT GUTENBERG[^*]*\*\*\*", re.IGNORECASE
)
_RE_END = re.compile(
    r"\*\*\* ?END OF TH(E|IS) PROJECT GUTENBERG.*", re.IGNORECASE | re.DOTALL
)


def _url_texto_plano(formats: dict) -> str | None:
    preferidos = (
        "text/plain; charset=utf-8",
        "text/plain; charset=us-ascii",
        "text/plain",
    )
    for mime in preferidos:
        url = formats.get(mime)
        if url and not url.endswith(".zip"):
            return url
    for mime, url in formats.items():
        if mime.startswith("text/plain") and not url.endswith(".zip"):
            return url
    return None


def parse_busca(payload: dict) -> list[Referencia]:
    refs: list[Referencia] = []
    for item in payload.get("results", []):
        url = _url_texto_plano(item.get("formats", {}))
        if not url:
            continue
        autores = item.get("authors") or []
        idiomas = item.get("languages") or []
        refs.append(
            Referencia(
                fonte="gutenberg",
                id_externo=str(item["id"]),
                titulo=item.get("title", "sem título"),
                autor=autores[0]["name"] if autores else None,
                url=url,
                idioma=idiomas[0] if idiomas else None,
            )
        )
    return refs


def limpar_boilerplate(texto: str) -> str:
    m = _RE_START.search(texto)
    if m:
        texto = texto[m.end():]
    texto = _RE_END.sub("", texto)
    return texto.strip()


class Gutenberg:
    nome = "gutenberg"

    def buscar(self, query: str, *, limite: int, http) -> list[Referencia]:
        payload = http.get_json(_API, params={"search": query})
        return parse_busca(payload)[:limite]

    def baixar(self, ref: Referencia, *, http) -> Documento:
        bruto = http.get_text_cacheado(ref.url, fonte="gutenberg", id_externo=ref.id_externo)
        texto = limpar_boilerplate(bruto)
        prov = Proveniencia.de_fonte_remota(
            fonte="gutenberg", autor=ref.autor, obra=ref.titulo,
            url=ref.url, idioma=ref.idioma, autoridade=_AUTORIDADE,
        )
        logger.info("Gutenberg baixado", id=ref.id_externo, chars=len(texto))
        return Documento(
            id=id_deterministico("gutenberg", ref.id_externo),
            titulo=ref.titulo, texto=texto, proveniencia=prov,
        )
```

- [ ] **Step 4: Rodar teste, verificar que passa**

Run: `uv run pytest tests/knowledge/sources/remote/test_gutenberg.py -v`
Esperado: PASS (3 testes).

- [ ] **Step 5: Commit (opcional)**

```bash
git add src/forge/knowledge/sources/remote/gutenberg.py tests/knowledge/sources/remote/test_gutenberg.py
git commit -m "feat(knowledge): fonte Gutenberg (Gutendex)"
```

---

## Task 5: Fonte Internet Archive

**Files:**
- Create: `src/forge/knowledge/sources/remote/internet_archive.py`
- Test: `tests/knowledge/sources/remote/test_internet_archive.py`

**Interfaces:**
- Consumes: `Referencia`, `Http`, domínio.
- Produces: `InternetArchive` (`nome="internet_archive"`); puras `parse_busca(payload) -> list[Referencia]`, `escolher_arquivo_texto(meta) -> str | None`.

- [ ] **Step 1: Escrever teste falho**

Criar `tests/knowledge/sources/remote/test_internet_archive.py`:

```python
import pytest

from forge.knowledge.sources.remote.base import Referencia
from forge.knowledge.sources.remote.internet_archive import (
    InternetArchive,
    escolher_arquivo_texto,
    parse_busca,
)


def test_parse_busca_normaliza_creator_e_language_lista():
    payload = {
        "response": {
            "docs": [
                {
                    "identifier": "meditations00",
                    "title": "Meditations",
                    "creator": ["Marcus Aurelius"],
                    "language": ["eng"],
                },
                {"title": "sem id"},  # sem identifier -> descartado
            ]
        }
    }
    refs = parse_busca(payload)
    assert len(refs) == 1
    r = refs[0]
    assert r.id_externo == "meditations00"
    assert r.autor == "Marcus Aurelius"
    assert r.idioma == "eng"
    assert r.url == "https://archive.org/metadata/meditations00"


def test_escolher_arquivo_prefere_djvu_txt():
    meta = {"files": [{"name": "scan.pdf"}, {"name": "book_djvu.txt"}, {"name": "notas.txt"}]}
    assert escolher_arquivo_texto(meta) == "book_djvu.txt"


def test_escolher_arquivo_none_quando_sem_texto():
    meta = {"files": [{"name": "scan.pdf"}, {"name": "img.jp2"}]}
    assert escolher_arquivo_texto(meta) is None


def test_baixar_sem_texto_levanta():
    class FakeHttp:
        def get_json(self, url, *, params=None):
            return {"files": [{"name": "scan.pdf"}]}

    ref = Referencia(fonte="internet_archive", id_externo="x", titulo="X",
                     url="https://archive.org/metadata/x")
    with pytest.raises(ValueError):
        InternetArchive().baixar(ref, http=FakeHttp())


def test_baixar_monta_documento():
    class FakeHttp:
        def get_json(self, url, *, params=None):
            return {"files": [{"name": "book_djvu.txt"}]}

        def get_text_cacheado(self, url, *, fonte, id_externo, ext="txt"):
            assert url == "https://archive.org/download/x/book_djvu.txt"
            return "conteúdo"

    ref = Referencia(fonte="internet_archive", id_externo="x", titulo="X",
                     url="https://archive.org/metadata/x", idioma="eng")
    doc = InternetArchive().baixar(ref, http=FakeHttp())
    assert doc.texto == "conteúdo"
    assert doc.proveniencia.fonte == "internet_archive"
```

- [ ] **Step 2: Rodar teste, verificar que falha**

Run: `uv run pytest tests/knowledge/sources/remote/test_internet_archive.py -v`
Esperado: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implementar `internet_archive.py`**

```python
"""Internet Archive: advancedsearch para candidatos, metadata para o arquivo
de texto (*_djvu.txt / *.txt), download do texto. Parse puro; rede via http."""
from forge.infrastructure.logging import get_logger
from forge.knowledge.domain.models import Documento, Proveniencia, id_deterministico
from forge.knowledge.sources.remote.base import Referencia

logger = get_logger(__name__)

_SEARCH = "https://archive.org/advancedsearch.php"
_META = "https://archive.org/metadata/{id}"
_DOWNLOAD = "https://archive.org/download/{id}/{file}"
_AUTORIDADE = 1.0


def _primeiro(valor):
    if isinstance(valor, list):
        return valor[0] if valor else None
    return valor


def parse_busca(payload: dict) -> list[Referencia]:
    docs = payload.get("response", {}).get("docs", [])
    refs: list[Referencia] = []
    for d in docs:
        ident = d.get("identifier")
        if not ident:
            continue
        titulo = _primeiro(d.get("title")) or ident
        refs.append(
            Referencia(
                fonte="internet_archive",
                id_externo=ident,
                titulo=titulo if isinstance(titulo, str) else ident,
                autor=_primeiro(d.get("creator")),
                url=_META.format(id=ident),
                idioma=_primeiro(d.get("language")),
            )
        )
    return refs


def escolher_arquivo_texto(meta: dict) -> str | None:
    files = meta.get("files", [])
    for f in files:
        if f.get("name", "").endswith("_djvu.txt"):
            return f["name"]
    for f in files:
        if f.get("name", "").endswith(".txt"):
            return f["name"]
    return None


class InternetArchive:
    nome = "internet_archive"

    def buscar(self, query: str, *, limite: int, http) -> list[Referencia]:
        payload = http.get_json(
            _SEARCH,
            params={
                "q": query,
                "fl[]": ["identifier", "title", "creator", "language"],
                "sort[]": "downloads desc",
                "rows": limite,
                "output": "json",
            },
        )
        return parse_busca(payload)[:limite]

    def baixar(self, ref: Referencia, *, http) -> Documento:
        meta = http.get_json(ref.url)
        arquivo = escolher_arquivo_texto(meta)
        if not arquivo:
            raise ValueError(f"sem arquivo de texto para {ref.id_externo}")
        url = _DOWNLOAD.format(id=ref.id_externo, file=arquivo)
        texto = http.get_text_cacheado(url, fonte="internet_archive", id_externo=ref.id_externo)
        prov = Proveniencia.de_fonte_remota(
            fonte="internet_archive", autor=ref.autor, obra=ref.titulo,
            url=url, idioma=ref.idioma, autoridade=_AUTORIDADE,
        )
        logger.info("Internet Archive baixado", id=ref.id_externo, chars=len(texto))
        return Documento(
            id=id_deterministico("internet_archive", ref.id_externo),
            titulo=ref.titulo, texto=texto, proveniencia=prov,
        )
```

- [ ] **Step 4: Rodar teste, verificar que passa**

Run: `uv run pytest tests/knowledge/sources/remote/test_internet_archive.py -v`
Esperado: PASS (5 testes).

- [ ] **Step 5: Commit (opcional)**

```bash
git add src/forge/knowledge/sources/remote/internet_archive.py tests/knowledge/sources/remote/test_internet_archive.py
git commit -m "feat(knowledge): fonte Internet Archive"
```

---

## Task 6: Fonte Wikisource

**Files:**
- Create: `src/forge/knowledge/sources/remote/wikisource.py`
- Test: `tests/knowledge/sources/remote/test_wikisource.py`

**Interfaces:**
- Consumes: `Referencia`, `Http`, domínio.
- Produces: `Wikisource(langs: list[str])` (`nome="wikisource"`); puras `parse_busca(payload, lang) -> list[Referencia]`, `extrair_plaintext(payload) -> str`. Convenção: `id_externo = f"{lang}:{titulo}"`.

- [ ] **Step 1: Escrever teste falho**

Criar `tests/knowledge/sources/remote/test_wikisource.py`:

```python
from forge.knowledge.sources.remote.wikisource import (
    Wikisource,
    extrair_plaintext,
    parse_busca,
)


def test_parse_busca_prefixa_lang_no_id():
    payload = {"query": {"search": [{"title": "A República"}, {"title": "Ética"}]}}
    refs = parse_busca(payload, "pt")
    assert [r.id_externo for r in refs] == ["pt:A República", "pt:Ética"]
    assert refs[0].idioma == "pt"
    assert refs[0].fonte == "wikisource"


def test_extrair_plaintext_pega_extract_da_pagina():
    payload = {"query": {"pages": {"123": {"title": "A República", "extract": "corpo"}}}}
    assert extrair_plaintext(payload) == "corpo"


def test_buscar_varre_langs_configurados():
    chamadas = []

    class FakeHttp:
        def get_json(self, url, *, params=None):
            chamadas.append(url)
            lang = "pt" if "pt." in url else "en"
            return {"query": {"search": [{"title": f"Obra {lang}"}]}}

    refs = Wikisource(["pt", "en"]).buscar("tema", limite=4, http=FakeHttp())
    assert {r.idioma for r in refs} == {"pt", "en"}
    assert any("pt.wikisource" in c for c in chamadas)
    assert any("en.wikisource" in c for c in chamadas)


def test_baixar_monta_documento():
    class FakeHttp:
        def get_json(self, url, *, params=None):
            return {"query": {"pages": {"1": {"extract": "texto da obra"}}}}

    from forge.knowledge.sources.remote.base import Referencia

    ref = Referencia(fonte="wikisource", id_externo="pt:A República",
                     titulo="A República", url="https://pt.wikisource.org/w/api.php", idioma="pt")
    doc = Wikisource(["pt"]).baixar(ref, http=FakeHttp())
    assert doc.texto == "texto da obra"
    assert doc.proveniencia.idioma == "pt"
```

- [ ] **Step 2: Rodar teste, verificar que falha**

Run: `uv run pytest tests/knowledge/sources/remote/test_wikisource.py -v`
Esperado: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implementar `wikisource.py`**

```python
"""Wikisource via MediaWiki API, multi-subdomínio (um por idioma).

id_externo = "<lang>:<título>" para o baixar saber a qual wiki voltar. `langs`
vem de settings.knowledge.wikisource_langs — adicionar idiomas amplia a varredura.
"""
from forge.infrastructure.logging import get_logger
from forge.knowledge.domain.models import Documento, Proveniencia, id_deterministico
from forge.knowledge.sources.remote.base import Referencia

logger = get_logger(__name__)

_API = "https://{lang}.wikisource.org/w/api.php"
_AUTORIDADE = 1.0


def parse_busca(payload: dict, lang: str) -> list[Referencia]:
    hits = payload.get("query", {}).get("search", [])
    refs: list[Referencia] = []
    for h in hits:
        titulo = h.get("title")
        if not titulo:
            continue
        refs.append(
            Referencia(
                fonte="wikisource",
                id_externo=f"{lang}:{titulo}",
                titulo=titulo,
                url=_API.format(lang=lang),
                idioma=lang,
            )
        )
    return refs


def extrair_plaintext(payload: dict) -> str:
    pages = payload.get("query", {}).get("pages", {})
    for page in pages.values():
        return page.get("extract", "")
    return ""


class Wikisource:
    nome = "wikisource"

    def __init__(self, langs: list[str]):
        self._langs = langs

    def buscar(self, query: str, *, limite: int, http) -> list[Referencia]:
        por_lang = max(1, limite // max(1, len(self._langs)))
        refs: list[Referencia] = []
        for lang in self._langs:
            payload = http.get_json(
                _API.format(lang=lang),
                params={
                    "action": "query", "list": "search", "srsearch": query,
                    "srlimit": por_lang, "format": "json",
                },
            )
            refs.extend(parse_busca(payload, lang)[:por_lang])
        return refs[:limite]

    def baixar(self, ref: Referencia, *, http) -> Documento:
        lang, titulo = ref.id_externo.split(":", 1)
        payload = http.get_json(
            _API.format(lang=lang),
            params={
                "action": "query", "prop": "extracts", "explaintext": "1",
                "titles": titulo, "format": "json",
            },
        )
        texto = extrair_plaintext(payload)
        prov = Proveniencia.de_fonte_remota(
            fonte="wikisource", obra=ref.titulo, url=ref.url,
            idioma=lang, autoridade=_AUTORIDADE,
        )
        logger.info("Wikisource baixado", id=ref.id_externo, chars=len(texto))
        return Documento(
            id=id_deterministico("wikisource", ref.id_externo),
            titulo=ref.titulo, texto=texto, proveniencia=prov,
        )
```

- [ ] **Step 4: Rodar teste, verificar que passa**

Run: `uv run pytest tests/knowledge/sources/remote/test_wikisource.py -v`
Esperado: PASS (4 testes).

- [ ] **Step 5: Commit (opcional)**

```bash
git add src/forge/knowledge/sources/remote/wikisource.py tests/knowledge/sources/remote/test_wikisource.py
git commit -m "feat(knowledge): fonte Wikisource (MediaWiki multi-lang)"
```

---

## Task 7: Fonte SEP (scraping)

**Files:**
- Create: `src/forge/knowledge/sources/remote/sep.py`
- Test: `tests/knowledge/sources/remote/test_sep.py`

**Interfaces:**
- Consumes: `Referencia`, `Http`, domínio, `bs4` (extra `knowledge`).
- Produces: `SEP` (`nome="sep"`); puras `parse_busca(html) -> list[Referencia]`, `extrair_artigo(html) -> str`. `id_externo = slug` da entrada; idioma fixo `"en"`; autoridade `0.9`.

- [ ] **Step 1: Escrever teste falho**

Criar `tests/knowledge/sources/remote/test_sep.py`:

```python
from forge.knowledge.sources.remote.base import Referencia
from forge.knowledge.sources.remote.sep import SEP, extrair_artigo, parse_busca


def test_parse_busca_extrai_slugs_unicos():
    html = """
    <html><body>
      <a href="/entries/stoicism/">Stoicism</a>
      <a href="/entries/stoicism/#Eth">Stoicism ancora</a>
      <a href="/entries/plato-ethics/">Plato's Ethics</a>
      <a href="https://outrolugar.com/x/">externo</a>
    </body></html>
    """
    refs = parse_busca(html)
    assert [r.id_externo for r in refs] == ["stoicism", "plato-ethics"]
    assert refs[0].url == "https://plato.stanford.edu/entries/stoicism/"
    assert refs[0].idioma == "en"


def test_extrair_artigo_pega_conteudo():
    html = """
    <html><body>
      <div id="article-content"><p>Primeira frase.</p><p>Segunda.</p></div>
      <div id="bibliography">refs...</div>
    </body></html>
    """
    texto = extrair_artigo(html)
    assert "Primeira frase." in texto
    assert "Segunda." in texto
    assert "refs..." not in texto


def test_baixar_monta_documento_autoridade_09():
    class FakeHttp:
        def get_text_cacheado(self, url, *, fonte, id_externo, ext="txt"):
            return '<div id="article-content"><p>corpo</p></div>'

    ref = Referencia(fonte="sep", id_externo="stoicism", titulo="Stoicism",
                     url="https://plato.stanford.edu/entries/stoicism/", idioma="en")
    doc = SEP().baixar(ref, http=FakeHttp())
    assert "corpo" in doc.texto
    assert doc.proveniencia.autoridade == 0.9
    assert doc.proveniencia.fonte == "sep"
```

- [ ] **Step 2: Rodar teste, verificar que falha**

Run: `uv run pytest tests/knowledge/sources/remote/test_sep.py -v`
Esperado: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implementar `sep.py`**

```python
"""Stanford Encyclopedia of Philosophy: sem API. Busca via endpoint interno de
search (HTML), artigo via scraping da página da entrada. bs4 confinado aqui."""
import re

from bs4 import BeautifulSoup

from forge.infrastructure.logging import get_logger
from forge.knowledge.domain.models import Documento, Proveniencia, id_deterministico
from forge.knowledge.sources.remote.base import Referencia

logger = get_logger(__name__)

_SEARCH = "https://plato.stanford.edu/search/searcher.py"
_ENTRY = "https://plato.stanford.edu/entries/{slug}/"
_AUTORIDADE = 0.9
_RE_SLUG = re.compile(r"^/entries/([^/#?\"]+)/")


def parse_busca(html: str) -> list[Referencia]:
    sopa = BeautifulSoup(html, "html.parser")
    vistos: list[str] = []
    refs: list[Referencia] = []
    for a in sopa.find_all("a", href=True):
        m = _RE_SLUG.match(a["href"])
        if not m:
            continue
        slug = m.group(1)
        if slug in vistos:
            continue
        vistos.append(slug)
        refs.append(
            Referencia(
                fonte="sep",
                id_externo=slug,
                titulo=a.get_text(strip=True) or slug,
                url=_ENTRY.format(slug=slug),
                idioma="en",
            )
        )
    return refs


def extrair_artigo(html: str) -> str:
    sopa = BeautifulSoup(html, "html.parser")
    art = sopa.find(id="article-content") or sopa.find(id="aueditable")
    if art is None:
        return ""
    return art.get_text(separator="\n").strip()


class SEP:
    nome = "sep"

    def buscar(self, query: str, *, limite: int, http) -> list[Referencia]:
        html = http.get_text(_SEARCH, params={"query": query})
        return parse_busca(html)[:limite]

    def baixar(self, ref: Referencia, *, http) -> Documento:
        html = http.get_text_cacheado(ref.url, fonte="sep", id_externo=ref.id_externo, ext="html")
        texto = extrair_artigo(html)
        prov = Proveniencia.de_fonte_remota(
            fonte="sep", obra=ref.titulo, url=ref.url,
            idioma="en", autoridade=_AUTORIDADE,
        )
        logger.info("SEP baixado", slug=ref.id_externo, chars=len(texto))
        return Documento(
            id=id_deterministico("sep", ref.id_externo),
            titulo=ref.titulo, texto=texto, proveniencia=prov,
        )
```

- [ ] **Step 4: Rodar teste, verificar que passa**

Run: `uv run pytest tests/knowledge/sources/remote/test_sep.py -v`
Esperado: PASS (3 testes).

- [ ] **Step 5: Commit (opcional)**

```bash
git add src/forge/knowledge/sources/remote/sep.py tests/knowledge/sources/remote/test_sep.py
git commit -m "feat(knowledge): fonte SEP (scraping plato.stanford.edu)"
```

---

## Task 8: Registry, integração no ingest e CLI

**Files:**
- Modify: `src/forge/knowledge/sources/remote/__init__.py` (registry)
- Modify: `src/forge/knowledge/ingest.py` (`ingerir_busca_remota`)
- Modify: `src/forge/cli.py` (flags `--source`/`--query`/`--limite`)
- Test: `tests/knowledge/sources/remote/test_base.py` (adicionar caso do registry) e `tests/test_cli.py`

**Interfaces:**
- Consumes: todas as fontes (Tasks 4–7); `Http` (Task 2); `buscar_e_baixar` (Task 3); `ingerir_documentos`, `_montar` (`ingest.py`).
- Produces: `construir_fontes(nomes, *, settings) -> list[FonteRemota]` (expande `"all"`); `ingerir_busca_remota(nomes_fontes, query, settings, *, limite=None) -> int`.

- [ ] **Step 1: Escrever teste falho do registry**

Adicionar a `tests/knowledge/sources/remote/test_base.py`:

```python
def test_construir_fontes_expande_all():
    from types import SimpleNamespace

    from forge.knowledge.sources.remote import construir_fontes

    settings = SimpleNamespace(knowledge=SimpleNamespace(wikisource_langs=["pt"]))
    fontes = construir_fontes(["all"], settings=settings)
    nomes = {f.nome for f in fontes}
    assert nomes == {"gutenberg", "internet_archive", "wikisource", "sep"}


def test_construir_fontes_subconjunto():
    from types import SimpleNamespace

    from forge.knowledge.sources.remote import construir_fontes

    settings = SimpleNamespace(knowledge=SimpleNamespace(wikisource_langs=["pt"]))
    fontes = construir_fontes(["gutenberg"], settings=settings)
    assert [f.nome for f in fontes] == ["gutenberg"]
```

Run: `uv run pytest tests/knowledge/sources/remote/test_base.py -k construir -v`
Esperado: FAIL (`ImportError: construir_fontes`).

- [ ] **Step 2: Implementar registry em `__init__.py`**

Substituir o conteúdo de `src/forge/knowledge/sources/remote/__init__.py`:

```python
"""Registry das fontes remotas: nome -> construtor. Resolve --source (e "all")."""
from forge.knowledge.sources.remote.gutenberg import Gutenberg
from forge.knowledge.sources.remote.internet_archive import InternetArchive
from forge.knowledge.sources.remote.sep import SEP
from forge.knowledge.sources.remote.wikisource import Wikisource


def construir_fontes(nomes: list[str], *, settings) -> list:
    construtores = {
        "gutenberg": lambda: Gutenberg(),
        "internet_archive": lambda: InternetArchive(),
        "wikisource": lambda: Wikisource(settings.knowledge.wikisource_langs),
        "sep": lambda: SEP(),
    }
    if "all" in nomes:
        nomes = list(construtores)
    return [construtores[n]() for n in nomes]
```

Run: `uv run pytest tests/knowledge/sources/remote/test_base.py -k construir -v`
Esperado: PASS.

- [ ] **Step 3: Escrever teste falho de `ingerir_busca_remota`**

Adicionar a `tests/knowledge/sources/remote/test_base.py` (topo com imports conforme necessário):

```python
def test_ingerir_busca_remota_sem_docs_retorna_zero(monkeypatch):
    from types import SimpleNamespace

    import forge.knowledge.ingest as ing

    monkeypatch.setattr(ing, "construir_fontes", lambda nomes, *, settings: [], raising=False)
    # buscar_e_baixar devolve [] com fontes vazias; _montar não deve ser chamado
    def _boom(_s):
        raise AssertionError("_montar não devia ser chamado sem docs")

    monkeypatch.setattr(ing, "_montar", _boom)

    settings = SimpleNamespace(
        knowledge=SimpleNamespace(
            wikisource_langs=["pt"], remote_top_n=3,
            remote_rate_delay=0, remote_timeout=5, cache_dir="x",
        )
    )
    total = ing.ingerir_busca_remota(["gutenberg"], "tema", settings)
    assert total == 0
```

Run: `uv run pytest tests/knowledge/sources/remote/test_base.py -k ingerir_busca -v`
Esperado: FAIL (`AttributeError: ingerir_busca_remota`).

- [ ] **Step 4: Implementar `ingerir_busca_remota` em `ingest.py`**

Adicionar ao final de `src/forge/knowledge/ingest.py`. Importar `construir_fontes` no topo do módulo para o monkeypatch alcançá-lo:

No topo do arquivo, junto aos imports:

```python
from forge.knowledge.sources.remote import construir_fontes
```

Ao final:

```python
def ingerir_busca_remota(nomes_fontes: list[str], query: str, settings: Settings, *, limite: int | None = None) -> int:
    """Busca por tema nas fontes remotas, baixa e ingere pelo pipeline padrão."""
    from forge.knowledge.sources.remote.base import buscar_e_baixar
    from forge.knowledge.sources.remote.http import Http

    k = settings.knowledge
    limite = limite or k.remote_top_n
    fontes = construir_fontes(nomes_fontes, settings=settings)
    http = Http(cache_dir=k.cache_dir, rate_delay=k.remote_rate_delay, timeout=k.remote_timeout)
    docs = buscar_e_baixar(fontes, query, limite=limite, http=http)
    if not docs:
        logger.info("Busca remota sem documentos", fontes=nomes_fontes, query=query[:60])
        return 0
    model, embed_fn, stores = _montar(settings)
    return ingerir_documentos(docs, model=model, embed_fn=embed_fn, stores=stores, settings=settings)
```

Run: `uv run pytest tests/knowledge/sources/remote/test_base.py -k ingerir_busca -v`
Esperado: PASS.

- [ ] **Step 5: Escrever teste falho da CLI**

Adicionar a `tests/test_cli.py` (seguir o estilo dos testes de CLI existentes; se já houver import de `main`, reusar):

```python
def test_ingest_source_sem_query_falha(monkeypatch):
    from forge.cli import main

    rc = main(["ingest", "--source", "gutenberg"])
    assert rc == 1


def test_ingest_source_chama_ingerir_busca_remota(monkeypatch):
    import forge.cli as cli

    capturado = {}

    def fake(nomes, query, settings, *, limite=None):
        capturado["nomes"] = nomes
        capturado["query"] = query
        capturado["limite"] = limite
        return 7

    monkeypatch.setattr("forge.knowledge.ingest.ingerir_busca_remota", fake)
    rc = cli.main(["ingest", "--source", "all", "--query", "estoicismo", "--limite", "2"])
    assert rc == 0
    assert capturado["nomes"] == ["all"]
    assert capturado["query"] == "estoicismo"
    assert capturado["limite"] == 2
```

Run: `uv run pytest tests/test_cli.py -k ingest_source -v`
Esperado: FAIL (argumento `--source` desconhecido / rc errado).

- [ ] **Step 6: Adicionar flags e roteamento na CLI**

Em `src/forge/cli.py`, no parser `ing` (após `--status`):

```python
    ing.add_argument(
        "--source",
        choices=["gutenberg", "internet_archive", "wikisource", "sep", "all"],
        default=None,
        help="Busca por tema numa fonte remota (ou 'all')",
    )
    ing.add_argument("--query", default=None, help="Tema para a busca remota")
    ing.add_argument("--limite", type=int, default=None, help="Máximo de obras por fonte")
```

Em `_cmd_ingest`, logo após `setup_logging(...)` e antes do bloco `if args.status`:

```python
    if args.source:
        if not args.query:
            logger.error("--source exige --query")
            return 1
        from forge.knowledge.ingest import ingerir_busca_remota

        try:
            total = ingerir_busca_remota([args.source], args.query, settings, limite=args.limite)
        except Exception as e:
            logger.error("Busca remota falhou", error=str(e), exc_info=True)
            return 1
        logger.info("Ingest remoto completo", chunks=total)
        print(f"chunks indexados: {total}")
        return 0
```

Run: `uv run pytest tests/test_cli.py -k ingest_source -v`
Esperado: PASS.

- [ ] **Step 7: Rodar a suíte inteira**

Run: `uv run pytest`
Esperado: PASS (toda a suíte, sem rede).

- [ ] **Step 8: Commit (opcional)**

```bash
git add src/forge/knowledge/sources/remote/__init__.py src/forge/knowledge/ingest.py src/forge/cli.py tests/knowledge/ tests/test_cli.py
git commit -m "feat(knowledge): registry de fontes + CLI ingest --source/--query"
```

---

## Verificação final

- [ ] `uv run pytest` — suíte verde, sem rede.
- [ ] Smoke real (opcional, gated): `uv run forge ingest --source gutenberg --query "stoicism" --limite 1` com os stores no ar (`docker compose up -d`) → imprime `chunks indexados: N>0` e cria `output/knowledge_cache/gutenberg/<id>.txt`.

## Notas de execução

- SEP e o endpoint de busca do IA/Wikisource podem mudar HTML/campos. Os parsers puros isolam isso: quebra real aparece em teste de integração, sem afetar o resto (best-effort).
- `plato.stanford.edu/search/searcher.py` é o ponto mais frágil (scraping). Se sumir, trocar `SEP.buscar` para casar título contra `contents.html` — o contrato `parse_busca(html)` não muda.
