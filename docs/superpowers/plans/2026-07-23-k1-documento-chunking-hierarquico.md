# K1 — Documento Original e Chunking Hierárquico — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Substituir a ingestão atual (chunk por caracteres + análise LLM do livro inteiro) por uma árvore estrutural determinística de Livro a Sentença, com o documento original persistido íntegro e identidade de chunk derivada do conteúdo.

**Architecture:** Duas árvores que nunca se misturam. A estrutural (Postgres) é imutável, derivada só do texto, sem nenhuma chamada de LLM. O grafo semântico (Neo4j) é evolutivo e referencia `chunk_id` — não é escrito em K1. Extração devolve texto cru + marcas de cabeçalho + offsets de página; a montagem da árvore usa só essas marcas. Embedding sai apenas das folhas-parágrafo (small-to-big).

**Tech Stack:** Python 3.12, pydantic v2, psycopg 3, qdrant-client, sentence-transformers (bge-m3), pypdf, ebooklib, BeautifulSoup, pytest.

## Global Constraints

- **Nenhum commit.** Instrução explícita do usuário. Cada tarefa termina com uma verificação rodando a suite, não com `git commit`.
- **Zero LLM na ingestão de conteúdo.** A única chamada de LLM que resta na camada é a tradução do termo de busca em fontes remotas, que não toca o conteúdo.
- **Texto nunca é alterado.** `documentos.texto` é a extração crua. O texto de um chunk é sempre uma fatia por offset desse original. Normalização existe só como entrada transitória de `tsvector` e embedding, nunca persistida.
- **Identidade de chunk vem do conteúdo:** `id_deterministico(documento_id, sha256(texto), ocorrencia)`. Nunca da posição.
- **Retriever dormente.** Nada em K1-K4 pode depender de retrieval. `hybrid.py` permanece no repositório, marcado dormente.
- **Português no domínio.** Nomes de estado, campos e mensagens de log em português; logging estruturado via `structlog` com `key=value`, nunca f-string.
- **Injeção de dependências:** `embed_fn` e `stores` entram por parâmetro; as funções de topo montam as reais a partir de `Settings`.
- **Padding do caminho materializado:** 4 dígitos por nível, separados por ponto (`0001.0003.0002`).
- **`paragrafo_min_chars` = 40** (default configurável).

---

## Decisão de plano que refina o spec

O spec §6.3 manda persistir até sentença. Isso se mantém: toda sentença é uma linha com id estável. Mas a **coluna `texto` só é preenchida no nível `paragrafo`**. Todos os outros níveis (livro, capítulo, subcapítulo, seção, sentença) guardam `offset_inicio`/`offset_fim` e derivam o texto de `documentos.texto` sob demanda. Evita guardar o livro inteiro 4 vezes e alinha o índice léxico à mesma granularidade do embedding.

O id da sentença continua vindo do `sha256` do seu texto — o texto existe no momento da construção, só não é persistido.

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `src/forge/knowledge/domain/models.py` | **Modificar.** `Proveniencia` (Nível 1 completo), `Documento` (texto, hash, chave_externa), `Chunk` hierárquico, `Nivel`, `id_de_chunk`, `caminho_filho`. Remove `Secao`. |
| `src/forge/knowledge/sources/extract/tipos.py` | **Criar.** `Marca`, `TextoExtraido`, `pagina_de_offset`. |
| `src/forge/knowledge/sources/extract/texto.py` | **Criar.** TXT/MD: detecção de marcas por regex de cabeçalho. |
| `src/forge/knowledge/sources/extract/pdf.py` | **Criar.** PDF: concatenação com offsets de página + marcas. |
| `src/forge/knowledge/sources/extract/epub.py` | **Criar.** EPUB: spine como capítulo, `<h1>`-`<h6>` como subnível. |
| `src/forge/knowledge/sources/extract/__init__.py` | **Criar.** Dispatcher por extensão + `marcas_de_texto` para fontes sem arquivo. |
| `src/forge/knowledge/pipeline/segmentar.py` | **Criar.** Parágrafos e sentenças como intervalos de offset. |
| `src/forge/knowledge/pipeline/arvore.py` | **Criar.** Marcas + segmentação → lista de `Chunk` com nível, pai, caminho, ordem, página. |
| `src/forge/knowledge/sources/book.py` | **Modificar.** Arquivo → `(Documento, TextoExtraido)`; hash, idioma, metadados. |
| `src/forge/knowledge/stores/catalog.py` | **Modificar.** Schema dos dois níveis, tsvector por idioma, upserts de árvore, `existe_chave_externa`, `resetar`. |
| `src/forge/knowledge/stores/vector.py` | **Modificar.** Payload novo, só parágrafos, `resetar`. |
| `src/forge/knowledge/stores/graph.py` | **Modificar.** `params_documento` deixa de depender de `Documento`; `resetar`. |
| `src/forge/knowledge/ingest.py` | **Modificar.** Pipeline sem LLM; `ingerir_documentos` recebe `(Documento, TextoExtraido)`. |
| `src/forge/knowledge/retriever/hybrid.py` | **Modificar.** Marcar dormente. |
| `src/forge/knowledge/integration.py` | **Deletar.** Refeito em K5. |
| `src/forge/knowledge/pipeline/{chunk,structure,summarize,entities,relations,concepts}.py` | **Deletar.** |
| `src/forge/orchestration/graph.py` | **Modificar.** Remove ponte research→knowledge. |
| `src/forge/cli.py` | **Modificar.** Remove `buscar`; adiciona `ingest --reset`. |
| `src/forge/infrastructure/config.py` | **Modificar.** Remove `chunk_size`/`chunk_overlap`; adiciona `paragrafo_min_chars`. |
| `src/forge/knowledge/sources/web.py` + `sources/remote/*.py` | **Modificar.** `chave_externa` e hash. |

---

### Task 1: Modelo de domínio das duas camadas

**Files:**
- Modify: `src/forge/knowledge/domain/models.py`
- Test: `tests/knowledge/test_models.py`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `Nivel = Literal["livro","capitulo","subcapitulo","secao","paragrafo","sentenca"]`
  - `id_de_chunk(documento_id: str, texto: str, ocorrencia: int) -> str`
  - `caminho_filho(caminho_pai: str, ordem: int) -> str`
  - `hash_texto(texto: str) -> str`
  - `Proveniencia(tipo, fonte, autor, obra, edicao, isbn, licenca, url, data_publicacao, idioma, autoridade)` com `de_livro`, `de_web`, `de_fonte_remota`
  - `Documento(id, hash_sha256, titulo, texto, proveniencia, chave_externa)`
  - `Chunk(id, documento_id, pai_id, nivel, caminho, ordem, titulo, texto, pagina, offset_inicio, offset_fim, embedding)`
  - `NIVEL_FOLHA = "paragrafo"` — o único nível embedado e com `texto` persistido. Importado por `arvore.py`, `vector.py` e `ingest.py` em vez de repetir a string.

- [ ] **Step 1: Write the failing test**

Create `tests/knowledge/test_models.py`:

```python
import pytest

from forge.knowledge.domain.models import (
    Chunk,
    Documento,
    Proveniencia,
    caminho_filho,
    hash_texto,
    id_de_chunk,
)


def test_id_de_chunk_vem_do_conteudo_nao_da_posicao():
    a = id_de_chunk("doc-1", "O homem está condenado à liberdade.", 0)
    b = id_de_chunk("doc-1", "O homem está condenado à liberdade.", 0)
    assert a == b


def test_id_de_chunk_separa_ocorrencias_do_mesmo_texto():
    a = id_de_chunk("doc-1", "Ibid.", 0)
    b = id_de_chunk("doc-1", "Ibid.", 1)
    assert a != b


def test_id_de_chunk_separa_documentos():
    a = id_de_chunk("doc-1", "mesmo texto", 0)
    b = id_de_chunk("doc-2", "mesmo texto", 0)
    assert a != b


def test_caminho_filho_usa_padding_de_quatro_digitos():
    assert caminho_filho("", 1) == "0001"
    assert caminho_filho("0001", 3) == "0001.0003"
    assert caminho_filho("0001.0003", 12) == "0001.0003.0012"


def test_caminho_ordena_lexicograficamente_na_ordem_numerica():
    caminhos = [caminho_filho("0001", n) for n in (10, 2, 1)]
    assert sorted(caminhos) == [
        caminho_filho("0001", 1),
        caminho_filho("0001", 2),
        caminho_filho("0001", 10),
    ]


def test_hash_texto_e_estavel_e_hexadecimal():
    h = hash_texto("texto")
    assert h == hash_texto("texto")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_documento_carrega_nivel_1_completo():
    prov = Proveniencia.de_livro(
        fonte="etica.pdf", autor="Espinosa", obra="Ética",
        edicao="2ª", isbn="978-85-000-0000-0", licenca="domínio público",
        idioma="pt", data_publicacao="1677",
    )
    doc = Documento(
        id="doc-1", hash_sha256=hash_texto("corpo"), titulo="Ética",
        texto="corpo", proveniencia=prov,
    )
    assert doc.texto == "corpo"
    assert doc.proveniencia.isbn == "978-85-000-0000-0"
    assert doc.proveniencia.licenca == "domínio público"
    assert doc.proveniencia.autoridade == 1.0
    assert doc.chave_externa is None


def test_chunk_e_no_de_arvore_sem_proveniencia_propria():
    chunk = Chunk(
        id="c-1", documento_id="doc-1", pai_id="c-0", nivel="paragrafo",
        caminho="0001.0002", ordem=2, texto="trecho",
        offset_inicio=10, offset_fim=16,
    )
    assert chunk.pagina is None
    assert chunk.embedding is None
    assert not hasattr(chunk, "proveniencia")


def test_chunk_rejeita_nivel_invalido():
    with pytest.raises(ValueError):
        Chunk(
            id="c-1", documento_id="doc-1", nivel="ideia",
            caminho="0001", ordem=1, offset_inicio=0, offset_fim=1,
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/knowledge/test_models.py -v`
Expected: FAIL com `ImportError: cannot import name 'caminho_filho'`.

- [ ] **Step 3: Write the implementation**

Replace the whole of `src/forge/knowledge/domain/models.py`:

```python
"""Modelos da camada Knowledge — Níveis 1 e 2 de docs/knowledge.md.

Duas árvores que nunca se misturam. Esta é a estrutural: derivada só do texto,
imutável, sem LLM. O grafo semântico (Conceito/Ideia/Argumento/Afirmação) vive
no Neo4j, referencia `chunk_id` e é escrito a partir de K3.

`Proveniencia` acompanha o documento e é o que separa citação de livro (fonte
primária) de snippet de web. Sem ela a biblioteca reintroduz o problema de fonte
não-rastreável que existe para resolver.
"""
from __future__ import annotations

import hashlib
import uuid
from typing import Literal

from pydantic import BaseModel, Field

TipoFonte = Literal["livro", "web"]
Nivel = Literal["livro", "capitulo", "subcapitulo", "secao", "paragrafo", "sentenca"]
TipoEntidade = Literal["filosofo", "escola", "obra", "ideia", "conceito", "outro"]

# Único nível embedado e com `texto` persistido (small-to-big). Os demais níveis
# guardam offsets e derivam o texto de `documentos.texto`.
NIVEL_FOLHA: Nivel = "paragrafo"

# Autoridade padrão por tipo de fonte. Livro é fonte primária controlada;
# web é ponto de partida, não prova.
_AUTORIDADE_LIVRO = 1.0
_AUTORIDADE_WEB = 0.4

_NAMESPACE = uuid.UUID("6f9b2c1e-0d3a-4a1b-9c7e-2f8a1b3c4d5e")

# Largura do segmento no caminho materializado. 4 dígitos deixam a ordem
# lexicográfica coincidir com a numérica até 9999 filhos por nó.
_LARGURA_CAMINHO = 4


def id_deterministico(*partes: str) -> str:
    """UUID estável a partir das partes — mesma entrada, mesmo id."""
    return str(uuid.uuid5(_NAMESPACE, "::".join(partes)))


def hash_texto(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def id_de_chunk(documento_id: str, texto: str, ocorrencia: int) -> str:
    """Identidade por conteúdo, nunca por posição.

    A camada semântica acumula anotações sobre `chunk_id`. Se o id viesse da
    ordem, inserir um parágrafo no capítulo 1 invalidaria tudo que veio depois.
    `ocorrencia` desempata texto repetido no mesmo documento ('Ibid.').
    """
    return id_deterministico(documento_id, hash_texto(texto), str(ocorrencia))


def caminho_filho(caminho_pai: str, ordem: int) -> str:
    segmento = str(ordem).zfill(_LARGURA_CAMINHO)
    return f"{caminho_pai}.{segmento}" if caminho_pai else segmento


class Proveniencia(BaseModel):
    tipo: TipoFonte
    fonte: str
    autor: str | None = None
    obra: str | None = None
    edicao: str | None = None
    isbn: str | None = None
    licenca: str | None = None
    url: str | None = None
    data_publicacao: str | None = None
    idioma: str | None = None
    autoridade: float = Field(ge=0.0, le=1.0)

    @classmethod
    def de_livro(
        cls,
        fonte: str,
        autor: str | None = None,
        obra: str | None = None,
        edicao: str | None = None,
        isbn: str | None = None,
        licenca: str | None = None,
        idioma: str | None = None,
        data_publicacao: str | None = None,
    ) -> Proveniencia:
        return cls(
            tipo="livro", fonte=fonte, autor=autor, obra=obra, edicao=edicao,
            isbn=isbn, licenca=licenca, idioma=idioma,
            data_publicacao=data_publicacao, autoridade=_AUTORIDADE_LIVRO,
        )

    @classmethod
    def de_web(
        cls, url: str, titulo: str | None = None, data_publicacao: str | None = None
    ) -> Proveniencia:
        return cls(
            tipo="web", fonte="web_search", obra=titulo, url=url,
            data_publicacao=data_publicacao, autoridade=_AUTORIDADE_WEB,
        )

    @classmethod
    def de_fonte_remota(
        cls,
        *,
        fonte: str,
        autor: str | None = None,
        obra: str | None = None,
        url: str | None = None,
        idioma: str | None = None,
        licenca: str | None = None,
        autoridade: float,
    ) -> Proveniencia:
        return cls(
            tipo="livro", fonte=fonte, autor=autor, obra=obra, url=url,
            idioma=idioma, licenca=licenca, autoridade=autoridade,
        )


class Conceito(BaseModel):
    nome: str
    descricao: str | None = None


class Entidade(BaseModel):
    nome: str
    tipo: TipoEntidade = "outro"


class Relacionamento(BaseModel):
    origem: str
    tipo: str
    destino: str


class Documento(BaseModel):
    """Nível 1 — fonte da verdade. `texto` é a extração crua, nunca alterada.

    `chave_externa` identifica a obra na fonte de origem (`gutenberg::1234`) e
    permite pular o download de algo já ingerido, antes de existir hash.
    """
    id: str
    hash_sha256: str
    titulo: str
    texto: str
    proveniencia: Proveniencia
    chave_externa: str | None = None


class Chunk(BaseModel):
    """Nível 2 — nó da árvore estrutural.

    Sem proveniência própria: ela é do documento e é resolvida por join. O
    capítulo de um chunk é o ancestral de nível capítulo, resolvido pelo
    `caminho` — não é campo duplicado.
    """
    id: str
    documento_id: str
    pai_id: str | None = None
    nivel: Nivel
    caminho: str
    ordem: int
    titulo: str | None = None
    texto: str | None = None
    pagina: int | None = None
    offset_inicio: int
    offset_fim: int
    embedding: list[float] | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/knowledge/test_models.py -v`
Expected: 9 passed.

- [ ] **Step 5: Checkpoint (no commit)**

Run: `uv run pytest tests/knowledge/test_models.py tests/knowledge/test_proveniencia.py -v`
Expected: `test_proveniencia.py` provavelmente falha — ele testa a API antiga. Delete `tests/knowledge/test_proveniencia.py`; os casos equivalentes já estão em `test_models.py`. Rode de novo e confirme que só `test_models.py` roda e passa.

---

### Task 2: Tipos de extração e marcas em texto puro

**Files:**
- Create: `src/forge/knowledge/sources/extract/__init__.py`
- Create: `src/forge/knowledge/sources/extract/tipos.py`
- Create: `src/forge/knowledge/sources/extract/texto.py`
- Test: `tests/knowledge/extract/__init__.py` (vazio), `tests/knowledge/extract/test_texto.py`

**Interfaces:**
- Consumes: nada da Task 1.
- Produces:
  - `Marca(offset: int, nivel: int, titulo: str, comprimento: int)` — `nivel` 1=capítulo, 2=subcapítulo, 3=seção. `comprimento` é quantos caracteres o cabeçalho ocupa a partir de `offset`; a árvore usa isso para saber onde o corpo começa. Sem ele, `# Capítulo 1` deixaria o sobejo `1` no primeiro parágrafo, porque `titulo` não inclui as cerquilhas.
  - `TextoExtraido(texto: str, marcas: list[Marca], paginas: list[int], idioma: str | None)`
  - `pagina_de_offset(paginas: list[int], offset: int) -> int | None`
  - `marcas_de_texto(texto: str) -> list[Marca]`
  - `extrair_texto(texto: str) -> TextoExtraido`

- [ ] **Step 1: Write the failing test**

Create `tests/knowledge/extract/__init__.py` (empty) and `tests/knowledge/extract/test_texto.py`:

```python
from forge.knowledge.sources.extract.texto import extrair_texto, marcas_de_texto
from forge.knowledge.sources.extract.tipos import pagina_de_offset

MD = """# Parte I

abertura

## Capítulo 1

corpo do capítulo

### Seção A

detalhe
"""


def test_marcas_de_markdown_carregam_nivel_pelo_numero_de_cerquilhas():
    marcas = marcas_de_texto(MD)
    assert [(m.nivel, m.titulo) for m in marcas] == [
        (1, "Parte I"),
        (2, "Capítulo 1"),
        (3, "Seção A"),
    ]


def test_marca_aponta_para_o_offset_do_cabecalho_no_texto_original():
    marcas = marcas_de_texto(MD)
    for marca in marcas:
        assert MD[marca.offset:].startswith("#")


def test_comprimento_cobre_a_linha_inteira_do_cabecalho():
    marca = marcas_de_texto(MD)[1]
    assert MD[marca.offset:marca.offset + marca.comprimento] == "## Capítulo 1"
    # O corpo começa depois do cabeçalho inteiro, não depois do título.
    assert MD[marca.offset + marca.comprimento:].lstrip().startswith("corpo")


def test_cabecalho_em_prosa_e_reconhecido_sem_markdown():
    texto = "prólogo\n\nCapítulo 3\n\ncorpo\n\nCAPÍTULO IV\n\nmais\n"
    marcas = marcas_de_texto(texto)
    assert [m.titulo for m in marcas] == ["Capítulo 3", "CAPÍTULO IV"]
    assert all(m.nivel == 1 for m in marcas)


def test_cerquilha_no_meio_da_linha_nao_vira_marca():
    texto = "ele escreveu # sobre isso\n\ncorpo\n"
    assert marcas_de_texto(texto) == []


def test_texto_sem_cabecalho_nao_gera_marca():
    assert marcas_de_texto("só prosa corrida\n\nmais prosa\n") == []


def test_extrair_texto_preserva_o_original_e_nao_tem_paginas():
    extraido = extrair_texto(MD)
    assert extraido.texto == MD
    assert extraido.paginas == []
    assert len(extraido.marcas) == 3


def test_pagina_de_offset_mapeia_para_a_pagina_que_contem_o_offset():
    paginas = [0, 100, 250]
    assert pagina_de_offset(paginas, 0) == 1
    assert pagina_de_offset(paginas, 99) == 1
    assert pagina_de_offset(paginas, 100) == 2
    assert pagina_de_offset(paginas, 999) == 3


def test_pagina_de_offset_sem_paginas_devolve_nulo():
    assert pagina_de_offset([], 10) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/knowledge/extract/test_texto.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'forge.knowledge.sources.extract'`.

- [ ] **Step 3: Write the implementation**

Create `src/forge/knowledge/sources/extract/tipos.py`:

```python
"""Contrato da extração: texto cru + onde estão os cabeçalhos e as páginas.

A extração não interpreta a estrutura, só marca onde ela começa. Quem monta a
árvore é `pipeline.arvore`. Separar os dois deixa o detector de cabeçalho
testável sem PDF e a árvore testável sem extrator.
"""
from bisect import bisect_right
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Marca:
    """Cabeçalho encontrado no texto. `nivel`: 1=capítulo, 2=subcapítulo, 3=seção.

    `comprimento` é quanto o cabeçalho ocupa a partir de `offset`. A árvore usa
    isso para achar o início do corpo — `titulo` não serve, porque não inclui as
    cerquilhas do markdown.
    """
    offset: int
    nivel: int
    titulo: str
    comprimento: int


@dataclass
class TextoExtraido:
    texto: str
    marcas: list[Marca] = field(default_factory=list)
    # Offset inicial de cada página, em ordem. Vazio quando o formato não tem
    # páginas (EPUB, TXT, MD) — nesse caso o chunk fica com página nula.
    paginas: list[int] = field(default_factory=list)
    idioma: str | None = None


def pagina_de_offset(paginas: list[int], offset: int) -> int | None:
    """Número de página (base 1) que contém o offset, ou None se não há páginas."""
    if not paginas:
        return None
    return bisect_right(paginas, offset)
```

Create `src/forge/knowledge/sources/extract/texto.py`:

```python
"""Detecção de cabeçalho em texto puro (TXT/MD) e em texto vindo de fonte remota.

Duas famílias: markdown (`#` a `######`, o nível é a contagem de cerquilhas) e
prosa (`Capítulo 3`, `Parte II`), sempre linha inteira — cerquilha ou palavra no
meio da frase não é cabeçalho.
"""
import re

from forge.knowledge.sources.extract.tipos import Marca, TextoExtraido

_MARKDOWN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_PROSA = re.compile(
    r"^((?:cap[íi]tulo|chapter|parte|part|se[çc][ãa]o)\s+[\dIVXLC]+.*?)\s*$",
    re.IGNORECASE,
)


def marcas_de_texto(texto: str) -> list[Marca]:
    marcas: list[Marca] = []
    offset = 0
    for linha in texto.splitlines(keepends=True):
        despida = linha.strip()
        comprimento = len(linha.rstrip("\r\n"))
        md = _MARKDOWN.match(despida)
        if md:
            marcas.append(
                Marca(offset=offset, nivel=len(md.group(1)), titulo=md.group(2),
                      comprimento=comprimento)
            )
        else:
            prosa = _PROSA.match(despida)
            if prosa:
                marcas.append(
                    Marca(offset=offset, nivel=1, titulo=prosa.group(1),
                          comprimento=comprimento)
                )
        offset += len(linha)
    return marcas


def extrair_texto(texto: str) -> TextoExtraido:
    """TXT/MD e texto de fonte remota: sem páginas, marcas por cabeçalho."""
    return TextoExtraido(texto=texto, marcas=marcas_de_texto(texto), paginas=[])
```

Create `src/forge/knowledge/sources/extract/__init__.py`:

```python
"""Extração por formato: arquivo -> TextoExtraido. Imports preguiçosos.

Quem só ingere .txt não precisa de pypdf nem ebooklib instalados.
"""
from pathlib import Path

from forge.knowledge.sources.extract.texto import extrair_texto, marcas_de_texto
from forge.knowledge.sources.extract.tipos import Marca, TextoExtraido, pagina_de_offset

EXTENSOES_SUPORTADAS = {".txt", ".md", ".pdf", ".epub"}

__all__ = [
    "EXTENSOES_SUPORTADAS",
    "Marca",
    "TextoExtraido",
    "extrair_arquivo",
    "extrair_texto",
    "marcas_de_texto",
    "pagina_de_offset",
]


def extrair_arquivo(path: Path, *, ocr_enabled: bool = False) -> TextoExtraido:
    path = Path(path)
    sufixo = path.suffix.lower()
    if sufixo not in EXTENSOES_SUPORTADAS:
        raise ValueError(
            f"Formato {sufixo!r} não suportado; suporta {sorted(EXTENSOES_SUPORTADAS)}"
        )
    if sufixo in {".txt", ".md"}:
        return extrair_texto(path.read_text(encoding="utf-8"))
    if sufixo == ".pdf":
        from forge.knowledge.sources.extract.pdf import extrair_pdf

        return extrair_pdf(path, ocr_enabled=ocr_enabled)
    from forge.knowledge.sources.extract.epub import extrair_epub

    return extrair_epub(path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/knowledge/extract/test_texto.py -v`
Expected: 9 passed.

Nota: `extrair_arquivo` importa `pdf`/`epub` de forma preguiçosa, então este passo passa antes das Tasks 3 e 4 existirem.

- [ ] **Step 5: Checkpoint (no commit)**

Run: `uv run pytest tests/knowledge -v`
Expected: PASS. Nenhuma regressão.

---

### Task 3: Extração de PDF com offsets de página

**Files:**
- Create: `src/forge/knowledge/sources/extract/pdf.py`
- Test: `tests/knowledge/extract/test_pdf.py`

**Interfaces:**
- Consumes: `TextoExtraido`, `marcas_de_texto` (Task 2).
- Produces: `extrair_pdf(path: Path, *, ocr_enabled: bool = False) -> TextoExtraido`, `montar_paginas(paginas: list[str]) -> tuple[str, list[int]]`.

- [ ] **Step 1: Write the failing test**

Create `tests/knowledge/extract/test_pdf.py`:

```python
from forge.knowledge.sources.extract.pdf import montar_paginas
from forge.knowledge.sources.extract.tipos import pagina_de_offset


def test_montar_paginas_concatena_e_devolve_offset_inicial_de_cada_uma():
    texto, paginas = montar_paginas(["um", "dois", "três"])
    assert texto == "um\n\ndois\n\ntrês"
    assert paginas == [0, 4, 10]
    assert texto[paginas[1]:].startswith("dois")
    assert texto[paginas[2]:].startswith("três")


def test_offset_de_cada_pagina_resolve_para_o_numero_certo():
    texto, paginas = montar_paginas(["um", "dois", "três"])
    assert pagina_de_offset(paginas, texto.index("um")) == 1
    assert pagina_de_offset(paginas, texto.index("dois")) == 2
    assert pagina_de_offset(paginas, texto.index("três")) == 3


def test_pagina_vazia_ocupa_offset_mas_nao_quebra_a_contagem():
    texto, paginas = montar_paginas(["um", "", "três"])
    assert len(paginas) == 3
    assert pagina_de_offset(paginas, texto.index("três")) == 3


def test_lista_vazia_devolve_texto_vazio_e_nenhuma_pagina():
    assert montar_paginas([]) == ("", [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/knowledge/extract/test_pdf.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'forge.knowledge.sources.extract.pdf'`.

- [ ] **Step 3: Write the implementation**

Create `src/forge/knowledge/sources/extract/pdf.py`:

```python
"""PDF -> texto + offsets de página.

Nós concatenamos as páginas e registramos o offset acumulado de cada uma: o
offset é controle nosso, não do extrator. `pypdf` não garante nada sobre
posição, então derivar página a partir dele depois seria chute.
"""
from pathlib import Path

from forge.infrastructure.logging import get_logger
from forge.knowledge.sources.extract.texto import marcas_de_texto
from forge.knowledge.sources.extract.tipos import TextoExtraido

logger = get_logger(__name__)

_SEPARADOR = "\n\n"


def montar_paginas(paginas: list[str]) -> tuple[str, list[int]]:
    """Concatena as páginas e devolve (texto, offset inicial de cada página)."""
    if not paginas:
        return "", []
    offsets: list[int] = []
    partes: list[str] = []
    posicao = 0
    for indice, pagina in enumerate(paginas):
        if indice:
            partes.append(_SEPARADOR)
            posicao += len(_SEPARADOR)
        offsets.append(posicao)
        partes.append(pagina)
        posicao += len(pagina)
    return "".join(partes), offsets


def extrair_pdf(path: Path, *, ocr_enabled: bool = False) -> TextoExtraido:
    from pypdf import PdfReader

    leitor = PdfReader(str(path))
    brutas = [pagina.extract_text() or "" for pagina in leitor.pages]
    texto, offsets = montar_paginas(brutas)

    if not texto.strip() and ocr_enabled:
        logger.info("PDF sem camada de texto, caindo para OCR", fonte=path.name)
        brutas = _ocr_paginas(path)
        texto, offsets = montar_paginas(brutas)
    elif not texto.strip():
        logger.warning("PDF sem texto extraível e OCR desabilitado", fonte=path.name)

    logger.info("PDF extraído", fonte=path.name, paginas=len(offsets), chars=len(texto))
    return TextoExtraido(texto=texto, marcas=marcas_de_texto(texto), paginas=offsets)


def _ocr_paginas(path: Path) -> list[str]:
    """OCR opcional, atrás de `ocr_enabled`. Requer pytesseract + tesseract no SO."""
    import pytesseract
    from pdf2image import convert_from_path

    return [pytesseract.image_to_string(img, lang="por") for img in convert_from_path(str(path))]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/knowledge/extract/test_pdf.py -v`
Expected: 4 passed.

- [ ] **Step 5: Checkpoint (no commit)**

Run: `uv run pytest tests/knowledge -v`
Expected: PASS.

---

### Task 4: Extração de EPUB usando spine e headings

**Files:**
- Create: `src/forge/knowledge/sources/extract/epub.py`
- Test: `tests/knowledge/extract/test_epub.py`

**Interfaces:**
- Consumes: `Marca`, `TextoExtraido` (Task 2).
- Produces: `extrair_epub(path: Path) -> TextoExtraido`, `montar_itens(itens: list[tuple[str, str]]) -> TextoExtraido` onde cada item é `(titulo_do_spine, html)`.

- [ ] **Step 1: Write the failing test**

Create `tests/knowledge/extract/test_epub.py`:

```python
from forge.knowledge.sources.extract.epub import montar_itens


def test_cada_item_do_spine_vira_marca_de_capitulo():
    extraido = montar_itens([("Capítulo 1", "<p>um</p>"), ("Capítulo 2", "<p>dois</p>")])
    capitulos = [m for m in extraido.marcas if m.nivel == 1]
    assert [m.titulo for m in capitulos] == ["Capítulo 1", "Capítulo 2"]


def test_headings_do_html_viram_subniveis_abaixo_do_capitulo():
    extraido = montar_itens([("Capítulo 1", "<h2>Parte A</h2><p>um</p><h3>Trecho</h3><p>dois</p>")])
    assert [(m.nivel, m.titulo) for m in extraido.marcas] == [
        (1, "Capítulo 1"),
        (2, "Parte A"),
        (3, "Trecho"),
    ]


def test_marca_aponta_para_o_offset_real_do_titulo_no_texto_montado():
    extraido = montar_itens([("Capítulo 1", "<h2>Parte A</h2><p>corpo</p>")])
    for marca in extraido.marcas:
        assert extraido.texto[marca.offset:].startswith(marca.titulo)


def test_epub_nao_tem_paginas():
    extraido = montar_itens([("Capítulo 1", "<p>um</p>")])
    assert extraido.paginas == []


def test_texto_do_html_e_preservado_no_corpo():
    extraido = montar_itens([("Capítulo 1", "<p>o homem é livre</p>")])
    assert "o homem é livre" in extraido.texto
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/knowledge/extract/test_epub.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'forge.knowledge.sources.extract.epub'`.

- [ ] **Step 3: Write the implementation**

Create `src/forge/knowledge/sources/extract/epub.py`:

```python
"""EPUB -> texto + marcas.

O spine é o melhor sinal estrutural dos três formatos: ele diz onde cada
capítulo começa, sem heurística nenhuma. Dentro do capítulo, <h2>-<h6> dão
subcapítulo e seção. Hoje esse sinal é jogado fora por um get_text() no arquivo
inteiro.
"""
from pathlib import Path

from forge.infrastructure.logging import get_logger
from forge.knowledge.sources.extract.tipos import Marca, TextoExtraido

logger = get_logger(__name__)

_SEPARADOR = "\n\n"
_HEADINGS = ["h1", "h2", "h3", "h4", "h5", "h6"]


def _nivel_do_heading(nome: str) -> int:
    """<h2> vira nível 2, <h3> vira 3. <h1> dentro do item é nível 2: o nível 1
    já é o capítulo do spine, e dois capítulos aninhados não fazem sentido."""
    numero = int(nome[1])
    return max(2, numero)


def montar_itens(itens: list[tuple[str, str]]) -> TextoExtraido:
    """(titulo do spine, html) -> texto concatenado + marcas com offsets reais."""
    from bs4 import BeautifulSoup

    partes: list[str] = []
    marcas: list[Marca] = []
    posicao = 0

    for titulo, html in itens:
        if partes:
            partes.append(_SEPARADOR)
            posicao += len(_SEPARADOR)

        marcas.append(
            Marca(offset=posicao, nivel=1, titulo=titulo, comprimento=len(titulo))
        )
        partes.append(titulo)
        posicao += len(titulo)

        sopa = BeautifulSoup(html, "html.parser")
        for elemento in sopa.find_all(_HEADINGS + ["p"]):
            texto = elemento.get_text(separator=" ", strip=True)
            if not texto:
                continue
            partes.append(_SEPARADOR)
            posicao += len(_SEPARADOR)
            if elemento.name in _HEADINGS:
                marcas.append(
                    Marca(
                        offset=posicao, nivel=_nivel_do_heading(elemento.name),
                        titulo=texto, comprimento=len(texto),
                    )
                )
            partes.append(texto)
            posicao += len(texto)

    return TextoExtraido(texto="".join(partes), marcas=marcas, paginas=[])


def extrair_epub(path: Path) -> TextoExtraido:
    import ebooklib
    from ebooklib import epub

    livro = epub.read_epub(str(path))
    itens: list[tuple[str, str]] = []
    for item in livro.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        titulo = getattr(item, "title", None) or Path(item.get_name()).stem
        itens.append((titulo, item.get_content().decode("utf-8", errors="replace")))

    extraido = montar_itens(itens)
    logger.info("EPUB extraído", fonte=path.name, itens=len(itens), chars=len(extraido.texto))
    return extraido
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/knowledge/extract/test_epub.py -v`
Expected: 5 passed.

- [ ] **Step 5: Checkpoint (no commit)**

Run: `uv run pytest tests/knowledge -v`
Expected: PASS.

---

### Task 5: Segmentação em parágrafos e sentenças por offset

**Files:**
- Create: `src/forge/knowledge/pipeline/segmentar.py`
- Test: `tests/knowledge/pipeline/test_segmentar.py`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `paragrafos(texto: str, inicio: int, fim: int, *, min_chars: int = 40) -> list[tuple[int, int]]`
  - `sentencas(texto: str, inicio: int, fim: int) -> list[tuple[int, int]]`

  Ambas devolvem intervalos `(offset_inicio, offset_fim)` absolutos no `texto` completo do documento. Fatiar `texto[inicio:fim]` dá exatamente o conteúdo do nó.

- [ ] **Step 1: Write the failing test**

Create `tests/knowledge/pipeline/test_segmentar.py`:

```python
from forge.knowledge.pipeline.segmentar import paragrafos, sentencas

TEXTO = (
    "Primeiro parágrafo com tamanho suficiente para não ser mesclado.\n\n"
    "Segundo parágrafo, também suficientemente longo para sobreviver sozinho.\n\n"
    "curto\n\n"
    "Terceiro parágrafo longo o bastante para permanecer separado do resto."
)


def test_paragrafos_devolvem_offsets_absolutos_que_fatiam_o_original():
    for inicio, fim in paragrafos(TEXTO, 0, len(TEXTO)):
        assert TEXTO[inicio:fim].strip() == TEXTO[inicio:fim]
        assert TEXTO[inicio:fim] in TEXTO


def test_paragrafo_curto_e_mesclado_no_seguinte():
    trechos = [TEXTO[i:f] for i, f in paragrafos(TEXTO, 0, len(TEXTO), min_chars=40)]
    assert not any(t == "curto" for t in trechos)
    assert any(t.startswith("curto") and "Terceiro" in t for t in trechos)


def test_segmentacao_respeita_a_janela_pedida():
    inicio = TEXTO.index("Segundo")
    fim = TEXTO.index("curto")
    resultado = paragrafos(TEXTO, inicio, fim)
    assert all(inicio <= i and f <= fim for i, f in resultado)


def test_janela_so_com_espaco_nao_gera_paragrafo():
    branco = "   \n\n   "
    assert paragrafos(branco, 0, len(branco)) == []


def test_sentencas_quebram_em_pontuacao_final():
    texto = "O homem é livre. Ele escolhe. E responde por isso."
    trechos = [texto[i:f] for i, f in sentencas(texto, 0, len(texto))]
    assert trechos == ["O homem é livre.", "Ele escolhe.", "E responde por isso."]


def test_abreviacao_nao_quebra_sentenca():
    texto = "Segundo o Dr. Silva, a virtude é hábito. Aristóteles concorda."
    trechos = [texto[i:f] for i, f in sentencas(texto, 0, len(texto))]
    assert trechos == [
        "Segundo o Dr. Silva, a virtude é hábito.",
        "Aristóteles concorda.",
    ]


def test_sentenca_sem_pontuacao_final_ainda_e_devolvida():
    texto = "uma frase sem ponto"
    assert [texto[i:f] for i, f in sentencas(texto, 0, len(texto))] == ["uma frase sem ponto"]


def test_sentencas_devolvem_offsets_absolutos_na_janela():
    inicio = TEXTO.index("Segundo")
    fim = TEXTO.index("curto")
    for i, f in sentencas(TEXTO, inicio, fim):
        assert inicio <= i < f <= fim
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/knowledge/pipeline/test_segmentar.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'forge.knowledge.pipeline.segmentar'`.

- [ ] **Step 3: Write the implementation**

Create `src/forge/knowledge/pipeline/segmentar.py`:

```python
"""Parágrafos e sentenças como intervalos de offset no texto do documento.

Nada aqui devolve string nova: só (inicio, fim). É o que garante que o texto de
um chunk é sempre uma fatia exata do original — citação nunca é reconstruída.

Parágrafo curto demais (índice, número de página solto, artefato de EPUB) é
mesclado no seguinte em vez de virar chunk próprio.
"""
import re

_QUEBRA_PARAGRAFO = re.compile(r"\n[ \t]*\n")

# Fim de sentença: pontuação final, aspas/parênteses opcionais, espaço, e
# próxima frase começando em maiúscula ou aspas.
_FIM_SENTENCA = re.compile(r'(?<=[.!?])["\')\]]*\s+(?=["\'(\[]*[A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇ])')

# Abreviações que terminam em ponto sem terminar a sentença.
_ABREVIACOES = (
    "sr.", "sra.", "dr.", "dra.", "prof.", "profa.", "st.", "ed.", "org.",
    "trad.", "cf.", "op.", "cit.", "p.", "pp.", "vol.", "n.", "etc.",
)


def _aparar(texto: str, inicio: int, fim: int) -> tuple[int, int] | None:
    """Encolhe o intervalo até remover espaço nas pontas. None se sobrar vazio."""
    while inicio < fim and texto[inicio].isspace():
        inicio += 1
    while fim > inicio and texto[fim - 1].isspace():
        fim -= 1
    return (inicio, fim) if fim > inicio else None


def paragrafos(
    texto: str, inicio: int, fim: int, *, min_chars: int = 40
) -> list[tuple[int, int]]:
    janela = texto[inicio:fim]
    cortes: list[tuple[int, int]] = []
    posicao = 0
    for quebra in _QUEBRA_PARAGRAFO.finditer(janela):
        cortes.append((posicao, quebra.start()))
        posicao = quebra.end()
    cortes.append((posicao, len(janela)))

    aparados = [
        aparado
        for corte in cortes
        if (aparado := _aparar(janela, corte[0], corte[1])) is not None
    ]
    if not aparados:
        return []

    # Mescla curto no seguinte; o último, se curto, se funde no anterior.
    mesclados: list[tuple[int, int]] = []
    pendente: int | None = None
    for indice, (i, f) in enumerate(aparados):
        comeco = pendente if pendente is not None else i
        ultimo = indice == len(aparados) - 1
        if f - comeco < min_chars and not ultimo:
            pendente = comeco
            continue
        if f - comeco < min_chars and mesclados:
            anterior_i, _ = mesclados.pop()
            mesclados.append((anterior_i, f))
        else:
            mesclados.append((comeco, f))
        pendente = None

    return [(inicio + i, inicio + f) for i, f in mesclados]


def _termina_em_abreviacao(trecho: str) -> bool:
    ultima = trecho.rsplit(maxsplit=1)[-1].lower() if trecho.split() else ""
    return ultima in _ABREVIACOES


def sentencas(texto: str, inicio: int, fim: int) -> list[tuple[int, int]]:
    janela = texto[inicio:fim]
    limites: list[int] = [0]
    for corte in _FIM_SENTENCA.finditer(janela):
        if _termina_em_abreviacao(janela[limites[-1]:corte.start()]):
            continue
        limites.append(corte.end())
    limites.append(len(janela))

    resultado: list[tuple[int, int]] = []
    for i, f in zip(limites, limites[1:]):
        aparado = _aparar(janela, i, f)
        if aparado is not None:
            resultado.append((inicio + aparado[0], inicio + aparado[1]))
    return resultado
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/knowledge/pipeline/test_segmentar.py -v`
Expected: 8 passed.

- [ ] **Step 5: Checkpoint (no commit)**

Run: `uv run pytest tests/knowledge -v`
Expected: PASS.

---

### Task 6: Montagem da árvore estrutural

**Files:**
- Create: `src/forge/knowledge/pipeline/arvore.py`
- Test: `tests/knowledge/pipeline/test_arvore.py`

**Interfaces:**
- Consumes: `Chunk`, `Nivel`, `id_de_chunk`, `caminho_filho` (Task 1); `TextoExtraido`, `Marca`, `pagina_de_offset` (Task 2); `paragrafos`, `sentencas` (Task 5).
- Produces:
  - `construir_arvore(documento_id: str, extraido: TextoExtraido, *, paragrafo_min_chars: int = 40) -> list[Chunk]`
  - `texto_de(documento_texto: str, chunk: Chunk) -> str`

  Contrato: lista em pré-ordem, raiz primeiro. Raiz é `nivel="livro"`, `caminho="0001"`, `pai_id=None`. Só `nivel="paragrafo"` tem `texto` preenchido.

- [ ] **Step 1: Write the failing test**

Create `tests/knowledge/pipeline/test_arvore.py`:

```python
from forge.knowledge.pipeline.arvore import construir_arvore, texto_de
from forge.knowledge.sources.extract.texto import extrair_texto

LIVRO = """# Capítulo 1

Primeiro parágrafo do capítulo um, longo o suficiente para virar chunk próprio.

Segundo parágrafo do capítulo um, também com tamanho adequado para sobreviver.

## Seção 1.1

Parágrafo dentro da seção, com comprimento suficiente para não ser mesclado.

# Capítulo 2

Parágrafo do capítulo dois, escrito com folga para passar do mínimo exigido.
"""


def arvore():
    return construir_arvore("doc-1", extrair_texto(LIVRO))


def por_nivel(chunks, nivel):
    return [c for c in chunks if c.nivel == nivel]


def test_raiz_e_o_livro_inteiro_sem_pai():
    raiz = arvore()[0]
    assert raiz.nivel == "livro"
    assert raiz.pai_id is None
    assert raiz.caminho == "0001"
    assert (raiz.offset_inicio, raiz.offset_fim) == (0, len(LIVRO))


def test_capitulos_penduram_na_raiz():
    chunks = arvore()
    raiz = chunks[0]
    capitulos = por_nivel(chunks, "capitulo")
    assert [c.titulo for c in capitulos] == ["Capítulo 1", "Capítulo 2"]
    assert all(c.pai_id == raiz.id for c in capitulos)


def test_subnivel_pendura_no_capitulo_e_nao_na_raiz():
    chunks = arvore()
    capitulo_um = next(c for c in chunks if c.titulo == "Capítulo 1")
    secao = next(c for c in chunks if c.titulo == "Seção 1.1")
    assert secao.nivel == "subcapitulo"
    assert secao.pai_id == capitulo_um.id
    assert secao.caminho.startswith(capitulo_um.caminho + ".")


def test_paragrafo_tem_texto_e_demais_niveis_nao():
    chunks = arvore()
    assert all(c.texto for c in por_nivel(chunks, "paragrafo"))
    assert all(c.texto is None for c in chunks if c.nivel != "paragrafo")


def test_sentencas_penduram_no_paragrafo():
    chunks = arvore()
    paragrafo = por_nivel(chunks, "paragrafo")[0]
    filhas = [c for c in chunks if c.pai_id == paragrafo.id]
    assert filhas
    assert all(c.nivel == "sentenca" for c in filhas)


def test_texto_de_reconstroi_qualquer_nivel_por_offset():
    chunks = arvore()
    capitulo = next(c for c in chunks if c.titulo == "Capítulo 2")
    assert "Parágrafo do capítulo dois" in texto_de(LIVRO, capitulo)


def test_fidelidade_paragrafos_reproduzem_o_original_na_ordem():
    chunks = arvore()
    trechos = [c.texto for c in por_nivel(chunks, "paragrafo")]
    posicao = 0
    for trecho in trechos:
        posicao = LIVRO.index(trecho, posicao)
        posicao += len(trecho)


def folhas_e_sentencas(chunks):
    return {c.id for c in chunks if c.nivel in {"paragrafo", "sentenca"}}


def test_estabilidade_insercao_no_meio_preserva_ids_das_folhas():
    """Propriedade que sustenta o acúmulo semântico: a anotação de K2-K4 vive
    sobre parágrafo e sentença, e essas têm que sobreviver à reingestão.

    Nó contêiner (raiz, capítulo) muda de id de propósito: o texto dele é o
    intervalo inteiro, que de fato passou a incluir o parágrafo novo.
    """
    antes = folhas_e_sentencas(arvore())
    alterado = LIVRO.replace(
        "# Capítulo 2",
        "Parágrafo novo inserido no meio do livro, com tamanho mais que suficiente.\n\n# Capítulo 2",
    )
    depois = folhas_e_sentencas(construir_arvore("doc-1", extrair_texto(alterado)))
    assert antes <= depois


def test_caminho_nao_colide_entre_secao_e_paragrafo_do_mesmo_pai():
    com_prefacio = "Prefácio longo o bastante para virar parágrafo próprio aqui.\n\n" + LIVRO
    chunks = construir_arvore("doc-1", extrair_texto(com_prefacio))
    raiz = chunks[0]
    filhos = [c for c in chunks if c.pai_id == raiz.id]
    assert len({c.caminho for c in filhos}) == len(filhos)


def test_texto_repetido_no_mesmo_documento_gera_ids_distintos():
    repetido = (
        "Mesmo parágrafo repetido duas vezes no livro para testar ocorrência.\n\n"
        "Mesmo parágrafo repetido duas vezes no livro para testar ocorrência.\n"
    )
    chunks = construir_arvore("doc-1", extrair_texto(repetido))
    paragrafos_ = por_nivel(chunks, "paragrafo")
    assert len(paragrafos_) == 2
    assert paragrafos_[0].id != paragrafos_[1].id


def test_documento_sem_cabecalho_pendura_paragrafos_direto_na_raiz():
    plano = (
        "Parágrafo um sem nenhum cabeçalho, longo o bastante para virar chunk.\n\n"
        "Parágrafo dois sem nenhum cabeçalho, também com tamanho adequado aqui.\n"
    )
    chunks = construir_arvore("doc-1", extrair_texto(plano))
    raiz = chunks[0]
    assert not [c for c in chunks if c.nivel in {"capitulo", "subcapitulo", "secao"}]
    assert all(c.pai_id == raiz.id for c in chunks if c.nivel == "paragrafo")


def test_pagina_e_propagada_quando_a_extracao_tem_paginas():
    from forge.knowledge.sources.extract.pdf import montar_paginas
    from forge.knowledge.sources.extract.tipos import TextoExtraido

    texto, offsets = montar_paginas([
        "Parágrafo da primeira página, com comprimento acima do mínimo exigido.",
        "Parágrafo da segunda página, também com comprimento acima do mínimo.",
    ])
    chunks = construir_arvore("doc-1", TextoExtraido(texto=texto, paginas=offsets))
    paginas = [c.pagina for c in chunks if c.nivel == "paragrafo"]
    assert paginas == [1, 2]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/knowledge/pipeline/test_arvore.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'forge.knowledge.pipeline.arvore'`.

- [ ] **Step 3: Write the implementation**

Create `src/forge/knowledge/pipeline/arvore.py`:

```python
"""Marcas + segmentação -> árvore estrutural de Chunks.

Determinística, sem LLM. A árvore é a fonte da verdade estrutural: ela existe
independentemente de qualquer análise semântica e sobrevive a troca de modelo.

Só a folha-parágrafo guarda `texto`. Os outros níveis guardam offsets e derivam
o texto de `documentos.texto` via `texto_de` — evita guardar o livro inteiro
quatro vezes e alinha o índice léxico à granularidade do embedding.
"""
from forge.infrastructure.logging import get_logger
from forge.knowledge.domain.models import (
    NIVEL_FOLHA,
    Chunk,
    Nivel,
    caminho_filho,
    id_de_chunk,
)
from forge.knowledge.pipeline.segmentar import paragrafos, sentencas
from forge.knowledge.sources.extract.tipos import Marca, TextoExtraido, pagina_de_offset

logger = get_logger(__name__)

# Marca nível 1 vira capítulo, 2 vira subcapítulo, 3+ vira seção.
_NIVEL_DE_MARCA: dict[int, Nivel] = {1: "capitulo", 2: "subcapitulo"}


def _nivel_estrutural(nivel_marca: int) -> Nivel:
    return _NIVEL_DE_MARCA.get(nivel_marca, "secao")


def texto_de(documento_texto: str, chunk: Chunk) -> str:
    """Texto de qualquer nó, por offset. Para parágrafo é igual a `chunk.texto`."""
    return documento_texto[chunk.offset_inicio:chunk.offset_fim]


class _Construtor:
    def __init__(self, documento_id: str, extraido: TextoExtraido, min_chars: int):
        self.documento_id = documento_id
        self.texto = extraido.texto
        self.paginas = extraido.paginas
        self.min_chars = min_chars
        self.chunks: list[Chunk] = []
        self.ocorrencias: dict[str, int] = {}
        # Ordem do próximo filho, por pai. Um mesmo pai recebe capítulos e
        # parágrafos soltos (prefácio); se cada laço contasse do 1, dois filhos
        # diferentes acabariam com o mesmo caminho materializado.
        self.contadores: dict[str, int] = {}

    def _proxima_ordem(self, pai: Chunk) -> int:
        ordem = self.contadores.get(pai.id, 0) + 1
        self.contadores[pai.id] = ordem
        return ordem

    def _novo(
        self, *, nivel: Nivel, caminho: str, ordem: int, pai_id: str | None,
        inicio: int, fim: int, titulo: str | None = None,
    ) -> Chunk:
        conteudo = self.texto[inicio:fim]
        ocorrencia = self.ocorrencias.get(conteudo, 0)
        self.ocorrencias[conteudo] = ocorrencia + 1
        chunk = Chunk(
            id=id_de_chunk(self.documento_id, conteudo, ocorrencia),
            documento_id=self.documento_id,
            pai_id=pai_id,
            nivel=nivel,
            caminho=caminho,
            ordem=ordem,
            titulo=titulo,
            texto=conteudo if nivel == NIVEL_FOLHA else None,
            pagina=pagina_de_offset(self.paginas, inicio),
            offset_inicio=inicio,
            offset_fim=fim,
        )
        self.chunks.append(chunk)
        return chunk

    def _folhas(self, pai: Chunk, inicio: int, fim: int) -> None:
        """Parágrafos do intervalo e as sentenças de cada um."""
        for p_inicio, p_fim in paragrafos(
            self.texto, inicio, fim, min_chars=self.min_chars
        ):
            ordem = self._proxima_ordem(pai)
            paragrafo = self._novo(
                nivel=NIVEL_FOLHA, caminho=caminho_filho(pai.caminho, ordem),
                ordem=ordem, pai_id=pai.id, inicio=p_inicio, fim=p_fim,
            )
            for s_inicio, s_fim in sentencas(self.texto, p_inicio, p_fim):
                s_ordem = self._proxima_ordem(paragrafo)
                self._novo(
                    nivel="sentenca",
                    caminho=caminho_filho(paragrafo.caminho, s_ordem),
                    ordem=s_ordem, pai_id=paragrafo.id,
                    inicio=s_inicio, fim=s_fim,
                )


def _fim_da_marca(marcas: list[Marca], indice: int, limite: int) -> int:
    """Uma marca vai até a próxima de nível igual ou mais alto."""
    atual = marcas[indice]
    for seguinte in marcas[indice + 1:]:
        if seguinte.nivel <= atual.nivel:
            return seguinte.offset
    return limite


def construir_arvore(
    documento_id: str, extraido: TextoExtraido, *, paragrafo_min_chars: int = 40
) -> list[Chunk]:
    construtor = _Construtor(documento_id, extraido, paragrafo_min_chars)
    texto = extraido.texto
    marcas = sorted(extraido.marcas, key=lambda m: m.offset)

    raiz = construtor._novo(
        nivel="livro", caminho=caminho_filho("", 1), ordem=1,
        pai_id=None, inicio=0, fim=len(texto),
    )

    if not marcas:
        construtor._folhas(raiz, 0, len(texto))
        logger.info("Árvore montada", doc=documento_id, nos=len(construtor.chunks), marcas=0)
        return construtor.chunks

    # Texto antes do primeiro cabeçalho (prefácio, epígrafe) pendura na raiz.
    if marcas[0].offset > 0:
        construtor._folhas(raiz, 0, marcas[0].offset)

    # Pilha de (nivel_da_marca, chunk) para achar o pai correto de cada marca.
    pilha: list[tuple[int, Chunk]] = [(0, raiz)]
    for indice, marca in enumerate(marcas):
        while len(pilha) > 1 and pilha[-1][0] >= marca.nivel:
            pilha.pop()
        _, pai = pilha[-1]

        ordem = construtor._proxima_ordem(pai)
        fim = _fim_da_marca(marcas, indice, len(texto))
        no = construtor._novo(
            nivel=_nivel_estrutural(marca.nivel),
            caminho=caminho_filho(pai.caminho, ordem),
            ordem=ordem, pai_id=pai.id, inicio=marca.offset, fim=fim,
            titulo=marca.titulo,
        )
        pilha.append((marca.nivel, no))

        # Corpo próprio da marca: do fim do cabeçalho até o próximo cabeçalho,
        # seja qual for o nível dele.
        proximo = marcas[indice + 1].offset if indice + 1 < len(marcas) else len(texto)
        corpo_inicio = marca.offset + marca.comprimento
        if proximo > corpo_inicio:
            construtor._folhas(no, corpo_inicio, proximo)

    logger.info(
        "Árvore montada", doc=documento_id,
        nos=len(construtor.chunks), marcas=len(marcas),
    )
    return construtor.chunks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/knowledge/pipeline/test_arvore.py -v`
Expected: 12 passed.

- [ ] **Step 5: Checkpoint (no commit)**

Run: `uv run pytest tests/knowledge -v`
Expected: PASS.

---

### Task 7: `book.py` produz Documento de Nível 1

**Files:**
- Modify: `src/forge/knowledge/sources/book.py`
- Test: `tests/knowledge/sources/test_book.py`

**Interfaces:**
- Consumes: `Documento`, `Proveniencia`, `hash_texto`, `id_deterministico` (Task 1); `extrair_arquivo`, `TextoExtraido`, `EXTENSOES_SUPORTADAS` (Task 2).
- Produces: `carregar_livro(path: Path, *, ocr_enabled: bool = False) -> tuple[Documento, TextoExtraido]`, `EXTENSOES_SUPORTADAS`.

- [ ] **Step 1: Write the failing test**

Create `tests/knowledge/sources/test_book.py`:

```python
import pytest

from forge.knowledge.domain.models import hash_texto
from forge.knowledge.sources.book import carregar_livro

CORPO = "# Capítulo 1\n\nParágrafo com tamanho suficiente para virar chunk próprio.\n"


def escrever(tmp_path, nome, corpo=CORPO):
    caminho = tmp_path / nome
    caminho.write_text(corpo, encoding="utf-8")
    return caminho


def test_documento_guarda_o_texto_integro_e_seu_hash(tmp_path):
    doc, _ = carregar_livro(escrever(tmp_path, "etica.md"))
    assert doc.texto == CORPO
    assert doc.hash_sha256 == hash_texto(CORPO)


def test_id_vem_do_hash_e_nao_do_nome_do_arquivo(tmp_path):
    doc_a, _ = carregar_livro(escrever(tmp_path, "etica.md"))
    doc_b, _ = carregar_livro(escrever(tmp_path, "outro-nome.md"))
    assert doc_a.id == doc_b.id


def test_conteudo_diferente_gera_documento_diferente(tmp_path):
    doc_a, _ = carregar_livro(escrever(tmp_path, "a.md"))
    doc_b, _ = carregar_livro(escrever(tmp_path, "b.md", CORPO + "\nmais texto aqui.\n"))
    assert doc_a.id != doc_b.id


def test_chave_externa_de_livro_local_e_o_nome_do_arquivo(tmp_path):
    doc, _ = carregar_livro(escrever(tmp_path, "etica.md"))
    assert doc.chave_externa == "arquivo::etica.md"


def test_devolve_a_extracao_com_as_marcas_detectadas(tmp_path):
    _, extraido = carregar_livro(escrever(tmp_path, "etica.md"))
    assert extraido.texto == CORPO
    assert [m.titulo for m in extraido.marcas] == ["Capítulo 1"]


def test_proveniencia_e_de_livro_com_autoridade_maxima(tmp_path):
    doc, _ = carregar_livro(escrever(tmp_path, "etica.md"))
    assert doc.proveniencia.tipo == "livro"
    assert doc.proveniencia.autoridade == 1.0
    assert doc.proveniencia.fonte == "etica.md"


def test_formato_nao_suportado_falha_com_mensagem_explicita(tmp_path):
    caminho = tmp_path / "arquivo.docx"
    caminho.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="não suportado"):
        carregar_livro(caminho)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/knowledge/sources/test_book.py -v`
Expected: FAIL — `carregar_livro` devolve um `Documento`, não uma tupla, e `Documento` não tem `hash_sha256`.

- [ ] **Step 3: Write the implementation**

Replace the whole of `src/forge/knowledge/sources/book.py`:

```python
"""Arquivo de livro -> (Documento de Nível 1, TextoExtraido).

Responsabilidade única: montar o registro do documento original. A extração por
formato é de `sources.extract`; a árvore é de `pipeline.arvore`. Aqui não se
interpreta estrutura nenhuma.

O id vem do hash do texto, não do nome do arquivo: renomear um livro não pode
criar um documento duplicado na base.
"""
from pathlib import Path

from forge.infrastructure.logging import get_logger
from forge.knowledge.domain.models import (
    Documento,
    Proveniencia,
    hash_texto,
    id_deterministico,
)
from forge.knowledge.sources.extract import (
    EXTENSOES_SUPORTADAS,
    TextoExtraido,
    extrair_arquivo,
)

logger = get_logger(__name__)

__all__ = ["EXTENSOES_SUPORTADAS", "carregar_livro"]


def carregar_livro(
    path: Path, *, ocr_enabled: bool = False
) -> tuple[Documento, TextoExtraido]:
    path = Path(path)
    extraido = extrair_arquivo(path, ocr_enabled=ocr_enabled)
    digest = hash_texto(extraido.texto)

    doc = Documento(
        id=id_deterministico("documento", digest),
        hash_sha256=digest,
        titulo=path.stem,
        texto=extraido.texto,
        proveniencia=Proveniencia.de_livro(fonte=path.name, idioma=extraido.idioma),
        chave_externa=f"arquivo::{path.name}",
    )
    logger.info("Livro carregado", fonte=path.name, chars=len(extraido.texto), doc=doc.id)
    return doc, extraido
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/knowledge/sources/test_book.py -v`
Expected: 7 passed.

- [ ] **Step 5: Checkpoint (no commit)**

Run: `uv run pytest tests/knowledge -v`
Expected: PASS.

---

### Task 8: Schema Postgres dos dois níveis

**Files:**
- Modify: `src/forge/knowledge/stores/catalog.py`
- Test: `tests/knowledge/stores/__init__.py` (vazio), `tests/knowledge/stores/test_catalog.py`

**Interfaces:**
- Consumes: `Chunk`, `Documento` (Task 1).
- Produces: `linha_documento(doc) -> dict`, `linha_chunk(chunk) -> dict`, `CatalogStore` com `garantir_schema()`, `upsert_documento(doc)`, `upsert_chunks(chunks)`, `existe_chave_externa(chave) -> bool`, `resetar()`, `contar_chunks() -> int`, `close()`.

- [ ] **Step 1: Write the failing test**

Create `tests/knowledge/stores/__init__.py` (empty) and `tests/knowledge/stores/test_catalog.py`:

```python
from forge.knowledge.domain.models import Chunk, Documento, Proveniencia, hash_texto
from forge.knowledge.stores.catalog import _SCHEMA, linha_chunk, linha_documento


def documento():
    return Documento(
        id="doc-1", hash_sha256=hash_texto("corpo"), titulo="Ética", texto="corpo",
        chave_externa="gutenberg::1234",
        proveniencia=Proveniencia.de_livro(
            fonte="etica.pdf", autor="Espinosa", obra="Ética", edicao="2ª",
            isbn="978-85", licenca="domínio público", idioma="pt",
            data_publicacao="1677",
        ),
    )


def test_linha_documento_leva_o_texto_integro_e_o_hash():
    linha = linha_documento(documento())
    assert linha["texto"] == "corpo"
    assert linha["hash_sha256"] == hash_texto("corpo")


def test_linha_documento_achata_toda_a_proveniencia_de_nivel_1():
    linha = linha_documento(documento())
    for campo in ("autor", "obra", "edicao", "isbn", "licenca", "idioma",
                  "data_publicacao", "url", "fonte", "tipo", "autoridade"):
        assert campo in linha
    assert linha["autor"] == "Espinosa"
    assert linha["chave_externa"] == "gutenberg::1234"


def test_linha_chunk_leva_a_estrutura_e_nao_a_proveniencia():
    chunk = Chunk(
        id="c-1", documento_id="doc-1", pai_id="c-0", nivel="paragrafo",
        caminho="0001.0002", ordem=2, titulo=None, texto="trecho",
        pagina=3, offset_inicio=10, offset_fim=16,
    )
    linha = linha_chunk(chunk)
    assert linha == {
        "id": "c-1", "documento_id": "doc-1", "pai_id": "c-0",
        "nivel": "paragrafo", "caminho": "0001.0002", "ordem": 2,
        "titulo": None, "texto": "trecho", "pagina": 3,
        "offset_inicio": 10, "offset_fim": 16,
    }


def test_schema_indexa_tsvector_por_idioma_e_nao_fixo_em_portugues():
    assert "CASE" in _SCHEMA
    assert "'english'" in _SCHEMA
    assert "'portuguese'" in _SCHEMA


def test_schema_tem_indice_unico_de_chave_externa_para_dedup_pre_download():
    assert "chave_externa" in _SCHEMA
    assert "UNIQUE" in _SCHEMA


def test_schema_liga_chunk_ao_pai_e_indexa_o_caminho():
    assert "pai_id" in _SCHEMA
    assert "chunks_caminho_idx" in _SCHEMA
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/knowledge/stores/test_catalog.py -v`
Expected: FAIL — `linha_documento` não tem `texto`/`hash_sha256`, `_SCHEMA` não tem `CASE`.

- [ ] **Step 3: Write the implementation**

Replace the whole of `src/forge/knowledge/stores/catalog.py`:

```python
"""Postgres: Nível 1 (documento original) + Nível 2 (árvore estrutural).

`tsvector` é gerado com o stemmer do idioma do documento. `CASE` com configs
literais é IMMUTABLE, que é o que uma generated column exige — passar o idioma
como coluna castada para regconfig não é.

Só o nível `paragrafo` tem `texto`: os outros derivam de `documentos.texto` pelos
offsets. Isso evita guardar o livro inteiro uma vez por nível e alinha o índice
léxico à granularidade do embedding.

`linha_documento` e `linha_chunk` são puras e testáveis sem servidor.
"""
from forge.infrastructure.logging import get_logger
from forge.knowledge.domain.models import Chunk, Documento

logger = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documentos (
    id               TEXT PRIMARY KEY,
    hash_sha256      TEXT NOT NULL,
    chave_externa    TEXT,
    titulo           TEXT NOT NULL,
    texto            TEXT NOT NULL,
    tipo             TEXT NOT NULL,
    fonte            TEXT NOT NULL,
    autor            TEXT,
    obra             TEXT,
    edicao           TEXT,
    isbn             TEXT,
    licenca          TEXT,
    url              TEXT,
    idioma           TEXT,
    data_publicacao  TEXT,
    data_ingestao    TIMESTAMPTZ NOT NULL DEFAULT now(),
    autoridade       REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS documentos_chave_externa_idx
    ON documentos (chave_externa) WHERE chave_externa IS NOT NULL;

CREATE TABLE IF NOT EXISTS chunks (
    id             TEXT PRIMARY KEY,
    documento_id   TEXT NOT NULL REFERENCES documentos(id) ON DELETE CASCADE,
    pai_id         TEXT,
    nivel          TEXT NOT NULL,
    caminho        TEXT NOT NULL,
    ordem          INT  NOT NULL,
    titulo         TEXT,
    texto          TEXT,
    pagina         INT,
    offset_inicio  INT  NOT NULL,
    offset_fim     INT  NOT NULL,
    idioma         TEXT,
    tsv            tsvector GENERATED ALWAYS AS (
        CASE idioma
            WHEN 'en' THEN to_tsvector('english', coalesce(texto, ''))
            ELSE to_tsvector('portuguese', coalesce(texto, ''))
        END
    ) STORED
);
CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON chunks USING GIN (tsv);
CREATE INDEX IF NOT EXISTS chunks_caminho_idx ON chunks (documento_id, caminho);
CREATE INDEX IF NOT EXISTS chunks_pai_idx ON chunks (pai_id);
"""

_UPSERT_DOC = """
INSERT INTO documentos (
    id, hash_sha256, chave_externa, titulo, texto, tipo, fonte, autor, obra,
    edicao, isbn, licenca, url, idioma, data_publicacao, autoridade
) VALUES (
    %(id)s, %(hash_sha256)s, %(chave_externa)s, %(titulo)s, %(texto)s, %(tipo)s,
    %(fonte)s, %(autor)s, %(obra)s, %(edicao)s, %(isbn)s, %(licenca)s, %(url)s,
    %(idioma)s, %(data_publicacao)s, %(autoridade)s
)
ON CONFLICT (id) DO UPDATE SET
    titulo = EXCLUDED.titulo,
    texto = EXCLUDED.texto,
    hash_sha256 = EXCLUDED.hash_sha256,
    autoridade = EXCLUDED.autoridade,
    chave_externa = EXCLUDED.chave_externa
"""

_UPSERT_CHUNK = """
INSERT INTO chunks (
    id, documento_id, pai_id, nivel, caminho, ordem, titulo, texto, pagina,
    offset_inicio, offset_fim, idioma
) VALUES (
    %(id)s, %(documento_id)s, %(pai_id)s, %(nivel)s, %(caminho)s, %(ordem)s,
    %(titulo)s, %(texto)s, %(pagina)s, %(offset_inicio)s, %(offset_fim)s, %(idioma)s
)
ON CONFLICT (id) DO UPDATE SET
    pai_id = EXCLUDED.pai_id,
    caminho = EXCLUDED.caminho,
    ordem = EXCLUDED.ordem,
    pagina = EXCLUDED.pagina,
    offset_inicio = EXCLUDED.offset_inicio,
    offset_fim = EXCLUDED.offset_fim
"""


def linha_documento(doc: Documento) -> dict:
    p = doc.proveniencia
    return {
        "id": doc.id, "hash_sha256": doc.hash_sha256,
        "chave_externa": doc.chave_externa, "titulo": doc.titulo, "texto": doc.texto,
        "tipo": p.tipo, "fonte": p.fonte, "autor": p.autor, "obra": p.obra,
        "edicao": p.edicao, "isbn": p.isbn, "licenca": p.licenca, "url": p.url,
        "idioma": p.idioma, "data_publicacao": p.data_publicacao,
        "autoridade": p.autoridade,
    }


def linha_chunk(chunk: Chunk) -> dict:
    return {
        "id": chunk.id, "documento_id": chunk.documento_id, "pai_id": chunk.pai_id,
        "nivel": chunk.nivel, "caminho": chunk.caminho, "ordem": chunk.ordem,
        "titulo": chunk.titulo, "texto": chunk.texto, "pagina": chunk.pagina,
        "offset_inicio": chunk.offset_inicio, "offset_fim": chunk.offset_fim,
    }


class CatalogStore:
    def __init__(self, dsn: str):
        import psycopg

        self._conn = psycopg.connect(dsn, autocommit=True)

    def garantir_schema(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute(_SCHEMA)
        logger.info("Schema Postgres garantido")

    def resetar(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS chunks, documentos CASCADE")
        logger.warning("Tabelas do catálogo removidas")
        self.garantir_schema()

    def upsert_documento(self, doc: Documento) -> None:
        with self._conn.cursor() as cur:
            cur.execute(_UPSERT_DOC, linha_documento(doc))

    def upsert_chunks(self, chunks: list[Chunk], *, idioma: str | None = None) -> int:
        if not chunks:
            return 0
        linhas = [{**linha_chunk(c), "idioma": idioma} for c in chunks]
        with self._conn.cursor() as cur:
            cur.executemany(_UPSERT_CHUNK, linhas)
        return len(chunks)

    def existe_chave_externa(self, chave: str) -> bool:
        """Dedup antes do download: a chave é conhecida pela referência da fonte,
        o hash só depois de baixar."""
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM documentos WHERE chave_externa = %(c)s", {"c": chave}
            )
            return cur.fetchone() is not None

    def contar_chunks(self) -> int:
        with self._conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM chunks")
            return cur.fetchone()[0]

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/knowledge/stores/test_catalog.py -v`
Expected: 6 passed.

- [ ] **Step 5: Checkpoint (no commit)**

Run: `uv run pytest tests/knowledge -v`
Expected: PASS.

---

### Task 9: Qdrant indexa só as folhas-parágrafo

**Files:**
- Modify: `src/forge/knowledge/stores/vector.py`
- Modify: `src/forge/knowledge/stores/graph.py`
- Test: `tests/knowledge/stores/test_vector.py`

**Interfaces:**
- Consumes: `Chunk`, `Documento` (Task 1).
- Produces: `_payload(doc: Documento, chunk: Chunk) -> dict`, `VectorStore.upsert_chunks(doc, chunks)`, `VectorStore.resetar()`, `GraphStore.params_documento(documento_id, entidades, relacionamentos)` (assinatura nova), `GraphStore.resetar()`.

- [ ] **Step 1: Write the failing test**

Create `tests/knowledge/stores/test_vector.py`:

```python
from forge.knowledge.domain.models import Chunk, Documento, Proveniencia, hash_texto
from forge.knowledge.stores.vector import _payload, pontos_de

DOC = Documento(
    id="doc-1", hash_sha256=hash_texto("corpo"), titulo="Ética", texto="corpo",
    proveniencia=Proveniencia.de_livro(
        fonte="etica.pdf", autor="Espinosa", obra="Ética", idioma="pt"
    ),
)


def chunk(nivel, cid="c-1", embedding=None, texto="trecho"):
    return Chunk(
        id=cid, documento_id="doc-1", pai_id="c-0", nivel=nivel,
        caminho="0001.0002", ordem=2, texto=texto, pagina=7,
        offset_inicio=0, offset_fim=6, embedding=embedding,
    )


def test_payload_carrega_estrutura_e_proveniencia_para_citar_sem_ir_ao_postgres():
    p = _payload(DOC, chunk("paragrafo"))
    assert p["documento_id"] == "doc-1"
    assert p["pai_id"] == "c-0"
    assert p["caminho"] == "0001.0002"
    assert p["pagina"] == 7
    assert p["autor"] == "Espinosa"
    assert p["obra"] == "Ética"
    assert p["autoridade"] == 1.0
    assert p["texto"] == "trecho"


def test_so_paragrafo_com_embedding_vira_ponto():
    chunks = [
        chunk("livro", cid="raiz", embedding=[0.1]),
        chunk("paragrafo", cid="par", embedding=[0.1]),
        chunk("sentenca", cid="sen", embedding=[0.1]),
    ]
    assert [p.id for p in pontos_de(DOC, chunks)] == ["par"]


def test_paragrafo_sem_embedding_e_ignorado():
    assert pontos_de(DOC, [chunk("paragrafo", embedding=None)]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/knowledge/stores/test_vector.py -v`
Expected: FAIL com `ImportError: cannot import name 'pontos_de'`.

- [ ] **Step 3: Write the implementation**

Replace the whole of `src/forge/knowledge/stores/vector.py`:

```python
"""Qdrant: vetores das folhas-parágrafo + payload de estrutura e proveniência.

Só parágrafo vira vetor (small-to-big): o embedding fica preciso e a entrega
sobe pelo `pai_id` para devolver o trecho com o contexto em volta. Sentença,
seção e capítulo não são indexados.

O payload carrega proveniência inteira porque o retriever precisa citar sem uma
segunda ida ao Postgres. `_payload` e `pontos_de` são puros e testáveis sem
servidor.
"""
from forge.infrastructure.logging import get_logger
from forge.knowledge.domain.models import NIVEL_FOLHA, Chunk, Documento

logger = get_logger(__name__)


def _payload(doc: Documento, chunk: Chunk) -> dict:
    p = doc.proveniencia
    return {
        "documento_id": chunk.documento_id,
        "pai_id": chunk.pai_id,
        "nivel": chunk.nivel,
        "caminho": chunk.caminho,
        "ordem": chunk.ordem,
        "texto": chunk.texto,
        "pagina": chunk.pagina,
        "offset_inicio": chunk.offset_inicio,
        "offset_fim": chunk.offset_fim,
        "tipo": p.tipo,
        "fonte": p.fonte,
        "autor": p.autor,
        "obra": p.obra,
        "url": p.url,
        "idioma": p.idioma,
        "data_publicacao": p.data_publicacao,
        "autoridade": p.autoridade,
    }


def pontos_de(doc: Documento, chunks: list[Chunk]) -> list:
    from qdrant_client.models import PointStruct

    return [
        PointStruct(id=c.id, vector=c.embedding, payload=_payload(doc, c))
        for c in chunks
        if c.nivel == NIVEL_FOLHA and c.embedding is not None
    ]


class VectorStore:
    def __init__(self, url: str, collection: str, dim: int):
        from qdrant_client import QdrantClient

        self._cliente = QdrantClient(url=url)
        self._collection = collection
        self._dim = dim

    def garantir_colecao(self) -> None:
        from qdrant_client.models import Distance, VectorParams

        if self._cliente.collection_exists(self._collection):
            return
        self._cliente.create_collection(
            self._collection,
            vectors_config=VectorParams(size=self._dim, distance=Distance.COSINE),
        )
        logger.info("Coleção Qdrant criada", collection=self._collection, dim=self._dim)

    def resetar(self) -> None:
        if self._cliente.collection_exists(self._collection):
            self._cliente.delete_collection(self._collection)
            logger.warning("Coleção Qdrant removida", collection=self._collection)
        self.garantir_colecao()

    def upsert_chunks(self, doc: Documento, chunks: list[Chunk]) -> int:
        pontos = pontos_de(doc, chunks)
        if not pontos:
            return 0
        self._cliente.upsert(self._collection, points=pontos)
        logger.info("Parágrafos no Qdrant", n=len(pontos), doc=doc.id)
        return len(pontos)

    def contar(self) -> int:
        return self._cliente.count(self._collection).count
```

In `src/forge/knowledge/stores/graph.py`, replace `params_documento` and add `resetar`, so the module stops depending on fields `Documento` no longer has:

```python
def params_documento(
    documento_id: str, entidades: list, relacionamentos: list
) -> tuple[list[dict], list[dict]]:
    """Dormente até K3: o grafo semântico só passa a ser escrito lá.

    Recebe listas explícitas em vez de um Documento — a árvore estrutural não
    carrega entidade nem relação, elas são da camada semântica.
    """
    nos = [{"nome": e.nome, "tipo": e.tipo} for e in entidades]
    arestas = [
        {"origem": r.origem, "destino": r.destino, "tipo": r.tipo,
         "documento_id": documento_id}
        for r in relacionamentos
    ]
    return nos, arestas
```

Replace `GraphStore.upsert_documento` with:

```python
    def upsert_semantica(
        self, documento_id: str, entidades: list, relacionamentos: list
    ) -> None:
        """Dormente até K3. Nenhum chamador em K1."""
        nos, arestas = params_documento(documento_id, entidades, relacionamentos)
        with self._driver.session() as s:
            for no in nos:
                s.run(_CYPHER_ENTIDADE, **no)
            for aresta in arestas:
                s.run(_CYPHER_RELACAO, **aresta)
        logger.info("KG atualizado", doc=documento_id, entidades=len(nos), relacoes=len(arestas))

    def resetar(self) -> None:
        with self._driver.session() as s:
            s.run("MATCH (n) DETACH DELETE n")
        logger.warning("Grafo Neo4j esvaziado")
        self.garantir_schema()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/knowledge/stores/test_vector.py -v`
Expected: 3 passed.

- [ ] **Step 5: Checkpoint (no commit)**

Run: `uv run pytest tests/knowledge -v`
Expected: PASS.

---

### Task 10: Pipeline de ingestão sem LLM

**Files:**
- Modify: `src/forge/knowledge/ingest.py`
- Modify: `src/forge/infrastructure/config.py:39-51`
- Test: `tests/knowledge/test_ingest.py`

**Interfaces:**
- Consumes: tudo das Tasks 1, 2, 6, 7, 8, 9.
- Produces:
  - `Stores(vector, graph, catalog)` com `garantir_schema()` e `resetar()`
  - `Entrada = tuple[Documento, TextoExtraido]`
  - `entrada_de_documento(doc: Documento) -> Entrada`
  - `ingerir_entradas(entradas, *, embed_fn, stores, settings) -> int`
  - `ingerir_caminho(caminho, settings) -> int`, `ingerir_resultados_busca(resultados, settings) -> int`, `ingerir_busca_remota(...) -> int`, `resetar_stores(settings) -> None`
  - `KnowledgeSettings.paragrafo_min_chars: int = 40` (substitui `chunk_size`/`chunk_overlap`)

- [ ] **Step 1: Write the failing test**

Create `tests/knowledge/test_ingest.py`:

```python
from forge.infrastructure.config import Settings
from forge.knowledge.domain.models import Documento, Proveniencia, hash_texto
from forge.knowledge.ingest import Stores, entrada_de_documento, ingerir_entradas
from forge.knowledge.sources.extract.texto import extrair_texto

LIVRO = """# Capítulo 1

Primeiro parágrafo do capítulo um, longo o suficiente para virar chunk próprio.

Segundo parágrafo do capítulo um, também com tamanho adequado para sobreviver.

# Capítulo 2

Parágrafo do capítulo dois, escrito com folga para passar do mínimo exigido.
"""


class FakeCatalog:
    def __init__(self):
        self.documentos = []
        self.chunks = []

    def garantir_schema(self):
        pass

    def resetar(self):
        self.documentos.clear()
        self.chunks.clear()

    def upsert_documento(self, doc):
        self.documentos.append(doc)

    def upsert_chunks(self, chunks, *, idioma=None):
        self.chunks.extend(chunks)
        return len(chunks)


class FakeVector:
    def __init__(self):
        self.pontos = []

    def garantir_colecao(self):
        pass

    def resetar(self):
        self.pontos.clear()

    def upsert_chunks(self, doc, chunks):
        indexados = [c for c in chunks if c.nivel == "paragrafo" and c.embedding]
        self.pontos.extend(indexados)
        return len(indexados)


class FakeGraph:
    def __init__(self):
        self.escritas = 0

    def garantir_schema(self):
        pass

    def resetar(self):
        self.escritas = 0


def embed_fake(textos):
    return [[float(len(t)), 1.0, 0.0] for t in textos]


def documento(texto=LIVRO):
    return Documento(
        id="doc-1", hash_sha256=hash_texto(texto), titulo="Livro", texto=texto,
        proveniencia=Proveniencia.de_livro(fonte="livro.md", idioma="pt"),
    )


def montar():
    return Stores(vector=FakeVector(), graph=FakeGraph(), catalog=FakeCatalog())


def ingerir(texto=LIVRO, stores=None):
    stores = stores or montar()
    doc = documento(texto)
    total = ingerir_entradas(
        [(doc, extrair_texto(texto))],
        embed_fn=embed_fake, stores=stores, settings=Settings(),
    )
    return stores, doc, total


def test_ingestao_nao_toca_no_modelo_de_linguagem():
    # `ingerir_entradas` não recebe `model`: se algum estágio tentar usar LLM,
    # a assinatura quebra antes de o teste rodar.
    stores, _, total = ingerir()
    assert total > 0
    assert stores.catalog.documentos


def test_documento_e_persistido_com_texto_integro():
    stores, doc, _ = ingerir()
    assert stores.catalog.documentos[0].texto == LIVRO
    assert stores.catalog.documentos[0].hash_sha256 == doc.hash_sha256


def test_arvore_inteira_vai_para_o_catalogo():
    stores, _, _ = ingerir()
    niveis = {c.nivel for c in stores.catalog.chunks}
    assert {"livro", "capitulo", "paragrafo", "sentenca"} <= niveis


def test_so_paragrafo_e_embedado_e_indexado():
    stores, _, _ = ingerir()
    assert all(c.nivel == "paragrafo" for c in stores.vector.pontos)
    embedados = [c for c in stores.catalog.chunks if c.embedding is not None]
    assert all(c.nivel == "paragrafo" for c in embedados)


def test_grafo_nao_recebe_nada_em_k1():
    stores, _, _ = ingerir()
    assert stores.graph.escritas == 0


def test_fidelidade_paragrafos_recompoem_o_original_em_ordem():
    stores, _, _ = ingerir()
    posicao = 0
    for chunk in [c for c in stores.catalog.chunks if c.nivel == "paragrafo"]:
        posicao = LIVRO.index(chunk.texto, posicao)
        posicao += len(chunk.texto)


def test_estabilidade_reingestao_com_paragrafo_novo_preserva_as_folhas():
    """A anotação semântica de K2-K4 vive sobre parágrafo e sentença. Reingerir
    com um parágrafo a mais não pode invalidar as folhas que já existiam."""
    def folhas(stores):
        return {
            c.id for c in stores.catalog.chunks
            if c.nivel in {"paragrafo", "sentenca"}
        }

    stores_a, _, _ = ingerir()
    alterado = LIVRO.replace(
        "# Capítulo 2",
        "Parágrafo novo no meio do livro, com tamanho mais que suficiente aqui.\n\n# Capítulo 2",
    )
    stores_b, _, _ = ingerir(alterado)
    assert folhas(stores_a) <= folhas(stores_b)


def test_entrada_de_documento_detecta_marcas_de_texto_sem_arquivo():
    doc = documento()
    _, extraido = entrada_de_documento(doc)
    assert extraido.texto == LIVRO
    assert [m.titulo for m in extraido.marcas] == ["Capítulo 1", "Capítulo 2"]
    assert extraido.paginas == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/knowledge/test_ingest.py -v`
Expected: FAIL com `ImportError: cannot import name 'ingerir_entradas'`.

- [ ] **Step 3: Write the implementation**

In `src/forge/infrastructure/config.py`, replace the two chunking lines inside `KnowledgeSettings`:

```python
    ocr_enabled: bool = False
    # Parágrafo abaixo disso é mesclado no seguinte: índice, número de página
    # solto e artefato de EPUB não merecem chunk próprio.
    paragrafo_min_chars: int = 40
```

Replace the whole of `src/forge/knowledge/ingest.py`:

```python
"""Orquestrador de ingestão: fonte -> árvore estrutural -> stores.

Sem LLM. K1 monta os Níveis 1 e 2 de docs/knowledge.md de forma determinística;
a análise semântica é de K2 em diante e escreve no Neo4j, não aqui.

`ingerir_entradas` recebe `embed_fn` e `stores` por injeção — o pipeline inteiro
roda com fakes, sem Docker. As `ingerir_*` de topo montam as dependências reais
a partir de Settings.
"""
from dataclasses import dataclass
from pathlib import Path

from forge.infrastructure.config import Settings
from forge.infrastructure.logging import get_logger
from forge.knowledge.domain.models import NIVEL_FOLHA, Documento
from forge.knowledge.pipeline.arvore import construir_arvore
from forge.knowledge.pipeline.embed import embed_chunks
from forge.knowledge.sources.extract import TextoExtraido, extrair_texto
from forge.knowledge.sources.remote import construir_fontes

logger = get_logger(__name__)

Entrada = tuple[Documento, TextoExtraido]


@dataclass
class Stores:
    """Trio de persistência. Qualquer objeto com a mesma interface serve (fakes)."""
    vector: object
    graph: object
    catalog: object

    def garantir_schema(self) -> None:
        self.catalog.garantir_schema()
        self.vector.garantir_colecao()
        self.graph.garantir_schema()

    def resetar(self) -> None:
        self.catalog.resetar()
        self.vector.resetar()
        self.graph.resetar()


def entrada_de_documento(doc: Documento) -> Entrada:
    """Documento sem arquivo (web, fonte remota): marcas vêm do próprio texto."""
    return doc, extrair_texto(doc.texto)


def ingerir_entradas(
    entradas: list[Entrada], *, embed_fn, stores: Stores, settings: Settings
) -> int:
    k = settings.knowledge
    total = 0
    for doc, extraido in entradas:
        chunks = construir_arvore(
            doc.id, extraido, paragrafo_min_chars=k.paragrafo_min_chars
        )
        folhas = [c for c in chunks if c.nivel == NIVEL_FOLHA]
        embed_chunks(folhas, embed_fn, batch=k.embedding_batch)

        stores.catalog.upsert_documento(doc)
        stores.catalog.upsert_chunks(chunks, idioma=doc.proveniencia.idioma)
        stores.vector.upsert_chunks(doc, chunks)

        total += len(folhas)
        logger.info(
            "Documento ingerido", doc=doc.id, nos=len(chunks),
            paragrafos=len(folhas), chars=len(doc.texto),
        )
    logger.info("Ingestão concluída", documentos=len(entradas), paragrafos=total)
    return total


# --- topo: monta dependências reais a partir de Settings ---------------------

def _montar(settings: Settings) -> tuple[object, Stores]:
    """Sem modelo de linguagem: K1 não faz nenhuma chamada de LLM."""
    from forge.knowledge.pipeline.embed import build_embed_fn, sonda_semantica
    from forge.knowledge.stores.catalog import CatalogStore
    from forge.knowledge.stores.graph import GraphStore
    from forge.knowledge.stores.vector import VectorStore

    embed_fn = build_embed_fn(settings)
    sonda_semantica(embed_fn)  # gate: aborta antes de tocar os stores

    k = settings.knowledge
    stores = Stores(
        vector=VectorStore(k.qdrant_url, k.qdrant_collection, k.embedding_dim),
        graph=GraphStore(k.neo4j_uri, k.neo4j_user, k.neo4j_password),
        catalog=CatalogStore(k.postgres_dsn),
    )
    stores.garantir_schema()
    return embed_fn, stores


def resetar_stores(settings: Settings) -> None:
    """Derruba e recria os três stores. Destrutivo e irreversível."""
    _, stores = _montar(settings)
    stores.resetar()
    logger.warning("Stores resetados")


def ingerir_caminho(caminho: Path, settings: Settings) -> int:
    from forge.knowledge.sources.book import EXTENSOES_SUPORTADAS, carregar_livro

    caminho = Path(caminho)
    arquivos = (
        [p for p in caminho.rglob("*") if p.suffix.lower() in EXTENSOES_SUPORTADAS]
        if caminho.is_dir()
        else [caminho]
    )
    embed_fn, stores = _montar(settings)
    entradas = [
        carregar_livro(p, ocr_enabled=settings.knowledge.ocr_enabled) for p in arquivos
    ]
    return ingerir_entradas(entradas, embed_fn=embed_fn, stores=stores, settings=settings)


def ingerir_resultados_busca(resultados: list[dict], settings: Settings) -> int:
    from forge.knowledge.sources.web import documentos_de_busca

    docs = documentos_de_busca(resultados)
    if not docs:
        return 0
    embed_fn, stores = _montar(settings)
    entradas = [entrada_de_documento(d) for d in docs]
    return ingerir_entradas(entradas, embed_fn=embed_fn, stores=stores, settings=settings)


def ingerir_busca_remota(
    nomes_fontes: list[str],
    query: str,
    settings: Settings,
    *,
    limite: int | None = None,
    sobrescrever: bool = False,
) -> int:
    """Busca por tema nas fontes remotas, baixa e ingere pelo pipeline padrão.

    A dedup pré-download usa `chave_externa` (conhecida pela referência da fonte),
    não o id: o id vem do hash do texto, que só existe depois de baixar.
    """
    from forge.knowledge.sources.remote.base import buscar_e_baixar
    from forge.knowledge.sources.remote.http import Http

    k = settings.knowledge
    limite = limite or k.remote_top_n
    fontes = construir_fontes(nomes_fontes, settings=settings)
    http = Http(cache_dir=k.cache_dir, rate_delay=k.remote_rate_delay, timeout=k.remote_timeout)

    if sobrescrever:
        ja_ingerido = None
    else:
        from forge.knowledge.stores.catalog import CatalogStore

        catalog = CatalogStore(k.postgres_dsn)
        catalog.garantir_schema()
        ja_ingerido = catalog.existe_chave_externa

    # Tradutor só é montado se alguma fonte declara idioma_busca (ex: SEP só-inglês).
    # É a única chamada de LLM que resta na camada, e traduz a query, nunca o conteúdo.
    traduzir_fn = None
    if any(getattr(f, "idioma_busca", None) for f in fontes):
        from forge.knowledge.pipeline.translate import traduzir as _traduzir
        from forge.llms.model import build_chat_model

        model = build_chat_model(settings)
        traduzir_fn = lambda texto, idioma: _traduzir(model, texto, idioma)

    docs = buscar_e_baixar(
        fontes, query, limite=limite, http=http,
        ja_ingerido=ja_ingerido if ja_ingerido is not None else (lambda _c: False),
        max_paginas=k.remote_max_pages,
        traduzir=traduzir_fn,
    )
    if not docs:
        logger.info("Busca remota sem documentos novos", fontes=nomes_fontes, query=query[:60])
        return 0
    embed_fn, stores = _montar(settings)
    entradas = [entrada_de_documento(d) for d in docs]
    return ingerir_entradas(entradas, embed_fn=embed_fn, stores=stores, settings=settings)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/knowledge/test_ingest.py -v`
Expected: 8 passed.

- [ ] **Step 5: Checkpoint (no commit)**

Run: `uv run pytest tests/knowledge -v`
Expected: PASS.

---

### Task 11: Remoções — pipeline antigo, ponte do research, retriever dormente

**Files:**
- Delete: `src/forge/knowledge/pipeline/chunk.py`, `structure.py`, `summarize.py`, `entities.py`, `relations.py`, `concepts.py`
- Delete: `src/forge/knowledge/integration.py`
- Modify: `src/forge/knowledge/retriever/hybrid.py`
- Modify: `src/forge/orchestration/graph.py:65-82`
- Test: `tests/orchestration/test_graph.py`

**Interfaces:**
- Consumes: nada novo.
- Produces: `node_research` deixa de chamar a camada de conhecimento; nenhuma função nova.

Nota: os estágios deletados voltam em K2 com escopo de chunk e prompts diferentes; o texto atual continua no histórico do git.

- [ ] **Step 1: Write the failing test**

Add to `tests/orchestration/test_graph.py`:

```python
def test_research_nao_chama_a_camada_de_conhecimento():
    """Retriever fica dormente até K5: nada no fluxo de roteiro pode tocá-lo."""
    import forge.orchestration.graph as modulo

    fonte = Path(modulo.__file__).read_text(encoding="utf-8")
    assert "knowledge" not in fonte
    assert "consultar_e_aprender" not in fonte
```

Add at the top of the file, if not already present:

```python
from pathlib import Path
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/orchestration/test_graph.py::test_research_nao_chama_a_camada_de_conhecimento -v`
Expected: FAIL — `graph.py` ainda importa `consultar_e_aprender`.

- [ ] **Step 3: Write the implementation**

Delete the files:

```bash
rm src/forge/knowledge/pipeline/chunk.py \
   src/forge/knowledge/pipeline/structure.py \
   src/forge/knowledge/pipeline/summarize.py \
   src/forge/knowledge/pipeline/entities.py \
   src/forge/knowledge/pipeline/relations.py \
   src/forge/knowledge/pipeline/concepts.py \
   src/forge/knowledge/integration.py
```

In `src/forge/orchestration/graph.py`, replace `node_research` (lines 65-82) with:

```python
    def node_research(state):
        pedido = state.get("pedido")
        logger.debug("Starting research phase", tema=state["tema"], reentrada=bool(pedido))
        brief, fontes, raw = research_stage.pesquisar(
            model, state["tema"], settings.provider, pedido
        )
        anterior = state.get("research_notes", "")
        combinado = f"{anterior}\n\n## Verificação dirigida\n\n{brief}".strip() if anterior else brief
        logger.info("Research completed", num_fontes=len(fontes), reentrada=bool(pedido))
        return {
            "research_notes": combinado,
            "fontes": fontes,
            "pedido": None,
            "_raw": raw,
        }
```

At the top of `src/forge/knowledge/retriever/hybrid.py`, replace the module docstring with:

```python
"""DORMENTE ATÉ K5. Nenhum chamador em K1-K4.

Retriever fino: vetorial + léxico com fusão RRF. A fusão RRF está correta e é
reaproveitada em K5 — por isso o módulo fica no repositório em vez de ser
apagado. O resto (query planner, perna de KG, metadados, recência, autoridade,
confiança, re-ranking por cross-encoder) é escopo de K5, depois que K1-K4
tiverem gravado esses sinais.

`retrieve` e `consultar` referenciam o schema anterior a K1 e não funcionam como
estão. Não chame nada daqui antes de K5.
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/orchestration/test_graph.py -v`
Expected: PASS, incluindo o teste novo.

- [ ] **Step 5: Checkpoint (no commit)**

Run: `uv run pytest -v`
Expected: falhas restantes só em `tests/test_cli.py` (comando `buscar` ainda no parser) — corrigido na Task 12. Nenhuma outra falha.

---

### Task 12: CLI — remove `buscar`, adiciona `ingest --reset`

**Files:**
- Modify: `src/forge/cli.py:45-72`, `75-100`, `103-148`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `resetar_stores` (Task 10).
- Produces: `forge ingest --reset [--sim]`; subcomando `buscar` deixa de existir.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
def test_comando_buscar_nao_existe_mais():
    """Retriever dormente até K5."""
    from forge.cli import main

    with pytest.raises(SystemExit):
        main(["buscar", "--query", "virtude"])


def test_reset_exige_confirmacao_e_aborta_quando_negada(monkeypatch, capsys):
    from forge import cli

    chamou = []
    monkeypatch.setattr(cli, "_confirmar_reset", lambda: False)
    monkeypatch.setattr(
        "forge.knowledge.ingest.resetar_stores", lambda s: chamou.append(s)
    )
    assert cli.main(["ingest", "--reset"]) == 1
    assert chamou == []


def test_reset_confirmado_chama_resetar_stores(monkeypatch):
    from forge import cli

    chamou = []
    monkeypatch.setattr(cli, "_confirmar_reset", lambda: True)
    monkeypatch.setattr(
        "forge.knowledge.ingest.resetar_stores", lambda s: chamou.append(s)
    )
    assert cli.main(["ingest", "--reset", "--sim"]) == 0
    assert len(chamou) == 1
```

Add `import pytest` at the top of `tests/test_cli.py` if not already present.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL — `--reset` não existe e `_confirmar_reset` não existe.

- [ ] **Step 3: Write the implementation**

In `src/forge/cli.py`, delete the `b = sub.add_parser("buscar", ...)` block (lines 62-64), the `if args.cmd == "buscar"` branch, and the whole `_cmd_buscar` function.

Add to the `ing` parser:

```python
    ing.add_argument(
        "--reset",
        action="store_true",
        help="APAGA todos os dados dos três stores e recria o schema",
    )
    ing.add_argument(
        "--sim",
        action="store_true",
        help="Pula a confirmação de --reset (para automação)",
    )
```

Add above `_cmd_ingest`:

```python
def _confirmar_reset() -> bool:
    """Confirmação interativa de operação destrutiva.

    --reset apaga Postgres, Qdrant e Neo4j de forma irreversível. Exige que o
    usuário digite a palavra, para que não seja acionado por engano.
    """
    print("--reset APAGA todos os dados de Postgres, Qdrant e Neo4j.")
    print("Esta ação é irreversível.")
    try:
        resposta = input("Digite 'apagar' para confirmar: ")
    except EOFError:
        return False
    return resposta.strip().lower() == "apagar"
```

At the start of `_cmd_ingest`, right after `setup_logging(settings.log_level)`:

```python
    if args.reset:
        from forge.knowledge.ingest import resetar_stores

        if not args.sim and not _confirmar_reset():
            logger.warning("Reset cancelado pelo usuário")
            print("cancelado")
            return 1
        try:
            resetar_stores(settings)
        except Exception as e:
            logger.error("Reset falhou", error=str(e), exc_info=True)
            return 1
        print("stores resetados")
        if not args.path and not args.source:
            return 0
```

Change the `--status` branch to use the new `_montar` signature and count chunks:

```python
    if args.status:
        _, stores = _montar(settings)
        print(f"qdrant vetores: {stores.vector.contar()}")
        print(f"postgres chunks: {stores.catalog.contar_chunks()}")
        print(f"neo4j entidades: {stores.graph.contar_entidades()}")
        return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS, incluindo os três testes novos.

- [ ] **Step 5: Checkpoint (no commit)**

Run: `uv run pytest -v`
Expected: PASS na suite inteira.

---

### Task 13: Fontes remotas e web com `chave_externa` e hash

**Files:**
- Modify: `src/forge/knowledge/sources/web.py`
- Modify: `src/forge/knowledge/sources/remote/gutenberg.py:89-95`, `internet_archive.py:83-89`, `sep.py:75-81`, `wikisource.py:78-84`
- Test: `tests/knowledge/sources/test_web.py`, e os testes existentes de `tests/knowledge/sources/remote/`

**Interfaces:**
- Consumes: `Documento`, `hash_texto`, `id_deterministico` (Task 1).
- Produces: todo `Documento` construído por fonte remota ou web carrega `hash_sha256` e `chave_externa`.

- [ ] **Step 1: Write the failing test**

Create `tests/knowledge/sources/test_web.py`:

```python
from forge.knowledge.domain.models import hash_texto
from forge.knowledge.sources.web import documento_de_resultado, documentos_de_busca


def test_documento_de_web_carrega_hash_do_texto():
    doc = documento_de_resultado(
        {"url": "https://exemplo.org/a", "title": "Virtude", "snippet": "corpo"}
    )
    assert doc.hash_sha256 == hash_texto("corpo")


def test_chave_externa_de_web_e_a_url():
    doc = documento_de_resultado({"url": "https://exemplo.org/a", "title": "Virtude"})
    assert doc.chave_externa == "web::https://exemplo.org/a"


def test_resultado_sem_url_e_descartado():
    assert documento_de_resultado({"title": "sem url"}) is None
    assert documentos_de_busca([{"title": "sem url"}]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/knowledge/sources/test_web.py -v`
Expected: FAIL — `Documento` exige `hash_sha256`, que `web.py` não passa.

- [ ] **Step 3: Write the implementation**

In `src/forge/knowledge/sources/web.py`, replace `documento_de_resultado`:

```python
def documento_de_resultado(resultado: dict) -> Documento | None:
    url = resultado.get("url") or resultado.get("href")
    if not url:
        logger.debug("Resultado de busca sem url, ignorado", resultado=resultado)
        return None
    texto = resultado.get("snippet") or resultado.get("body") or ""
    titulo = resultado.get("title") or url
    chave = f"web::{url}"
    return Documento(
        id=id_deterministico("documento", chave),
        hash_sha256=hash_texto(texto),
        titulo=titulo,
        texto=texto,
        proveniencia=Proveniencia.de_web(url=url, titulo=titulo),
        chave_externa=chave,
    )
```

> **Decisão do usuário, posterior à escrita do plano:** `documento.id` deriva de
> `chave_externa`, **não** do hash. `chave_externa` é a identidade estável da obra
> e carrega o índice UNIQUE, para que a mesma obra da mesma fonte nunca seja
> reprocessada em duplicata. Reprocessar reusa a linha existente; `hash_sha256`
> continua como coluna e é o que denuncia que o conteúdo mudou. Chunk segue com
> id de conteúdo — anotação semântica de K2-K4 sobrevive.

Update its import line to:

```python
from forge.knowledge.domain.models import (
    Documento,
    Proveniencia,
    hash_texto,
    id_deterministico,
)
```

In each of the four remote sources, the `Documento(...)` construction changes the same way. For `gutenberg.py` (and identically for the other three, swapping the source name):

```python
        return Documento(
            id=id_deterministico("documento", ref.chave_externa),
            hash_sha256=hash_texto(texto),
            titulo=ref.titulo,
            texto=texto,
            proveniencia=prov,
            chave_externa=ref.chave_externa,
        )
```

Update each file's import to include `hash_texto`.

In `src/forge/knowledge/sources/remote/base.py`, add `chave_externa` to `Referencia` alongside the existing `chave`:

```python
    @property
    def chave_externa(self) -> str:
        """Identidade da obra na fonte. Conhecida antes do download, ao contrário
        do hash — é o que permite pular o que já está na base."""
        return f"{self.fonte}::{self.id_externo}"

    @property
    def chave(self) -> str:
        return self.chave_externa
```

Remove the now-unused `id_deterministico` import from `base.py` if nothing else uses it.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/knowledge/sources -v`
Expected: PASS. Os testes existentes de `remote/` continuam passando; se algum construir `Documento` diretamente, adicione `hash_sha256=hash_texto(<texto>)` na fixture.

- [ ] **Step 5: Checkpoint (no commit)**

Run: `uv run pytest -v`
Expected: PASS na suite inteira.

---

### Task 14: Testes de integração dos stores reais

**Files:**
- Create: `tests/knowledge/stores/test_stores_reais.py`

**Interfaces:**
- Consumes: `CatalogStore` (Task 8), `VectorStore` (Task 9), `Stores`, `ingerir_entradas` (Task 10).
- Produces: nada — suite de verificação.

- [ ] **Step 1: Write the failing test**

Create `tests/knowledge/stores/test_stores_reais.py`:

```python
"""Roda contra os stores de verdade (docker compose up -d). Pulado se não houver.

Cobre o que fake nenhum cobre: se a generated column com CASE é aceita pelo
Postgres, se o índice único de chave_externa existe, e se o ts_rank casa com o
stemmer do idioma certo.
"""
import pytest

from forge.infrastructure.config import Settings
from forge.knowledge.domain.models import Chunk, Documento, Proveniencia, hash_texto

pytestmark = pytest.mark.integration


@pytest.fixture
def catalog():
    psycopg = pytest.importorskip("psycopg")
    from forge.knowledge.stores.catalog import CatalogStore

    dsn = Settings().knowledge.postgres_dsn
    try:
        store = CatalogStore(dsn)
    except psycopg.OperationalError:
        pytest.skip("Postgres indisponível")
    store.resetar()
    yield store
    store.close()


def documento(idioma="pt", texto="corpo"):
    return Documento(
        id=f"doc-{idioma}", hash_sha256=hash_texto(texto), titulo="Obra",
        texto=texto, chave_externa=f"teste::{idioma}",
        proveniencia=Proveniencia.de_livro(fonte="obra.md", idioma=idioma),
    )


def paragrafo(doc_id, texto, cid):
    return Chunk(
        id=cid, documento_id=doc_id, pai_id=None, nivel="paragrafo",
        caminho="0001.0001", ordem=1, texto=texto,
        offset_inicio=0, offset_fim=len(texto),
    )


def test_schema_com_generated_column_e_aceito_pelo_postgres(catalog):
    assert catalog.contar_chunks() == 0


def test_chave_externa_e_detectada_depois_do_upsert(catalog):
    doc = documento()
    catalog.upsert_documento(doc)
    assert catalog.existe_chave_externa("teste::pt")
    assert not catalog.existe_chave_externa("teste::inexistente")


def test_stemmer_portugues_casa_flexao(catalog):
    doc = documento()
    catalog.upsert_documento(doc)
    catalog.upsert_chunks(
        [paragrafo(doc.id, "a existência precede a essência", "c-pt")], idioma="pt"
    )
    with catalog._conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM chunks "
            "WHERE tsv @@ plainto_tsquery('portuguese', %(q)s)",
            {"q": "existencias"},
        )
        assert cur.fetchone()[0] == 1


def test_documento_em_ingles_usa_o_stemmer_ingles(catalog):
    doc = documento(idioma="en", texto="english body")
    catalog.upsert_documento(doc)
    catalog.upsert_chunks(
        [paragrafo(doc.id, "existence precedes essence", "c-en")], idioma="en"
    )
    with catalog._conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM chunks "
            "WHERE tsv @@ plainto_tsquery('english', %(q)s)",
            {"q": "precede"},
        )
        assert cur.fetchone()[0] == 1


def test_apagar_documento_leva_os_chunks_junto(catalog):
    doc = documento()
    catalog.upsert_documento(doc)
    catalog.upsert_chunks([paragrafo(doc.id, "trecho qualquer", "c-1")], idioma="pt")
    assert catalog.contar_chunks() == 1
    with catalog._conn.cursor() as cur:
        cur.execute("DELETE FROM documentos WHERE id = %(i)s", {"i": doc.id})
    assert catalog.contar_chunks() == 0
```

- [ ] **Step 2: Run test to verify it fails or skips**

Run: `uv run pytest tests/knowledge/stores/test_stores_reais.py -v`
Expected: sem Docker no ar, 5 skipped com "Postgres indisponível". Com `docker compose up -d`, 5 passed.

- [ ] **Step 3: Register the marker**

In `pyproject.toml`, under `[tool.pytest.ini_options]`, add:

```toml
markers = ["integration: exige os stores do docker-compose no ar"]
```

- [ ] **Step 4: Run to verify**

Run: `docker compose up -d && sleep 10 && uv run pytest tests/knowledge/stores/test_stores_reais.py -v`
Expected: 5 passed.

Se o Docker não estiver disponível no ambiente, rode `uv run pytest tests/knowledge/stores/test_stores_reais.py -v` e confirme 5 skipped — o resultado não pode ser "failed".

- [ ] **Step 5: Checkpoint (no commit)**

Run: `uv run pytest -v`
Expected: PASS (ou skip nos de integração).

---

### Task 15: Reconciliação dos documentos com knowledge.md

**Files:**
- Modify: `docs/Base_de_conhecimento.md`
- Modify: `docs/RAG_retriever_hibrido.md`
- Modify: `docs/CreatorBrain_Plataforma_Arquitetura_Visao.md:177-180`, `:248-272`
- Modify: `CLAUDE.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: nada.
- Produces: nada — documentação.

`docs/knowledge.md` é a fonte única e **não é alterado**.

- [ ] **Step 1: Substituir `docs/Base_de_conhecimento.md`**

Replace the whole file with:

```markdown
# Base de Conhecimento

> Superado. O fluxo linear que este documento descrevia foi substituído pelos
> seis níveis de [knowledge.md](knowledge.md), que é a fonte de verdade da
> camada Knowledge.

Ver [knowledge.md](knowledge.md).
```

- [ ] **Step 2: Atualizar `docs/RAG_retriever_hibrido.md`**

Add at the top of the file:

```markdown
> Escopo de K5, depois que K1-K4 tiverem gravado os sinais. Fonte de verdade da
> camada Knowledge: [knowledge.md](knowledge.md).
```

Replace the signal list (the block from `BM25` through `Autoridade`) with:

```text
BM25

+

Vetorial de chunk

+

Vetorial de conceito

+

Knowledge Graph

+

Metadados

+

Recência

+

Autoridade

+

Confiança
```

`Vetorial de conceito` e `Confiança` vêm de knowledge.md (Similaridade Conceitual e Refinamento por Confiança) e não existiam no desenho original.

- [ ] **Step 3: Atualizar `docs/CreatorBrain_Plataforma_Arquitetura_Visao.md`**

Replace the "Pipeline RAG" section (lines 177-180) with:

```markdown
# Pipeline RAG

Ver [knowledge.md](knowledge.md) — fonte de verdade da camada Knowledge.
```

Replace the V2 entry of the roadmap with:

```markdown
## V2

Camada Knowledge, decomposta em seis sub-projetos:

- **K1** — Documento original e chunking hierárquico (Níveis 1-2)
- **K2** — Estudo do chunk por agentes especializados (Nível 3)
- **K3** — Extração de conhecimento: ontologia, proposições, argumentos (Nível 4)
- **K4** — Conceitos refinados e grafo hierárquico (Nível 5)
- **K5** — Retriever híbrido completo
- **K6** — Conhecimento global: contradições, confiança, sínteses (Nível 6)
```

- [ ] **Step 4: Atualizar `CLAUDE.md`**

Replace the "Knowledge layer / RAG" section with:

```markdown
### Knowledge layer ([knowledge/](src/forge/knowledge/), optional, off by default)

Fonte de verdade do design: [docs/knowledge.md](docs/knowledge.md). Seis níveis,
implementados como seis sub-projetos K1-K6.

**Duas árvores que nunca se misturam.** A estrutural (Postgres) é imutável,
derivada só do texto, sem LLM: Livro > Capítulo > Subcapítulo > Seção > Parágrafo
> Sentença, com `pai_id` e caminho materializado. O grafo semântico (Neo4j) é
evolutivo, referencia `chunk_id` e é escrito a partir de K3. Regenerar a camada
semântica nunca exige reingerir a estrutural.

- **Identidade de chunk vem do conteúdo**, não da posição:
  `id_deterministico(documento_id, sha256(texto), ocorrencia)`. A camada semântica
  acumula anotações sobre `chunk_id`; id posicional invalidaria tudo a cada
  reingestão.
- **Texto nunca é alterado.** `documentos.texto` é a extração crua; o texto de um
  chunk é fatia por offset. Normalização só como entrada transitória de tsvector e
  embedding.
- **Só a folha-parágrafo é embedada** (small-to-big): vetor preciso, entrega sobe
  pelo `pai_id`. Só ela tem coluna `texto`; os outros níveis derivam por offset.
- **Ingestão de K1 não faz nenhuma chamada de LLM.** A única que resta na camada é
  a tradução do termo de busca em fontes remotas, que não toca o conteúdo.
- **Retriever dormente até K5.** `retriever/hybrid.py` não tem chamador; o comando
  `forge buscar` não existe; o fluxo de roteiro não toca a camada.
- Testabilidade: `embed_fn` e `stores` entram por injeção — o pipeline roda com
  fakes, sem Docker. `_montar()` monta as reais a partir de `Settings`.
```

Also update the Commands block: remove `uv run forge buscar` if present, and add:

```bash
uv run forge ingest --reset          # APAGA os três stores e recria o schema
```

- [ ] **Step 5: Atualizar `README.md`**

Replace the module layout section (que ainda descreve `writer/`, `orchestrator/`, `llm/`, `output/`) with:

```text
src/forge/
  agents/          tema, research, plan, write, review
  orchestration/   grafo LangGraph e estado compartilhado
  llms/            providers (anthropic, openai, lm-studio) e parsing
  knowledge/       camada Knowledge — ver docs/knowledge.md
  prompts/         markdown carregado por nome
  skills/          markdown com frontmatter, injetado nos prompts
  services/        artefatos de run e escrita do roteiro final
  domain/          modelos do roteiro
  infrastructure/  config e logging
```

Replace any description of the knowledge layer with a single line pointing to
`docs/knowledge.md`, and remove any mention of `forge buscar`.

- [ ] **Step 6: Checkpoint (no commit)**

Run: `uv run pytest -v`
Expected: PASS.

Confirme manualmente que nenhum documento em `docs/` descreve chunking por caracteres, análise de documento inteiro por LLM, ou o comando `buscar`.

---

## Verificação final

- [ ] `uv run pytest -v` — suite inteira passa.
- [ ] `uv run forge ingest --path <livro.epub>` ingere sem nenhuma chamada de LLM (confirme pelos logs: nenhum `Settings loaded ... model=`por parte da ingestão, nenhuma latência de rede entre `Livro carregado` e `Ingestão concluída`).
- [ ] `uv run forge roteiro --tema "teste"` funciona com `FORGE_KNOWLEDGE_ENABLED=true` — a flag não tem mais efeito, e o fluxo não toca a camada.
- [ ] `uv run forge buscar --query x` falha com erro de argumento inválido.
- [ ] Critérios de conclusão do spec §13, um a um.
