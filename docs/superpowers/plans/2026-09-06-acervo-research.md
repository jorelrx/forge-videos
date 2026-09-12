# Research via acervo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trocar a pesquisa web do forge por consultas à API `acervo`, de modo que toda fonte citada no roteiro venha de um livro indexado, com caminho canônico verificável.

**Architecture:** Um cliente HTTP fino (`services/acervo.py`) fala com a API. O agente `research` passa a ter três fases puras: o LLM formula queries, o cliente busca, o LLM sintetiza o brief. As fontes deixam de ser inferidas por LLM — são construídas a partir da resposta HTTP. Antes disso, as pontas soltas da camada `knowledge` removida são varridas, porque `forge ingest` hoje quebra ao importar módulo inexistente.

**Tech Stack:** Python 3.12, `uv`, pydantic v2, pydantic-settings, httpx, langgraph/langchain-core, pytest, structlog.

**Spec:** [docs/superpowers/specs/2026-09-06-video-pipeline-design.md](../specs/2026-09-06-video-pipeline-design.md) — sub-projetos S0 e S1.

## Global Constraints

- Nomes de domínio, de estado e mensagens de log em português; identificadores de código misturam português e inglês. Casar com o arquivo ao redor.
- Log estruturado com `structlog`: `get_logger(__name__)`, campos `chave=valor`, nunca f-string dentro da chamada de log.
- Nenhum teste toca a rede. O modelo é sempre a fixture `scripted`; o HTTP é sempre `httpx.MockTransport`.
- `docs/superpowers/` está no `.gitignore` (linha 2). Nunca commitar spec ou plano, nem com `-f`.
- A API do acervo é `http://127.0.0.1:8000`. Endpoints usados: `GET /search`, `GET /discover`, `GET /health`.
- Sem fallback para busca web sob nenhuma condição. Acervo fora do ar é erro explícito.
- Rodar a suíte com `uv run pytest`.
- Mensagens de commit em inglês, prefixo `feat:`/`fix:`/`chore:`/`docs:`.

---

### Task 1: Varrer as pontas soltas da camada `knowledge`

A pasta `src/forge/knowledge/` já foi apagada do working tree, mas as referências ficaram. `forge ingest` levanta `ModuleNotFoundError`. Esta tarefa fecha esse buraco antes de qualquer coisa nova entrar.

**Files:**
- Modify: `src/forge/cli.py:44-68` (parser do `ingest`), `src/forge/cli.py:70-71` (dispatch), `src/forge/cli.py:76-135` (`_confirmar_reset`, `_cmd_ingest`)
- Modify: `src/forge/infrastructure/config.py:5` (import), `:15-53` (`KnowledgeSettings`), `:94-95` (campos)
- Modify: `pyproject.toml:19-31` (extras `knowledge`, `books`, `ocr`)
- Modify: `tests/test_cli.py:36-40` (teste do `ingest`)
- Modify: `tests/test_config.py:76-84` (teste de `KnowledgeSettings`)
- Modify: `CLAUDE.md` (seção "Knowledge layer" e bloco de comandos)
- Delete: `tests/knowledge/`, `docker-compose.yml`, `docs/knowledge.md`

**Interfaces:**
- Consumes: nada.
- Produces: `Settings` sem os campos `knowledge_enabled` e `knowledge`; CLI com um único subcomando, `roteiro`.

- [ ] **Step 1: Confirmar o estado quebrado**

Run: `uv run forge ingest --status`
Expected: `ModuleNotFoundError: No module named 'forge.knowledge'`

Isso é a linha de base — a tarefa existe para eliminá-la.

- [ ] **Step 2: Escrever o teste que fixa o CLI sem `ingest`**

Substituir `test_ingest_source_sem_query_falha` em `tests/test_cli.py` por:

```python
def test_ingest_nao_e_mais_um_subcomando():
    """A ingestão de livros é do acervo (POST /books/{id}/ingest), não do forge."""
    with pytest.raises(SystemExit) as exc:
        cli.main(["ingest", "--status"])
    assert exc.value.code == 2  # argparse: subcomando inválido
```

- [ ] **Step 3: Rodar o teste e ver falhar**

Run: `uv run pytest tests/test_cli.py::test_ingest_nao_e_mais_um_subcomando -v`
Expected: FAIL — hoje `main` chega em `_cmd_ingest` e estoura `ModuleNotFoundError`, não `SystemExit`.

- [ ] **Step 4: Remover o subcomando do CLI**

Em `src/forge/cli.py`, apagar o bloco inteiro do parser `ing = sub.add_parser("ingest", ...)` até o último `ing.add_argument(...)`, apagar o dispatch e apagar as duas funções auxiliares:

```python
    # apagar estas duas linhas do dispatch:
    if args.cmd == "ingest":
        return _cmd_ingest(args)
    # sobra apenas:
    return _cmd_roteiro(args)
```

Apagar `_confirmar_reset` e `_cmd_ingest` por completo. O import `from pathlib import Path` continua em uso por `_cmd_roteiro`; conferir antes de mexer nos imports.

- [ ] **Step 5: Rodar o teste e ver passar**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 6: Remover `KnowledgeSettings` da config**

Em `src/forge/infrastructure/config.py`: apagar a classe `KnowledgeSettings` inteira, apagar os dois campos de `Settings`:

```python
    # apagar:
    knowledge_enabled: bool = False
    knowledge: KnowledgeSettings = Field(default_factory=KnowledgeSettings)
```

`BaseModel` fica sem uso — ajustar o import para `from pydantic import AliasChoices, Field`. `Field` continua em uso pelas chaves de API.

Apagar `test_knowledge_tem_defaults_de_fontes_remotas` de `tests/test_config.py`.

- [ ] **Step 7: Remover os extras e os arquivos órfãos**

Em `pyproject.toml`, apagar o bloco `[project.optional-dependencies]` inteiro — os três extras (`knowledge`, `books`, `ocr`) existiam só para a camada removida.

```bash
git rm -r tests/knowledge
git rm docker-compose.yml docs/knowledge.md
```

`docker-compose.yml` só continha Qdrant, Neo4j e Postgres da camada de conhecimento; o acervo é dono dos próprios stores.

- [ ] **Step 8: Atualizar o `CLAUDE.md`**

No bloco de comandos, apagar as quatro linhas de `uv sync --extra ...` e `forge ingest ...` e a linha do `docker compose up -d`. Substituir a seção `### Knowledge layer (...)` inteira por:

```markdown
### Acervo ([services/acervo.py](src/forge/services/acervo.py))

A pesquisa não usa a web. Um serviço externo, `acervo`
(`FORGE_ACERVO_URL`, default `http://127.0.0.1:8000`), indexa livros de domínio
público e devolve passagens com caminho canônico estável (`PassageOut.path`) —
é esse caminho que o roteiro cita. O forge só consome: ingestão de livros é do
acervo (`POST /books/{book_id}/ingest`), não daqui.

Acervo fora do ar levanta `AcervoIndisponivel`. Não existe fallback para busca
web: um fallback silencioso reintroduziria exatamente a fonte não-citável que
este desenho elimina.
```

Ajustar também a nota do topo sobre a árvore de módulos, que cita `knowledge/`.

- [ ] **Step 9: Rodar a suíte inteira**

Run: `uv run pytest`
Expected: PASS, sem erro de coleta (a pasta `tests/knowledge/` sumiu)

- [ ] **Step 10: Conferir que o CLI subiu limpo**

Run: `uv run forge --help`
Expected: lista apenas o subcomando `roteiro`

- [ ] **Step 11: Commit**

```bash
git add -A
git commit -m "chore: remove leftovers of the deleted knowledge layer

The knowledge/ package was already deleted from the tree, but cli.py still
registered an `ingest` subcommand importing it, so `forge ingest` raised
ModuleNotFoundError. Book ingestion belongs to the acervo service now.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Cliente do acervo

**Files:**
- Create: `src/forge/services/acervo.py`
- Create: `tests/services/__init__.py`, `tests/services/test_acervo.py`
- Modify: `src/forge/infrastructure/config.py` (três campos novos em `Settings`)
- Modify: `pyproject.toml` (dependência `httpx`)
- Modify: `tests/test_config.py` (defaults do acervo)

**Interfaces:**
- Consumes: `Settings` da Task 1 (já sem `knowledge`).
- Produces:
  - `class AcervoIndisponivel(RuntimeError)`
  - `class Passagem(BaseModel)` com `path: str`, `book_id: int`, `book_title: str`, `authors: list[str]`, `breadcrumb: str`, `text: str`, `url: str`, `score: float`
  - `class Candidato(BaseModel)` com `id: int`, `title: str`, `authors: list[str]`, `ingested: bool`
  - `class Acervo` com `__init__(self, base_url: str, *, timeout: float = 30.0, client: httpx.Client | None = None)`, `saude() -> bool`, `buscar(q: str, *, top: int = 8, excerpt: int = 160, rerank: bool = False, neighbours: bool = False) -> list[Passagem]`, `descobrir(q: str, *, limite: int = 5) -> list[Candidato]`
  - `Settings.acervo_url: str`, `Settings.acervo_top: int`, `Settings.acervo_timeout: float`

- [ ] **Step 1: Adicionar `httpx` às dependências**

`httpx` estava só no extra `knowledge`, que a Task 1 apagou. Agora é dependência de núcleo.

Em `pyproject.toml`, dentro de `dependencies`, acrescentar `"httpx>=0.27",`.

Run: `uv sync`
Expected: instala `httpx`, sem erro

- [ ] **Step 2: Escrever os testes do cliente**

Criar `tests/services/__init__.py` vazio e `tests/services/test_acervo.py`:

```python
import httpx
import pytest

from forge.services.acervo import Acervo, AcervoIndisponivel

BASE = "http://acervo.test"

PASSAGEM = {
    "path": "4363/ch2/p7",
    "book_id": 4363,
    "book_title": "Beyond Good and Evil",
    "authors": ["Friedrich Nietzsche"],
    "breadcrumb": "Chapter 2 > Section 3",
    "text": "trecho do livro",
    "url": "http://acervo.test/books/4363",
    "score": 0.81,
    "rerank_score": None,
}


def _acervo(handler) -> Acervo:
    """Cliente com transporte falso: o teste inteiro roda sem rede."""
    cliente = httpx.Client(base_url=BASE, transport=httpx.MockTransport(handler))
    return Acervo(BASE, client=cliente)


def test_buscar_converte_passagens():
    def handler(request):
        assert request.url.path == "/search"
        assert request.url.params["q"] == "livre-arbítrio"
        assert request.url.params["top"] == "3"
        return httpx.Response(200, json={
            "question": "livre-arbítrio", "took_ms": 12, "candidates": 1,
            "passages": [PASSAGEM],
        })

    passagens = _acervo(handler).buscar("livre-arbítrio", top=3)

    assert len(passagens) == 1
    p = passagens[0]
    assert p.path == "4363/ch2/p7"
    assert p.book_id == 4363
    assert p.book_title == "Beyond Good and Evil"
    assert p.authors == ["Friedrich Nietzsche"]
    assert p.score == 0.81


def test_buscar_sem_resultado_devolve_lista_vazia():
    def handler(request):
        return httpx.Response(200, json={
            "question": "x", "took_ms": 3, "candidates": 0, "passages": [],
        })

    assert _acervo(handler).buscar("x") == []


def test_acervo_fora_do_ar_levanta():
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(AcervoIndisponivel):
        _acervo(handler).buscar("x")


def test_resposta_de_erro_levanta():
    def handler(request):
        return httpx.Response(500, text="boom")

    with pytest.raises(AcervoIndisponivel):
        _acervo(handler).buscar("x")


def test_saude_devolve_false_em_vez_de_levantar():
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    assert _acervo(handler).saude() is False


def test_descobrir_converte_candidatos():
    def handler(request):
        assert request.url.path == "/discover"
        return httpx.Response(200, json={
            "query": "determinismo",
            "candidates": [
                {"id": 37358, "title": "Determinism or Free-Will?",
                 "authors": ["Chapman Cohen"], "ingested": False},
            ],
            "fronts": {},
        })

    candidatos = _acervo(handler).descobrir("determinismo")

    assert [c.id for c in candidatos] == [37358]
    assert candidatos[0].ingested is False
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `uv run pytest tests/services/test_acervo.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'forge.services.acervo'`

- [ ] **Step 4: Implementar o cliente**

Criar `src/forge/services/acervo.py`:

```python
"""Cliente da API `acervo` — a única fonte de material de pesquisa do forge.

O acervo indexa livros de domínio público e devolve passagens com caminho
canônico estável. É esse caminho (`Passagem.path`) que o roteiro cita: ele
sobrevive à re-fragmentação de outros livros, ao contrário de um número de
página ou de um offset.

Nenhuma chamada de LLM acontece aqui. O módulo traduz HTTP em modelos e nada
mais.
"""

from __future__ import annotations

import httpx
from pydantic import BaseModel, Field

from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)


class AcervoIndisponivel(RuntimeError):
    """O acervo não respondeu.

    Levantar em vez de cair para busca web é deliberado: um fallback silencioso
    devolveria material sem caminho citável, que é exatamente o que este
    desenho elimina.
    """


class Passagem(BaseModel):
    """Espelha `PassageOut` da API. Campos extras da resposta são ignorados."""

    path: str
    book_id: int
    book_title: str
    authors: list[str] = Field(default_factory=list)
    breadcrumb: str = ""
    text: str
    url: str = ""
    score: float = 0.0


class Candidato(BaseModel):
    """Espelha `CandidateOut` do `/discover`: obra sugerida, ainda não ingerida."""

    id: int
    title: str
    authors: list[str] = Field(default_factory=list)
    ingested: bool = False


class Acervo:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        # `client` entra por injeção para que o teste use MockTransport e a
        # suíte inteira rode sem rede.
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"), timeout=timeout
        )

    def _get(self, rota: str, params: dict) -> dict:
        try:
            resp = self._client.get(rota, params=params)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.error("Acervo request failed", rota=rota, error=str(e))
            raise AcervoIndisponivel(f"acervo não respondeu em {rota}: {e}") from e
        return resp.json()

    def saude(self) -> bool:
        try:
            self._get("/health", {})
        except AcervoIndisponivel:
            return False
        return True

    def buscar(
        self,
        q: str,
        *,
        top: int = 8,
        excerpt: int = 160,
        rerank: bool = False,
        neighbours: bool = False,
    ) -> list[Passagem]:
        dados = self._get(
            "/search",
            {
                "q": q,
                "top": top,
                "excerpt": excerpt,
                "rerank": rerank,
                "neighbours": neighbours,
            },
        )
        passagens = [Passagem(**p) for p in dados.get("passages", [])]
        logger.info("Acervo search", query=q, passagens=len(passagens))
        return passagens

    def descobrir(self, q: str, *, limite: int = 5) -> list[Candidato]:
        """Obras que o acervo *poderia* ter mas não tem.

        Usado só para relatar a lacuna ao usuário — o forge nunca ingere nada.
        """
        dados = self._get("/discover", {"q": q})
        candidatos = [Candidato(**c) for c in dados.get("candidates", [])]
        return candidatos[:limite]
```

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest tests/services/test_acervo.py -v`
Expected: PASS, 6 testes

- [ ] **Step 6: Escrever o teste dos defaults de config**

Acrescentar a `tests/test_config.py`:

```python
def test_acervo_tem_defaults_locais():
    from forge.infrastructure.config import Settings

    s = Settings(_env_file=None)
    assert s.acervo_url == "http://127.0.0.1:8000"
    assert s.acervo_top == 8
    assert s.acervo_timeout == 30.0
```

- [ ] **Step 7: Rodar e ver falhar**

Run: `uv run pytest tests/test_config.py::test_acervo_tem_defaults_locais -v`
Expected: FAIL com `AttributeError: 'Settings' object has no attribute 'acervo_url'`

- [ ] **Step 8: Adicionar os campos à `Settings`**

Em `src/forge/infrastructure/config.py`, dentro de `Settings`, logo abaixo de `lm_studio_base_url`:

```python
    # Serviço externo de pesquisa. Substitui a busca web por completo — ver
    # services/acervo.py.
    acervo_url: str = "http://127.0.0.1:8000"
    acervo_top: int = 8
    acervo_timeout: float = 30.0
```

- [ ] **Step 9: Rodar a suíte**

Run: `uv run pytest`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat: add acervo HTTP client

Thin client over the acervo API: /search, /discover, /health. No LLM calls,
no retries beyond httpx defaults. A failed request raises AcervoIndisponivel
rather than degrading, because a silent fallback would reintroduce sources
without a citable canonical path.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: `Fonte` carrega a procedência do acervo

Uma fonte que vem do acervo tem caminho canônico e id de livro. Sem esses campos no modelo, a informação morre entre a resposta HTTP e o artefato em disco — e o `--retomar` perde a procedência.

**Files:**
- Modify: `src/forge/domain/models.py:7-11` (`Fonte`)
- Modify: `src/forge/services/artefatos.py:40-47` (`_fmt_fontes`)
- Modify: `src/forge/services/storage.py:54-59` (render das fontes)
- Create: `tests/test_artefatos.py`
- Modify: `tests/test_storage.py`

**Interfaces:**
- Consumes: `Passagem` da Task 2.
- Produces: `Fonte` com `path: str | None = None` e `book_id: int | None = None`, sobrevivendo ao round-trip `_fmt_fontes` → `_ler_fontes`.

- [ ] **Step 1: Escrever o teste de round-trip**

Criar `tests/test_artefatos.py`:

```python
from forge.domain.models import Fonte
from forge.services.artefatos import _fmt_fontes, _ler_fontes


def test_fonte_do_acervo_sobrevive_ao_round_trip():
    """path e book_id são a procedência; perdê-los no disco quebra o --retomar."""
    fontes = [
        Fonte(
            titulo="Beyond Good and Evil",
            autor="Friedrich Nietzsche",
            url="http://acervo.test/books/4363",
            path="4363/ch2/p7",
            book_id=4363,
        )
    ]

    linha = _fmt_fontes(fontes)
    lidas = _ler_fontes(linha)

    assert lidas == fontes


def test_fonte_antiga_sem_procedencia_ainda_carrega():
    """Runs gravadas antes do acervo não têm path; devem continuar legíveis."""
    lidas = _ler_fontes('fontes: [{"titulo": "Ética", "autor": "Espinosa", "url": null}]')

    assert lidas[0].titulo == "Ética"
    assert lidas[0].path is None
    assert lidas[0].book_id is None
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_artefatos.py -v`
Expected: FAIL — `Fonte` não aceita `path`/`book_id` (pydantic levanta erro de campo extra) e `_fmt_fontes` não os emite.

- [ ] **Step 3: Acrescentar os campos ao modelo**

Em `src/forge/domain/models.py`:

```python
class Fonte(BaseModel):
    titulo: str
    autor: str | None = None
    url: str | None = None
    frase: str | None = None
    # Procedência no acervo. Opcionais porque runs anteriores ao acervo não
    # têm nenhum dos dois, e `--retomar` precisa continuar lendo aqueles
    # artefatos.
    path: str | None = None
    book_id: int | None = None
```

- [ ] **Step 4: Emitir os campos novos no artefato**

Em `src/forge/services/artefatos.py`, dentro de `_fmt_fontes`:

```python
    dados = [
        {
            "titulo": f.titulo,
            "autor": f.autor,
            "url": f.url,
            "path": f.path,
            "book_id": f.book_id,
        }
        for f in fontes
    ]
```

`_ler_fontes` já faz `Fonte(**d)` e não precisa mudar.

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest tests/test_artefatos.py -v`
Expected: PASS, 2 testes

- [ ] **Step 6: Escrever o teste do render do roteiro final**

`tests/test_storage.py` já exercita `gravar_roteiro` com `Settings(_env_file=None, output_dir=tmp_path)` e um helper `_roteiro()`. Seguir o mesmo padrão, sem tocar em `_render` diretamente:

```python
def test_fontes_do_acervo_saem_com_caminho_canonico(tmp_path):
    """O caminho canônico é o que torna a citação verificável no acervo."""
    roteiro = Roteiro(
        tema="determinismo",
        tese="tese",
        secoes=[Secao(nome="Hook", conteudo="c")],
        fontes=[Fonte(titulo="Beyond Good and Evil", autor="Nietzsche",
                      path="4363/ch2/p7", book_id=4363)],
    )
    settings = Settings(_env_file=None, output_dir=tmp_path)

    path = gravar_roteiro(roteiro, settings, rounds=1, aprovado=True)

    assert "- Beyond Good and Evil — Nietzsche (`4363/ch2/p7`)" in path.read_text(encoding="utf-8")


def test_fonte_sem_caminho_sai_sem_parenteses_vazio(tmp_path):
    settings = Settings(_env_file=None, output_dir=tmp_path)

    path = gravar_roteiro(_roteiro(), settings, rounds=1, aprovado=True)

    assert "- Obra — Autor\n" in path.read_text(encoding="utf-8")
```

Os imports de `Roteiro`, `Secao`, `Fonte`, `Settings` e `gravar_roteiro` já estão no topo do arquivo.

- [ ] **Step 7: Rodar e ver falhar**

Run: `uv run pytest tests/test_storage.py -v`
Expected: FAIL — a linha sai sem o caminho entre crases

- [ ] **Step 8: Renderizar o caminho**

Em `src/forge/services/storage.py`:

```python
        for f in roteiro.fontes:
            autor = f" — {f.autor}" if f.autor else ""
            # O caminho canônico é o que torna a citação verificável no acervo.
            caminho = f" (`{f.path}`)" if f.path else ""
            linhas.append(f"- {f.titulo}{autor}{caminho}")
```

- [ ] **Step 9: Rodar a suíte**

Run: `uv run pytest`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat: carry acervo provenance on Fonte

path and book_id travel from the HTTP response to the run artifact and to the
rendered script, so a citation can be verified against the acervo. Both are
optional: runs recorded before the acervo must stay readable by --retomar.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: `research` consulta o acervo

O coração do plano. O agente passa a ter três fases: LLM formula queries, cliente busca, LLM sintetiza. A extração de fontes por LLM (`_extrair_fontes`) morre — era onde nasciam citações inventadas.

**Files:**
- Rewrite: `src/forge/agents/research.py`
- Rewrite: `src/forge/prompts/research.md`
- Create: `src/forge/prompts/queries.md`
- Delete: `src/forge/prompts/fontes.md`
- Modify: `src/forge/orchestration/graph.py:20` (import), `:63-83` (`node_research`), `build_graph`
- Modify: `pyproject.toml` (remover `ddgs`)
- Rewrite: `tests/agents/test_research.py`
- Modify: `tests/conftest.py` (fixture `acervo_fake`)
- Modify: `tests/orchestration/test_graph.py:7` (import), `:60-120` (filas do modelo roteirizado)
- Modify: `CLAUDE.md` (parágrafo de Providers que descreve `web_search`/DuckDuckGo)

**Interfaces:**
- Consumes: `Acervo`, `Passagem`, `AcervoIndisponivel` (Task 2); `Fonte` com `path`/`book_id` (Task 3).
- Produces:
  - `pesquisar(model, tema: str, acervo: Acervo, pedido: str | None = None) -> tuple[str, list[Fonte], str]` — devolve `(brief, fontes, bruto)`, mesma forma de retorno de antes.
  - `formular_queries(model, tema: str, pedido: str | None = None) -> list[str]`
  - `colher(acervo: Acervo, queries: list[str], *, top: int = 8) -> list[Passagem]`
  - `LE = ["tema", "pedido", "research_notes"]` (inalterado)
  - `MAX_QUERIES = 5`

- [ ] **Step 1a: Acrescentar o acervo falso ao `conftest.py`**

`test_research.py` e `test_graph.py` precisam do mesmo duplo. Acrescentar a `tests/conftest.py`, seguindo o mesmo padrão do `scripted` (a fixture devolve a classe, não uma instância):

```python
class FakeAcervo:
    """Acervo falso: passagens fixas, sem rede. Registra as queries recebidas.

    `padrao` responde a qualquer query não mapeada — o teste de grafo não sabe
    que texto o modelo roteirizado vai emitir como query.
    """

    def __init__(self, por_query=None, candidatos=None, padrao=None):
        self.por_query = por_query or {}
        self.candidatos = candidatos or []
        self.padrao = padrao or []
        self.chamadas = []

    def buscar(self, q, **kwargs):
        self.chamadas.append(q)
        return self.por_query.get(q, self.padrao)

    def descobrir(self, q, **kwargs):
        return self.candidatos


@pytest.fixture
def acervo_fake():
    return FakeAcervo
```

- [ ] **Step 1b: Escrever os testes do agente novo**

Substituir o conteúdo inteiro de `tests/agents/test_research.py` por:

```python
from forge.agents.research import colher, formular_queries, pesquisar
from forge.services.acervo import Passagem


def _passagem(path, score, titulo="Beyond Good and Evil"):
    return Passagem(
        path=path, book_id=4363, book_title=titulo,
        authors=["Friedrich Nietzsche"], breadcrumb="Cap 2",
        text=f"texto de {path}", url="http://acervo.test/books/4363", score=score,
    )


def test_formular_queries_limpa_bullets_e_numeracao(scripted):
    model = scripted(invoke_texts=[
        "1. o que é livre-arbítrio\n- determinismo causal\n* vontade em Nietzsche"
    ])

    queries = formular_queries(model, "livre-arbítrio")

    assert queries == [
        "o que é livre-arbítrio",
        "determinismo causal",
        "vontade em Nietzsche",
    ]


def test_formular_queries_corta_no_maximo(scripted):
    model = scripted(invoke_texts=["\n".join(f"query {i}" for i in range(20))])

    assert len(formular_queries(model, "x")) == 5


def test_colher_deduplica_por_path_e_ordena_por_score(acervo_fake):
    acervo = acervo_fake(por_query={
        "a": [_passagem("p1", 0.5), _passagem("p2", 0.9)],
        "b": [_passagem("p1", 0.8), _passagem("p3", 0.2)],
    })

    passagens = colher(acervo, ["a", "b"])

    assert [p.path for p in passagens] == ["p2", "p1", "p3"]
    # p1 apareceu nas duas queries; fica com o maior score, não com o último.
    assert passagens[1].score == 0.8


def test_pesquisar_devolve_brief_e_fontes_estruturadas(scripted, acervo_fake):
    acervo = acervo_fake(por_query={"vontade": [_passagem("4363/ch2/p7", 0.81)]})
    model = scripted(invoke_texts=["vontade", "notas densas sobre a vontade"])

    brief, fontes, bruto = pesquisar(model, "vontade de potência", acervo)

    assert brief == "notas densas sobre a vontade"
    assert len(fontes) == 1
    assert fontes[0].titulo == "Beyond Good and Evil"
    assert fontes[0].autor == "Friedrich Nietzsche"
    assert fontes[0].path == "4363/ch2/p7"
    assert fontes[0].book_id == 4363
    assert "4363/ch2/p7" in bruto


def test_pesquisar_sem_passagens_relata_lacuna_e_nao_chama_o_modelo(scripted, acervo_fake):
    from forge.services.acervo import Candidato

    acervo = acervo_fake(candidatos=[
        Candidato(id=37358, title="Determinism or Free-Will?",
                  authors=["Chapman Cohen"]),
    ])
    # Só uma resposta na fila: a das queries. Se o agente tentar sintetizar um
    # brief sem material, o modelo falso estoura — que é o comportamento que
    # este teste tranca.
    model = scripted(invoke_texts=["determinismo"])

    brief, fontes, _ = pesquisar(model, "determinismo", acervo)

    assert fontes == []
    assert "Lacuna no acervo" in brief
    assert "Determinism or Free-Will?" in brief


def test_pedido_dirigido_entra_na_formulacao_das_queries(scripted, acervo_fake):
    acervo = acervo_fake(por_query={"kant sobre dever": [_passagem("p1", 0.5)]})
    model = scripted(invoke_texts=["kant sobre dever", "verificação"])

    pesquisar(model, "ética", acervo, pedido="Kant disse que o dever é X?")

    assert acervo.chamadas == ["kant sobre dever"]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/agents/test_research.py -v`
Expected: FAIL com `ImportError: cannot import name 'colher' from 'forge.agents.research'`

- [ ] **Step 3: Escrever o prompt de formulação de queries**

Criar `src/forge/prompts/queries.md`:

```markdown
Você vai pesquisar num acervo de livros de domínio público — filosofia,
psicologia, política, história das ideias. A busca é semântica: frases inteiras
funcionam melhor que palavras soltas.

Tema do roteiro: {tema}

{pedido}

Escreva de 3 a 5 buscas que cubram ângulos diferentes do tema. Uma por linha.
Sem numeração, sem marcador, sem comentário, sem nada antes ou depois da lista.
```

- [ ] **Step 4: Reescrever o prompt de síntese**

Substituir `src/forge/prompts/research.md` inteiro por:

```markdown
Você recebeu passagens de um acervo de livros de domínio público. Elas são o
único material disponível: não afirme fato, obra ou autor que não esteja abaixo.

Tema: {tema}

{skills}

{pedido}

Passagens — cada uma abre com o caminho canônico entre colchetes:

{passagens}

Produza notas de pesquisa densas: ideias-chave, escolas e autores presentes nas
passagens, e as tensões entre eles. Toda afirmação que dependa das passagens vem
seguida do caminho entre colchetes, na forma [4363/ch2/p7]. Onde as passagens
não cobrirem parte do tema, diga isso explicitamente — não preencha a lacuna de
memória.
```

- [ ] **Step 5: Reescrever o agente**

Substituir `src/forge/agents/research.py` inteiro por:

```python
"""Pesquisa contra o acervo.

Três fases, nesta ordem: o LLM formula as queries, o cliente HTTP busca, o LLM
sintetiza o brief a partir do que voltou. As fontes NÃO passam pelo modelo —
são construídas das passagens. A extração por LLM que existia aqui antes era a
origem das citações inventadas: o modelo relia o próprio brief e reconstruía
referências de memória.
"""

from __future__ import annotations

import re

from langchain_core.messages import HumanMessage

from forge.domain.models import Fonte
from forge.infrastructure.logging import get_logger
from forge.llms.parsing import _texto
from forge.prompts.loader import load_prompt
from forge.services.acervo import Acervo, Candidato, Passagem
from forge.skills.loader import load_skills

logger = get_logger(__name__)

SKILLS = ["fact_check"]
LE = ["tema", "pedido", "research_notes"]

MAX_QUERIES = 5

# Marcador de lista que o modelo insiste em emitir mesmo quando o prompt pede
# uma linha limpa.
_MARCADOR = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")


def pesquisar(
    model, tema: str, acervo: Acervo, pedido: str | None = None
) -> tuple[str, list[Fonte], str]:
    queries = formular_queries(model, tema, pedido)
    passagens = colher(acervo, queries)
    bruto = _bruto(queries, passagens)

    if not passagens:
        candidatos = acervo.descobrir(tema)
        logger.warning("Acervo gap", tema=tema, sugestoes=len(candidatos))
        return _brief_lacuna(tema, candidatos), [], bruto

    brief = _sintetizar(model, tema, pedido, passagens)
    logger.info("Research completed", queries=len(queries), passagens=len(passagens))
    return brief, _fontes(passagens), bruto


def formular_queries(model, tema: str, pedido: str | None = None) -> list[str]:
    prompt = load_prompt("queries").format(tema=tema, pedido=_fmt_pedido(pedido))
    resp = model.invoke([HumanMessage(content=prompt)])
    queries = _parse_queries(_texto(resp))
    logger.debug("Queries formuladas", queries=queries)
    return queries


def _parse_queries(texto: str) -> list[str]:
    """Uma query por linha, sem marcador e sem aspas, deduplicadas."""
    queries: list[str] = []
    for linha in texto.splitlines():
        q = _MARCADOR.sub("", linha).strip().strip('"')
        if q and q not in queries:
            queries.append(q)
    return queries[:MAX_QUERIES]


def colher(acervo: Acervo, queries: list[str], *, top: int = 8) -> list[Passagem]:
    """Busca cada query e funde os resultados.

    A mesma passagem costuma responder a mais de uma query. Deduplicar por
    `path` e guardar o maior score preserva a ordenação por relevância; guardar
    o último visto a destruiria.
    """
    por_path: dict[str, Passagem] = {}
    for q in queries:
        for p in acervo.buscar(q, top=top):
            atual = por_path.get(p.path)
            if atual is None or p.score > atual.score:
                por_path[p.path] = p
    return sorted(por_path.values(), key=lambda p: p.score, reverse=True)


def _sintetizar(model, tema: str, pedido: str | None, passagens: list[Passagem]) -> str:
    prompt = load_prompt("research").format(
        tema=tema,
        skills=load_skills(SKILLS, "research"),
        pedido=_fmt_pedido(pedido),
        passagens=_fmt_passagens(passagens),
    )
    return _texto(model.invoke([HumanMessage(content=prompt)]))


def _fmt_passagens(passagens: list[Passagem]) -> str:
    blocos = []
    for p in passagens:
        autores = ", ".join(p.authors) or "autor não identificado"
        blocos.append(f"[{p.path}] {p.book_title} — {autores}\n{p.breadcrumb}\n\n{p.text}")
    return "\n\n---\n\n".join(blocos)


def _fontes(passagens: list[Passagem]) -> list[Fonte]:
    return [
        Fonte(
            titulo=p.book_title,
            autor=", ".join(p.authors) or None,
            url=p.url or None,
            frase=p.text,
            path=p.path,
            book_id=p.book_id,
        )
        for p in passagens
    ]


def _brief_lacuna(tema: str, candidatos: list[Candidato]) -> str:
    """Brief de acervo vazio.

    Relatar a lacuna é o comportamento correto: o modelo não é chamado, então
    não tem como preencher o vazio de memória.
    """
    linhas = [
        "## Lacuna no acervo",
        "",
        f"Nenhuma passagem do acervo cobre: {tema}",
        "",
        "Sem fonte, o roteiro não pode afirmar nada sobre este ponto.",
        "Ingira uma destas obras no acervo e rode de novo:",
        "",
    ]
    if not candidatos:
        linhas.append("- (o /discover do acervo não sugeriu nenhuma obra)")
    for c in candidatos:
        autores = ", ".join(c.authors) or "autor não identificado"
        linhas.append(f"- [{c.id}] {c.title} — {autores}")
    return "\n".join(linhas)


def _bruto(queries: list[str], passagens: list[Passagem]) -> str:
    """Sidecar `.raw.md`: o que foi perguntado e o que voltou, sem síntese."""
    cabeca = "\n".join(f"- {q}" for q in queries) or "(nenhuma)"
    corpo = _fmt_passagens(passagens) if passagens else "(nenhuma passagem)"
    return f"## Queries\n\n{cabeca}\n\n## Passagens\n\n{corpo}"


def _fmt_pedido(pedido: str | None) -> str:
    if not pedido:
        return ""
    return (
        "ATENÇÃO — esta é uma passagem dirigida, não uma pesquisa do zero.\n"
        "Verifique apenas os pontos abaixo e devolva o que confirmou ou não:\n"
        f"{pedido}"
    )
```

- [ ] **Step 6: Rodar e ver passar**

Run: `uv run pytest tests/agents/test_research.py -v`
Expected: PASS, 6 testes

- [ ] **Step 7: Ligar o grafo ao acervo**

Em `src/forge/orchestration/graph.py`, acrescentar o import:

```python
from forge.services.acervo import Acervo
```

Dentro de `build_graph`, antes das definições de nó, construir o cliente uma vez:

```python
    # Um cliente por grafo: `research` é reentrado pelo reviewer e pelo write,
    # e abrir conexão nova a cada passagem não paga nada.
    acervo = Acervo(settings.acervo_url, timeout=settings.acervo_timeout)
```

Trocar o corpo de `node_research`:

```python
    def node_research(state):
        pedido = state.get("pedido")
        logger.debug("Starting research phase", tema=state["tema"], reentrada=bool(pedido))
        brief, fontes, raw = research_stage.pesquisar(model, state["tema"], acervo, pedido)
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

- [ ] **Step 8: Corrigir os testes do grafo**

Run: `uv run pytest tests/orchestration/test_graph.py -v`
Expected: FAIL. Os três testes de grafo completo alimentam um `FonteList` na fila `structured` a cada passagem por `research`, porque `_extrair_fontes` consumia um. Agora `research` não consome nenhum item estruturado e consome **dois** `invoke_texts` (queries e brief).

Em `tests/orchestration/test_graph.py`:

Trocar o import, tirando `FonteList`:

```python
from forge.domain.models import (
    ReviewResult, Nota, Plano, RoteiroDraft, Secao, Fonte,
)
```

Acrescentar, junto de `_draft()`, um helper de passagem e a injeção do acervo falso:

```python
def _passagem():
    from forge.services.acervo import Passagem

    return Passagem(
        path="4363/ch2/p7", book_id=4363, book_title="Obra",
        authors=["Autor"], breadcrumb="Cap 2", text="trecho",
        url="http://acervo.test/books/4363", score=0.9,
    )


@pytest.fixture
def grafo_com_acervo(monkeypatch, acervo_fake):
    """Troca o cliente real do grafo por um falso que sempre acha uma passagem.

    `build_graph` constrói o `Acervo` a partir de `Settings`; sem esta troca o
    teste tentaria falar com 127.0.0.1:8000.
    """
    import forge.orchestration.graph as graph_mod

    fake = acervo_fake(padrao=[_passagem()])
    monkeypatch.setattr(graph_mod, "Acervo", lambda *a, **k: fake)
    return fake
```

Acrescentar `import pytest` no topo, se ainda não houver.

Em `test_grafo_aprova_apos_uma_reprovacao`, receber a fixture e refazer as duas filas. Cada passagem por `research` consome dois `invoke_texts`; nenhuma consome item estruturado:

```python
def test_grafo_aprova_apos_uma_reprovacao(scripted, tmp_path, grafo_com_acervo):
    # invoke_texts: tema, queries(research), brief(research)
    # structured:   plano, draft(v1), review(reprovado), draft(v2), review(aprovado)
    model = scripted(
        invoke_texts=["tema gerado", "busca sobre o tema", "notas de pesquisa"],
        structured=[
            Plano(tese="tese", esboco="esboço"),
            _draft(),
            ReviewResult(aprovado=False, notas=[Nota(dimensao="clareza", problema="p", sugestao="s")]),
            _draft(),
            ReviewResult(aprovado=True),
        ],
    )
    settings = Settings(_env_file=None, max_review_rounds=8)
    graph = build_graph(model, settings)
    final = graph.invoke({"tema": None, "rounds": 0, "run_dir": tmp_path, "passos": 0})
    assert final["review"].aprovado is True
    assert final["rounds"] == 2
    assert final["roteiro"].secoes[0].nome == "Hook"
    assert final["fontes"][0].path == "4363/ch2/p7"
```

Em `test_grafo_para_no_teto`, o mesmo tratamento:

```python
def test_grafo_para_no_teto(scripted, tmp_path, grafo_com_acervo):
    model = scripted(
        invoke_texts=["tema", "busca", "notas"],
        structured=[
            Plano(tese="t", esboco="e"),
            _draft(), ReviewResult(aprovado=False),
            _draft(), ReviewResult(aprovado=False),
        ],
    )
    settings = Settings(_env_file=None, max_review_rounds=2)
    graph = build_graph(model, settings)
    final = graph.invoke({"tema": None, "rounds": 0, "run_dir": tmp_path, "passos": 0})
    assert final["rounds"] == 2
    assert final["review"].aprovado is False
```

Em `test_grafo_termina_com_modelo_patologico`, a docstring inteira descreve a dessincronização causada por `_extrair_fontes`, que deixou de existir. Substituir o teste por:

```python
def test_grafo_termina_com_modelo_patologico(scripted, tmp_path, grafo_com_acervo):
    """Model que sempre pede verificação não pode rodar para sempre.

    O handoff `review -> research` faz `node_research` rodar a cada volta, e
    cada volta consome dois `invoke_texts` (queries e brief) mais um `Plano`,
    um `RoteiroDraft` e um `ReviewResult` da fila estruturada. As filas abaixo
    repetem esse ciclo muito além do necessário: quem tem de encerrar o grafo é
    `max_passos`, não uma fila esgotada.
    """
    n_ciclos = 40  # bem mais que o necessário para estourar max_passos=12
    textos = ["tema"]
    estruturados = []
    for _ in range(n_ciclos):
        textos += ["busca", "notas"]
        estruturados += [
            Plano(tese="t", esboco="e"),
            _draft(),
            ReviewResult(aprovado=False, verificar=["x"]),
        ]

    model = scripted(invoke_texts=textos, structured=estruturados)
    settings = Settings(_env_file=None, max_review_rounds=100, max_passos=12)
    graph = build_graph(model, settings)

    final = graph.invoke({"tema": None, "rounds": 0, "run_dir": tmp_path, "passos": 0})

    assert final["passos"] >= 12
```

Conferir o restante do teste original (depois da linha 120) antes de substituir, e preservar as asserções finais que ele já fazia sobre o orçamento.

Run: `uv run pytest tests/orchestration/test_graph.py -v`
Expected: PASS

- [ ] **Step 9: Remover `ddgs` e o prompt órfão**

```bash
rm src/forge/prompts/fontes.md
```

Em `pyproject.toml`, apagar a linha `"ddgs>=9.0",` de `dependencies`.

Run: `uv sync`
Expected: remove `ddgs` do ambiente

- [ ] **Step 10: Confirmar que nada mais referencia a busca web**

Run: `uv run python -c "import subprocess,sys; sys.exit(subprocess.call(['git','grep','-n','-E','ddgs|buscar_web|web_search|_extrair_fontes|FonteList']))"`
Expected: sem resultado em `src/`. `FonteList` deve sobrar apenas em `domain/models.py:43`; apagar a classe — ela existia só para a extração de fontes por LLM, que morreu no Step 5. Rodar `git grep -n FonteList` antes de apagar para confirmar que nenhum teste ainda a importa.

- [ ] **Step 11: Atualizar o `CLAUDE.md`**

Na seção `### Providers`, substituir a última frase (a que descreve `web_search` server-side e DuckDuckGo client-side) por:

```markdown
A pesquisa não depende mais do provider: todo provider passa pelo mesmo caminho,
o acervo. O que varia entre providers é só o modelo e a chave.
```

Na descrição do grafo, ajustar a linha do nó `research` para dizer que ele consulta o acervo, não a web.

- [ ] **Step 12: Rodar a suíte inteira**

Run: `uv run pytest`
Expected: PASS

- [ ] **Step 13: Commit**

```bash
git add -A
git commit -m "feat: research against the acervo instead of the web

Three phases: the model writes queries, the client searches, the model
synthesizes a brief from what came back. Sources are built from the HTTP
response, never inferred — _extrair_fontes made the model reread its own brief
and reconstruct references from memory, which is where invented citations came
from. Drops ddgs and the anthropic server-side web_search path; research now
behaves identically on every provider.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Verificação de ponta a ponta contra o acervo real

O teste de integração existente é gated por credenciais. Este acrescenta um gate para o acervo, e é a única coisa no plano que toca a rede.

**Files:**
- Modify: `tests/test_integration.py`

**Interfaces:**
- Consumes: `Acervo` (Task 2), `pesquisar` (Task 4).
- Produces: nada consumido por tarefas posteriores.

- [ ] **Step 1: Abrir o arquivo e reusar o padrão de gate existente**

Ler `tests/test_integration.py` e reproduzir o mecanismo de skip que já está lá (marker `integration` declarado em `pyproject.toml`), em vez de inventar outro.

- [ ] **Step 2: Escrever o teste de integração**

Acrescentar a `tests/test_integration.py`:

```python
@pytest.mark.integration
def test_acervo_real_responde_e_devolve_caminho_citavel():
    """Exige o acervo no ar em FORGE_ACERVO_URL. Único teste que usa rede."""
    from forge.infrastructure.config import Settings
    from forge.services.acervo import Acervo

    s = Settings(_env_file=None, anthropic_api_key="sk-test")
    acervo = Acervo(s.acervo_url, timeout=s.acervo_timeout)

    if not acervo.saude():
        pytest.skip(f"acervo fora do ar em {s.acervo_url}")

    passagens = acervo.buscar("livre-arbítrio e determinismo", top=3)

    assert passagens, "acervo no ar mas sem passagens; confira se há livros ingeridos"
    assert all(p.path for p in passagens)
    assert all(p.book_title for p in passagens)
```

- [ ] **Step 3: Rodar com o acervo no ar**

Run: `uv run pytest tests/test_integration.py -m integration -v`
Expected: PASS (ou SKIP com a mensagem do acervo, se ele não estiver rodando)

- [ ] **Step 4: Rodar a suíte padrão e conferir que o teste não roda sozinho**

Run: `uv run pytest`
Expected: PASS, com o teste de integração deselecionado ou skipado — nunca fazendo rede na suíte padrão

- [ ] **Step 5: Rodar o fluxo de verdade**

Run: `uv run forge roteiro --tema "livre-arbítrio e determinismo" --provider lm-studio`
Expected: sai um caminho de `.md` no stdout; abrir `output/runs/<ts>-<slug>/01-research.md` e confirmar que a linha `fontes:` traz `path` e `book_id` preenchidos, e que `01-research.raw.md` lista as queries e as passagens.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "test: add gated integration check against the live acervo

Skips when the acervo is unreachable, so the default suite stays offline.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Cobertura do spec

| Requisito do spec | Tarefa |
|---|---|
| S0 — subcomando `ingest`, `KnowledgeSettings`, extras, `tests/knowledge/`, `docker-compose.yml`, `docs/knowledge.md`, `CLAUDE.md` | Task 1 |
| S1 — `services/acervo.py` com `buscar`/`descobrir`/`saude` | Task 2 |
| S1 — configs `FORGE_ACERVO_URL`, `FORGE_ACERVO_TOP`, `FORGE_ACERVO_TIMEOUT` | Task 2 |
| S1 — `Fonte` ganha `path` e `book_id` | Task 3 |
| S1 — LLM formula 3-5 queries | Task 4, `formular_queries` |
| S1 — uma busca por query, dedupe por `path`, ordem por `score` | Task 4, `colher` |
| S1 — brief cita o caminho canônico | Task 4, `prompts/research.md` |
| S1 — fontes saem das passagens, `_extrair_fontes` morre | Task 4, `_fontes` |
| S1 — lacuna relatada com sugestões do `/discover` | Task 4, `_brief_lacuna` |
| S1 — acervo fora do ar é erro explícito, sem fallback | Task 2, `AcervoIndisponivel` |
| D1 — `ddgs` e `web_search` removidos | Task 4, steps 9-10 |

Fora deste plano, por pertencerem a sub-projetos posteriores: S2 (broker de GPU), S3 (plano de mídia), S4 (manifesto e runner), S5 (narração), S6 (imagens), S7 (montagem). O spike de medição de throughput de imagem vai para o plano que contém S6, onde o resultado tem consequência.
