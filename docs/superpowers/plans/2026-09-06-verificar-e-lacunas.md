# Verificar honesto e realimentação do acervo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parar de queimar uma volta inteira do grafo por roteiro com um `verificar` que não contém alegação nenhuma, e passar a devolver ao acervo as perguntas que ele não soube responder.

**Architecture:** Duas frentes que se encontram no agente de pesquisa. A primeira conserta o revisor: o prompt nunca explicou o que é `verificar`, então o modelo o usa como checklist de autoavaliação e o grafo nunca termina por aprovação. A segunda acrescenta um juiz de relevância entre a busca e a síntese: ele decide quais passagens realmente respondem, e as queries cujas passagens todas foram reprovadas viram lacuna registrada — a pergunta no arquivo do acervo, a evidência completa num arquivo nosso ao lado.

**Tech Stack:** Python 3.12, `uv`, pydantic v2, pydantic-settings, httpx, langchain-core, pytest, structlog.

**Spec:** [docs/superpowers/specs/2026-09-06-video-pipeline-design.md](../specs/2026-09-06-video-pipeline-design.md) — sub-projeto S8, decisões D8 e D9, mais a seção "Medições do primeiro run real completo" que documenta os dois defeitos.

## Global Constraints

- Nomes de domínio, de estado e mensagens de log em português; identificadores de código misturam português e inglês. Casar com o arquivo ao redor.
- Log estruturado com `structlog`: `get_logger(__name__)`, campos `chave=valor`, nunca f-string dentro da chamada de log.
- Nenhum teste toca a rede, a GPU, o LM Studio, o ComfyUI, um binário externo, ou qualquer arquivo fora do `tmp_path` do próprio teste. Modelo é a fixture `scripted`; acervo é a fixture `acervo_fake`; HTTP é `httpx.MockTransport`.
- **Nenhum teste escreve em `C:\dev\research\dados\`.** Os caminhos reais são defaults de `Settings`; todo teste passa `tmp_path`.
- `uv run pytest` roda com `addopts = ["-m", "not integration"]`.
- `docs/superpowers/` está no `.gitignore`. Nunca commitar spec nem plano.
- Escrita em arquivo de outro projeto nunca derruba o roteiro: falha vira log de aviso.
- Toda dependência externa entra por injeção, com o default real montado à parte — padrão que `services/acervo.py` já segue.
- Mensagens de commit em inglês, prefixo `feat:`/`fix:`/`chore:`/`test:`/`docs:`, corpo terminando em `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

## Contexto medido, não suposto

O primeiro run real completo (2026-09-06, 2h, `qwen3.8-9b-distill` na RX 580) produziu isto no artefato `04-review-r2.md`:

```markdown
## Verificar

- Hook sem preâmbulo?
- Sim
- Conclusão transforma Hook?
- Sim (carro volta)
- Zero aspas indevidas?
- Sim
```

Seis itens, zero alegações. Como `rotear` faz `verificar` vencer `aprovado`, o grafo voltou para `research` nas duas rodadas e nunca terminou por aprovação. Cada volta custa ~50 min nesta máquina.

A causa está em [prompts/review.md](../../../src/forge/prompts/review.md): ele **não menciona `verificar` em lugar nenhum**. O campo só existe na descrição do schema `ReviewResult`, e o modelo o preenche por conta própria.

Custo de LLM importa aqui: nesta máquina uma chamada de prompt pequeno custa ~3 min e a síntese de pesquisa custa 15-22 min. O juiz da Task 2 acrescenta uma chamada por passagem de pesquisa; o prompt dele é deliberadamente compacto por isso, e `FORGE_JUIZ_RELEVANCIA=false` desliga.

---

### Task 1: `verificar` volta a significar alegação

**Files:**
- Modify: `src/forge/prompts/review.md`
- Modify: `src/forge/domain/models.py` (descrição do campo `verificar`)
- Modify: `src/forge/agents/review.py`
- Modify: `tests/agents/test_review.py`

**Interfaces:**
- Consumes: `ReviewResult` (já existe).
- Produces: `alegacoes_reais(itens: list[str]) -> list[str]` em `forge.agents.review`, exportada para teste; `revisar` passa a devolver `ReviewResult` com `verificar` já filtrado.

- [ ] **Step 1: Escrever os testes**

Acrescentar a `tests/agents/test_review.py`:

```python
from forge.agents.review import alegacoes_reais


def test_checklist_do_revisor_nao_vira_alegacao():
    """Payload real do run de 2026-09-06 (04-review-r2.md).

    O modelo usa `Verificar` como checklist de autoavaliação. Cada linha virava
    um item, `verificar` nunca esvaziava, e o grafo voltava para research em toda
    rodada — ~50 min por volta nesta máquina.
    """
    itens = [
        "Hook sem preâmbulo?",
        "Sim",
        "Conclusão transforma Hook?",
        "Sim (carro volta)",
        "Zero aspas indevidas?",
        "Sim",
    ]

    assert alegacoes_reais(itens) == []


def test_alegacao_de_verdade_sobrevive():
    itens = [
        "Bergson afirma em Time and Free Will que a duração não é mensurável.",
        "Leibniz chamou o poder sobre a vontade de oblíquo na Teodiceia.",
    ]

    assert alegacoes_reais(itens) == itens


def test_afirmacao_solta_e_pergunta_caem_mas_o_resto_fica():
    itens = [
        "Sim",
        "não",
        "  ",
        "O roteiro atribui a Hume a definição de liberdade como ausência de coação?",
        "Hume define liberdade como ausência de coação externa.",
    ]

    assert alegacoes_reais(itens) == ["Hume define liberdade como ausência de coação externa."]


def test_revisar_entrega_verificar_ja_filtrado(scripted):
    from forge.domain.models import ReviewResult, Roteiro, Secao
    from forge.agents.review import revisar

    bruto = ReviewResult(aprovado=True, verificar=["Hook sem preâmbulo?", "Sim"])
    model = scripted(structured=[bruto])
    roteiro = Roteiro(tema="t", tese="t", secoes=[Secao(nome="Hook", conteudo="c")])

    resultado = revisar(model, roteiro)

    assert resultado.verificar == []
    assert resultado.aprovado is True
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/agents/test_review.py -v`
Expected: FAIL com `ImportError: cannot import name 'alegacoes_reais'`

- [ ] **Step 3: Dizer ao revisor o que é `verificar`**

Substituir `src/forge/prompts/review.md` inteiro por:

```markdown
Revise este roteiro contra os critérios abaixo.

{skills}

Aprove (aprovado=true) somente se o roteiro passa em todos. Caso contrário,
aprovado=false e liste notas objetivas: dimensão, problema, sugestão.

## O campo `verificar`

`verificar` NÃO é a sua lista de conferência. Não escreva nele perguntas sobre o
seu próprio trabalho, nem respostas como "Sim" ou "OK".

Ele existe para uma coisa só: afirmações de fato que o roteiro faz e que você não
consegue confirmar com o material de pesquisa em mãos. Cada item é uma frase
afirmativa, completa, que alguém poderia ir conferir numa fonte — quem disse o
quê, em que obra, em que ano, com que número.

Exemplos do que entra:

- Bergson afirma em Time and Free Will que a duração não é mensurável.
- Leibniz chamou de oblíquo o poder que temos sobre a própria vontade.

Exemplos do que NUNCA entra: "Hook sem preâmbulo?", "Sim", "Zero aspas
indevidas?", "Conclusão transforma Hook?".

Cada item que você põe aqui manda o roteiro de volta para uma nova rodada de
pesquisa, que custa caro. Se não há nenhuma afirmação factual duvidosa, devolva
`verificar` vazio — essa é a resposta normal e esperada.

Roteiro:
{roteiro}
```

- [ ] **Step 4: Apertar a descrição do campo no schema**

Em `src/forge/domain/models.py`, no `ReviewResult`:

```python
    verificar: list[str] = Field(
        default_factory=list,
        description=(
            "Afirmações de fato do roteiro que você não conseguiu confirmar. "
            "Frases afirmativas e completas, nunca perguntas nem respostas de "
            "conferência. Vazio é a resposta normal."
        ),
    )
```

O modelo lê essa descrição mesmo quando o prompt cala; era a única instrução que ele tinha antes.

- [ ] **Step 5: Filtrar o que o modelo insiste em mandar**

Em `src/forge/agents/review.py`, acrescentar a função e chamá-la em `revisar`:

```python
# Palavras que o modelo emite como resposta de checklist. Um item que é só isso
# nunca foi uma alegação.
_RESPOSTAS = {"sim", "nao", "não", "ok", "n/a", "na", "nenhum", "nenhuma", "-"}


def alegacoes_reais(itens: list[str]) -> list[str]:
    """Descarta o que não é alegação factual.

    O prompt já pede afirmações, mas o modelo local reincide no checklist, e cada
    item falso manda o roteiro para outra volta de pesquisa (~50 min nesta
    máquina). Três regras, todas conservadoras: o que sobra tem de ser uma frase
    afirmativa com algum conteúdo.
    """
    mantidas: list[str] = []
    for bruto in itens:
        item = bruto.strip()
        chave = item.casefold().rstrip(".!").strip()
        if not item:
            continue
        if chave in _RESPOSTAS:
            logger.debug("Item de verificar descartado: resposta de checklist", item=item)
            continue
        if item.endswith("?"):
            # Uma pergunta é a metade errada de um checklist: alegação é
            # afirmação, e o prompt agora pede exatamente isso.
            logger.debug("Item de verificar descartado: pergunta", item=item)
            continue
        if len(item.split()) < 3:
            logger.debug("Item de verificar descartado: curto demais", item=item)
            continue
        mantidas.append(item)
    return mantidas
```

Em `revisar`, depois do `invoke` e antes do log:

```python
    filtradas = alegacoes_reais(result.verificar)
    if len(filtradas) != len(result.verificar):
        logger.info(
            "Itens de verificar descartados",
            descartados=len(result.verificar) - len(filtradas),
            mantidos=len(filtradas),
        )
    result.verificar = filtradas
```

- [ ] **Step 6: Rodar e ver passar**

Run: `uv run pytest tests/agents/test_review.py -v`
Expected: PASS

- [ ] **Step 7: Rodar a suíte**

Run: `uv run pytest`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "fix: make the reviewer's verificar mean a factual claim again

The review prompt never mentioned `verificar`, so the model filled it from the
schema description alone and used it as a self-checklist — six items of
\"Hook sem preâmbulo?\" / \"Sim\" in the first real run. Since verificar beats
aprovado in the router, the graph never terminated by approval and burned an
extra research round (~50 min on this hardware) per script. The prompt now says
what the field is for, and a conservative filter drops questions and bare
checklist answers the model still emits.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Juiz de relevância

**Files:**
- Create: `src/forge/prompts/juiz.md`
- Modify: `src/forge/agents/research.py`
- Modify: `src/forge/domain/models.py` (modelo `VeredictoRelevancia`)
- Modify: `src/forge/infrastructure/config.py`
- Modify: `tests/agents/test_research.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: `Passagem` (`services/acervo.py`), `colher` (`agents/research.py`).
- Produces:
  - `class VeredictoRelevancia(BaseModel)` com `relevantes: list[int]` e `motivo: str` em `forge.domain.models`
  - `julgar_relevancia(model, tema: str, passagens: list[Passagem]) -> tuple[list[Passagem], str]` em `forge.agents.research` — devolve as passagens aprovadas e o motivo dado pelo juiz
  - `colher_por_query(acervo, queries: list[str], *, top: int = 8) -> dict[str, list[Passagem]]`
  - `Settings.juiz_relevancia: bool = True`

- [ ] **Step 1: Escrever os testes**

Acrescentar a `tests/agents/test_research.py` (o arquivo já tem o helper `_passagem` e usa a fixture `acervo_fake`):

```python
def test_juiz_mantem_so_as_passagens_aprovadas(scripted):
    from forge.agents.research import julgar_relevancia
    from forge.domain.models import VeredictoRelevancia

    passagens = [_passagem("p1", 0.9), _passagem("p2", 0.8), _passagem("p3", 0.7)]
    model = scripted(structured=[
        VeredictoRelevancia(relevantes=[0, 2], motivo="a segunda fala de outro assunto")
    ])

    aprovadas, motivo = julgar_relevancia(model, "vontade", passagens)

    assert [p.path for p in aprovadas] == ["p1", "p3"]
    assert "outro assunto" in motivo


def test_juiz_ignora_indice_fora_da_lista(scripted):
    """Índice inventado pelo modelo não pode estourar nem trazer passagem errada."""
    from forge.agents.research import julgar_relevancia
    from forge.domain.models import VeredictoRelevancia

    passagens = [_passagem("p1", 0.9)]
    model = scripted(structured=[VeredictoRelevancia(relevantes=[0, 7, -3], motivo="")])

    aprovadas, _ = julgar_relevancia(model, "vontade", passagens)

    assert [p.path for p in aprovadas] == ["p1"]


def test_colher_por_query_preserva_a_origem(acervo_fake):
    from forge.agents.research import colher_por_query

    acervo = acervo_fake(por_query={
        "a": [_passagem("p1", 0.5), _passagem("p2", 0.9)],
        "b": [_passagem("p1", 0.8)],
    })

    por_query = colher_por_query(acervo, ["a", "b"])

    assert [p.path for p in por_query["a"]] == ["p1", "p2"]
    assert [p.path for p in por_query["b"]] == ["p1"]
```

Acrescentar a `tests/test_config.py`:

```python
def test_juiz_de_relevancia_vem_ligado():
    from forge.infrastructure.config import Settings

    assert Settings(_env_file=None).juiz_relevancia is True
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/agents/test_research.py tests/test_config.py -v`
Expected: FAIL com `ImportError`/`AttributeError`

- [ ] **Step 3: Modelo do veredicto**

Em `src/forge/domain/models.py`:

```python
class VeredictoRelevancia(BaseModel):
    """Quais passagens do acervo realmente respondem ao que se perguntou.

    Índices, não caminhos: pedir ao modelo que copie `4363/ch2/p7` corretamente é
    convidar erro de transcrição; um número ele acerta.
    """

    relevantes: list[int] = Field(default_factory=list)
    motivo: str = ""
```

- [ ] **Step 4: Prompt do juiz**

Criar `src/forge/prompts/juiz.md`. Deliberadamente compacto: nesta máquina cada chamada custa minutos, e o juiz roda em toda passagem de pesquisa.

```markdown
Um acervo de livros devolveu as passagens abaixo para este assunto:

{tema}

Diga quais delas realmente ajudam a falar sobre esse assunto. Busca semântica
erra: uma passagem pode ter vindo com pontuação alta e ser sobre outra coisa.

Responda com os índices das passagens que servem, e uma frase curta dizendo o que
as descartadas tinham de errado. Se nenhuma servir, devolva a lista vazia — é uma
resposta legítima e útil.

{passagens}
```

- [ ] **Step 5: Implementar o juiz e a colheita por query**

Em `src/forge/agents/research.py`:

```python
def colher_por_query(
    acervo: Acervo, queries: list[str], *, top: int = 8
) -> dict[str, list[Passagem]]:
    """Busca cada query preservando de qual delas veio cada passagem.

    `colher` funde tudo num pool ordenado, que é o que a síntese quer. A origem
    importa para outra coisa: saber qual pergunta o acervo não soube responder.
    """
    return {q: acervo.buscar(q, top=top) for q in queries}


def _fmt_passagens_curtas(passagens: list[Passagem], *, chars: int = 200) -> str:
    """Só o suficiente para julgar pertinência — o texto inteiro custaria minutos."""
    linhas = []
    for i, p in enumerate(passagens):
        autores = ", ".join(p.authors) or "autor não identificado"
        trecho = p.text[:chars].replace("\n", " ")
        linhas.append(f"[{i}] {p.book_title} — {autores} — {p.breadcrumb}\n{trecho}")
    return "\n\n".join(linhas)


def julgar_relevancia(
    model, tema: str, passagens: list[Passagem]
) -> tuple[list[Passagem], str]:
    prompt = load_prompt("juiz").format(
        tema=tema, passagens=_fmt_passagens_curtas(passagens)
    )
    veredicto = model.with_structured_output(VeredictoRelevancia).invoke(
        [HumanMessage(content=prompt)]
    )
    # Índice fora da faixa é erro de modelo, não motivo para estourar: descarta.
    validos = sorted({i for i in veredicto.relevantes if 0 <= i < len(passagens)})
    aprovadas = [passagens[i] for i in validos]
    logger.info(
        "Juiz de relevância",
        recebidas=len(passagens),
        aprovadas=len(aprovadas),
    )
    return aprovadas, veredicto.motivo
```

Acrescentar `VeredictoRelevancia` ao import de `forge.domain.models` no topo do arquivo.

- [ ] **Step 6: Config**

Em `src/forge/infrastructure/config.py`:

```python
    # O juiz custa uma chamada de LLM por passagem de pesquisa (~3 min nesta
    # máquina). Desligar troca a detecção de lacuna por velocidade.
    juiz_relevancia: bool = True
```

- [ ] **Step 7: Rodar e ver passar**

Run: `uv run pytest tests/agents/test_research.py tests/test_config.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: add a relevance judge over acervo passages

Semantic search returns high-scoring passages that are about something else.
The judge answers by index rather than by canonical path, because a model
transcribing `4363/ch2/p7` will eventually get it wrong and a number it will
not. Its prompt carries only titles, breadcrumbs and a 200-char excerpt: on this
hardware every call costs minutes, and this one runs on every research pass.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Registro de lacunas

**Files:**
- Create: `src/forge/services/lacunas.py`
- Create: `tests/services/test_lacunas.py`
- Modify: `src/forge/infrastructure/config.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Consumes: `Passagem` (`services/acervo.py`), `Settings`.
- Produces:
  - `registrar_lacuna(settings, *, query: str, tema: str, motivo: str, passagens: list[Passagem]) -> None`
  - `Settings.gaps_file: Path | None`, `Settings.respostas_ruins_file: Path | None`

- [ ] **Step 1: Escrever os testes**

Criar `tests/services/test_lacunas.py`:

```python
import json

from forge.infrastructure.config import Settings
from forge.services.acervo import Passagem
from forge.services.lacunas import registrar_lacuna


def _settings(tmp_path):
    return Settings(
        _env_file=None,
        gaps_file=tmp_path / "unanswered_questions.txt",
        respostas_ruins_file=tmp_path / "respostas_ruins.jsonl",
    )


def _passagem(path="4363/ch2/p7"):
    return Passagem(
        path=path, book_id=4363, book_title="Beyond Good and Evil",
        authors=["Nietzsche"], breadcrumb="Cap 2", text="trecho longo " * 40,
        url="http://acervo.test/books/4363", score=0.81,
    )


def test_grava_so_a_pergunta_no_arquivo_do_acervo(tmp_path):
    """O acervo lê esse arquivo de volta e dedupe por linha exata.

    Ver unanswered_log.py do projeto research: 'Holds ONLY the question, no
    duplicates'. Escrever o par pergunta/resposta ali quebraria o dedupe dele.
    """
    s = _settings(tmp_path)

    registrar_lacuna(s, query="vontade em Nietzsche", tema="vontade",
                     motivo="passagens sobre outro assunto", passagens=[_passagem()])

    linhas = s.gaps_file.read_text(encoding="utf-8").splitlines()
    assert linhas == ["vontade em Nietzsche"]


def test_nao_duplica_pergunta_ja_registrada(tmp_path):
    s = _settings(tmp_path)
    s.gaps_file.write_text("vontade em Nietzsche\n", encoding="utf-8")

    registrar_lacuna(s, query="  vontade   em Nietzsche  ", tema="vontade",
                     motivo="", passagens=[])

    assert s.gaps_file.read_text(encoding="utf-8") == "vontade em Nietzsche\n"


def test_evidencia_completa_vai_para_o_arquivo_nosso(tmp_path):
    s = _settings(tmp_path)

    registrar_lacuna(s, query="vontade em Nietzsche", tema="vontade de potência",
                     motivo="fala de moral, não de vontade", passagens=[_passagem()])

    registro = json.loads(s.respostas_ruins_file.read_text(encoding="utf-8").strip())
    assert registro["query"] == "vontade em Nietzsche"
    assert registro["tema"] == "vontade de potência"
    assert registro["motivo"] == "fala de moral, não de vontade"
    assert registro["passagens"][0]["path"] == "4363/ch2/p7"
    assert registro["passagens"][0]["book_title"] == "Beyond Good and Evil"
    assert registro["passagens"][0]["score"] == 0.81
    assert len(registro["passagens"][0]["trecho"]) <= 300
    assert registro["ts"]


def test_duas_lacunas_viram_duas_linhas_jsonl(tmp_path):
    s = _settings(tmp_path)

    registrar_lacuna(s, query="a", tema="t", motivo="", passagens=[])
    registrar_lacuna(s, query="b", tema="t", motivo="", passagens=[])

    linhas = s.respostas_ruins_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(linhas) == 2
    assert json.loads(linhas[1])["query"] == "b"


def test_caminho_impossivel_nao_derruba_o_roteiro(tmp_path):
    """Arquivo de outro projeto pode não existir ou estar sem permissão.

    Perder o registro é ruim; perder o roteiro por causa dele é pior.
    """
    s = Settings(
        _env_file=None,
        gaps_file=tmp_path / "sem" / "essa" / "pasta" / "x.txt",
        respostas_ruins_file=tmp_path / "sem" / "essa" / "pasta" / "y.jsonl",
    )
    s.gaps_file.parent.mkdir(parents=True)
    s.gaps_file.parent.chmod(0o500)
    try:
        registrar_lacuna(s, query="q", tema="t", motivo="", passagens=[])
    finally:
        s.gaps_file.parent.chmod(0o700)


def test_registro_desligado_quando_o_caminho_e_none(tmp_path):
    s = Settings(_env_file=None, gaps_file=None, respostas_ruins_file=None)

    registrar_lacuna(s, query="q", tema="t", motivo="", passagens=[])  # não levanta
```

Nota para quem implementa: `chmod` no Windows não impede escrita como no POSIX, então `test_caminho_impossivel_nao_derruba_o_roteiro` pode não exercitar a permissão de fato. Ele ainda vale como garantia de que a função não estoura. Se quiser um teste que discrimine de verdade nesta plataforma, monkeypatche `Path.open` (ou o `open` do módulo) para levantar `OSError` e assere que `registrar_lacuna` retorna normalmente — faça isso e diga no relatório qual dos dois você usou.

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/services/test_lacunas.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'forge.services.lacunas'`

- [ ] **Step 3: Config dos dois caminhos**

Em `src/forge/infrastructure/config.py`:

```python
    # Realimentação do acervo. O primeiro arquivo é DELE: guarda só a pergunta,
    # uma por linha, sem duplicata, e o próprio acervo o lê de volta
    # (ver unanswered_log.py no projeto research). A evidência completa vai no
    # segundo, que é nosso e ninguém lê de volta. `None` desliga.
    gaps_file: Path | None = Path(r"C:\dev\research\dados\unanswered_questions.txt")
    respostas_ruins_file: Path | None = Path(r"C:\dev\research\dados\respostas_ruins.jsonl")
```

Acrescentar a `tests/test_config.py`:

```python
def test_arquivos_de_lacuna_apontam_para_o_acervo():
    from forge.infrastructure.config import Settings

    s = Settings(_env_file=None)
    assert s.gaps_file is not None and s.gaps_file.name == "unanswered_questions.txt"
    assert s.respostas_ruins_file is not None
    assert s.respostas_ruins_file.suffix == ".jsonl"
```

- [ ] **Step 4: Implementar**

Criar `src/forge/services/lacunas.py`:

```python
"""Devolve ao acervo as perguntas que ele não soube responder.

Duas escritas com contratos diferentes, e misturá-las quebraria o acervo:

- `gaps_file` é ARQUIVO DO ACERVO. Segundo o `unanswered_log.py` daquele
  projeto, ele guarda "ONLY the question, no duplicates", uma por linha, e o
  próprio acervo o lê de volta. Escrever o par pergunta/resposta ali destruiria
  o dedupe dele.
- `respostas_ruins_file` é nosso. Guarda a evidência inteira, uma linha JSON por
  caso, e ninguém o lê de volta.

Falhar aqui nunca derruba o roteiro: um caminho inexistente ou sem permissão é
um aviso. Perder o registro é ruim; perder o roteiro por causa dele é pior.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from forge.infrastructure.config import Settings
from forge.infrastructure.logging import get_logger
from forge.services.acervo import Passagem

logger = get_logger(__name__)

TRECHO_MAX = 300


def registrar_lacuna(
    settings: Settings,
    *,
    query: str,
    tema: str,
    motivo: str,
    passagens: list[Passagem],
) -> None:
    pergunta = " ".join(query.split())
    if not pergunta:
        return
    _anexar_pergunta(settings.gaps_file, pergunta)
    _anexar_evidencia(settings.respostas_ruins_file, pergunta, tema, motivo, passagens)


def _anexar_pergunta(caminho: Path | None, pergunta: str) -> None:
    if caminho is None:
        return
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        existentes = set()
        if caminho.exists():
            existentes = {
                linha.strip()
                for linha in caminho.read_text(encoding="utf-8").splitlines()
                if linha.strip()
            }
        if pergunta in existentes:
            return
        with caminho.open("a", encoding="utf-8") as arquivo:
            arquivo.write(pergunta + "\n")
        logger.info("Lacuna registrada no acervo", pergunta=pergunta)
    except OSError as e:
        logger.warning("Não foi possível registrar a lacuna",
                       path=str(caminho), error=str(e))


def _anexar_evidencia(
    caminho: Path | None,
    pergunta: str,
    tema: str,
    motivo: str,
    passagens: list[Passagem],
) -> None:
    if caminho is None:
        return
    registro = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tema": tema,
        "query": pergunta,
        "motivo": motivo,
        "passagens": [
            {
                "path": p.path,
                "book_title": p.book_title,
                "score": p.score,
                "trecho": p.text[:TRECHO_MAX],
            }
            for p in passagens
        ],
    }
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        with caminho.open("a", encoding="utf-8") as arquivo:
            arquivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
    except OSError as e:
        logger.warning("Não foi possível gravar a evidência da lacuna",
                       path=str(caminho), error=str(e))
```

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest tests/services/test_lacunas.py tests/test_config.py -v`
Expected: PASS

- [ ] **Step 6: Confirmar que nenhum teste escreveu no projeto research**

Run: `git -C C:/dev/research status --short`
Expected: `dados/unanswered_questions.txt` NÃO aparece modificado. Se aparecer, algum teste usou o default em vez de `tmp_path` — corrigir antes de commitar.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: report acervo gaps back to the acervo

Two writes with different contracts. The acervo's own file takes the question
only, deduplicated, because that project reads it back and dedupes by exact
line; writing a question/answer pair there would break it. The full evidence
goes to a jsonl beside it that nobody reads back. Neither write can fail the
script: a missing directory is a warning.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Fiação — pesquisa julga, registra e reporta a lacuna

**Files:**
- Modify: `src/forge/agents/research.py`
- Modify: `src/forge/orchestration/graph.py`
- Modify: `tests/agents/test_research.py`, `tests/orchestration/test_graph.py`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: `julgar_relevancia`, `colher_por_query` (Task 2); `registrar_lacuna` (Task 3).
- Produces: `pesquisar(model, tema, acervo, pedido=None, *, top=None, settings=None) -> tuple[str, list[Fonte], str]` — mesma forma de retorno, novo parâmetro opcional `settings`. Sem `settings`, nada é registrado e o juiz não roda; é o que mantém os testes existentes válidos.

- [ ] **Step 1: Escrever os testes**

Acrescentar a `tests/agents/test_research.py`:

```python
def test_query_toda_reprovada_vira_lacuna_registrada(scripted, acervo_fake, tmp_path):
    from forge.agents.research import pesquisar
    from forge.domain.models import VeredictoRelevancia
    from forge.infrastructure.config import Settings

    s = Settings(
        _env_file=None,
        gaps_file=tmp_path / "gaps.txt",
        respostas_ruins_file=tmp_path / "ruins.jsonl",
    )
    acervo = acervo_fake(por_query={
        "boa": [_passagem("p1", 0.9)],
        "ruim": [_passagem("p2", 0.8)],
    })
    model = scripted(
        invoke_texts=["boa\nruim", "notas densas"],
        structured=[VeredictoRelevancia(relevantes=[0], motivo="a segunda é de outro assunto")],
    )

    brief, fontes, _ = pesquisar(model, "vontade", acervo, settings=s)

    assert brief == "notas densas"
    assert [f.path for f in fontes] == ["p1"]
    assert s.gaps_file.read_text(encoding="utf-8").splitlines() == ["ruim"]


def test_tudo_reprovado_vira_brief_de_lacuna_sem_sintetizar(scripted, acervo_fake, tmp_path):
    """Sem passagem aprovada não há o que sintetizar — e a síntese é a chamada
    mais cara do pipeline (15-22 min nesta máquina)."""
    from forge.agents.research import pesquisar
    from forge.domain.models import VeredictoRelevancia
    from forge.infrastructure.config import Settings
    from forge.services.acervo import Candidato

    s = Settings(_env_file=None, gaps_file=tmp_path / "gaps.txt",
                 respostas_ruins_file=tmp_path / "ruins.jsonl")
    acervo = acervo_fake(
        por_query={"ruim": [_passagem("p1", 0.9)]},
        candidatos=[Candidato(id=37358, title="Determinism or Free-Will?", authors=["Cohen"])],
    )
    # Só duas respostas na fila: queries e veredicto. Se o agente tentar
    # sintetizar, o modelo falso estoura — que é o que este teste tranca.
    model = scripted(
        invoke_texts=["ruim"],
        structured=[VeredictoRelevancia(relevantes=[], motivo="nada sobre o tema")],
    )

    brief, fontes, _ = pesquisar(model, "vontade", acervo, settings=s)

    assert fontes == []
    assert "Lacuna no acervo" in brief
    assert "Determinism or Free-Will?" in brief
    assert s.gaps_file.read_text(encoding="utf-8").splitlines() == ["ruim"]


def test_sem_settings_o_juiz_nao_roda(scripted, acervo_fake):
    """Chamada sem settings mantém o comportamento antigo — é o que os testes
    existentes e qualquer chamador antigo esperam."""
    from forge.agents.research import pesquisar

    acervo = acervo_fake(por_query={"q": [_passagem("p1", 0.9)]})
    model = scripted(invoke_texts=["q", "notas"])

    brief, fontes, _ = pesquisar(model, "vontade", acervo)

    assert brief == "notas"
    assert len(fontes) == 1


def test_juiz_desligado_por_config(scripted, acervo_fake, tmp_path):
    from forge.agents.research import pesquisar
    from forge.infrastructure.config import Settings

    s = Settings(_env_file=None, juiz_relevancia=False,
                 gaps_file=tmp_path / "gaps.txt",
                 respostas_ruins_file=tmp_path / "ruins.jsonl")
    acervo = acervo_fake(por_query={"q": [_passagem("p1", 0.9)]})
    model = scripted(invoke_texts=["q", "notas"])

    brief, fontes, _ = pesquisar(model, "vontade", acervo, settings=s)

    assert brief == "notas"
    assert not s.gaps_file.exists()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/agents/test_research.py -v`
Expected: FAIL — `pesquisar` ainda não aceita `settings`

- [ ] **Step 3: Reescrever `pesquisar`**

Em `src/forge/agents/research.py`, substituir o corpo de `pesquisar`:

```python
def pesquisar(
    model,
    tema: str,
    acervo: Acervo,
    pedido: str | None = None,
    *,
    top: int | None = None,
    settings=None,
) -> tuple[str, list[Fonte], str]:
    queries = formular_queries(model, tema, pedido)
    por_query = (
        colher_por_query(acervo, queries, top=top)
        if top is not None
        else colher_por_query(acervo, queries)
    )
    passagens = _fundir(por_query)
    bruto = _bruto(queries, passagens)

    if passagens and settings is not None and settings.juiz_relevancia:
        passagens = _julgar_e_registrar(model, tema, passagens, por_query, settings)

    if not passagens:
        candidatos = acervo.descobrir(tema)
        logger.warning("Acervo gap", tema=tema, sugestoes=len(candidatos))
        return _brief_lacuna(tema, candidatos), [], bruto

    brief = _sintetizar(model, tema, pedido, passagens)
    logger.info("Research completed", queries=len(queries), passagens=len(passagens))
    return brief, _fontes(passagens), bruto


def _julgar_e_registrar(model, tema, passagens, por_query, settings):
    """Filtra pelo juiz e devolve ao acervo as queries que não renderam nada.

    A lacuna é por QUERY, não pelo tema: é a pergunta específica que o acervo não
    soube responder, e é ela que diz qual obra falta ingerir.
    """
    # Import tardio: `lacunas` importa `Settings`, e o agente de pesquisa não
    # depende de config em lugar nenhum além daqui.
    from forge.services.lacunas import registrar_lacuna

    aprovadas, motivo = julgar_relevancia(model, tema, passagens)
    caminhos_ok = {p.path for p in aprovadas}
    for query, achadas in por_query.items():
        if achadas and not any(p.path in caminhos_ok for p in achadas):
            registrar_lacuna(
                settings, query=query, tema=tema, motivo=motivo, passagens=achadas
            )
    return aprovadas


def _fundir(por_query: dict[str, list[Passagem]]) -> list[Passagem]:
    """Dedupe por path guardando o maior score, ordenado por relevância.

    A mesma passagem costuma responder a mais de uma query; guardar a última
    vista destruiria a ordenação.
    """
    por_path: dict[str, Passagem] = {}
    for achadas in por_query.values():
        for p in achadas:
            atual = por_path.get(p.path)
            if atual is None or p.score > atual.score:
                por_path[p.path] = p
    return sorted(por_path.values(), key=lambda p: p.score, reverse=True)
```

Reescrever `colher` para delegar, mantendo a assinatura pública que os testes existentes usam:

```python
def colher(acervo: Acervo, queries: list[str], *, top: int = 8) -> list[Passagem]:
    return _fundir(colher_por_query(acervo, queries, top=top))
```

- [ ] **Step 4: Passar `settings` no grafo**

Em `src/forge/orchestration/graph.py`, dentro de `node_research`, acrescentar `settings=settings` à chamada de `research_stage.pesquisar`. `settings` já está no escopo de `build_graph`.

- [ ] **Step 5: Rodar tudo**

Run: `uv run pytest`
Expected: PASS. Os testes de grafo alimentam a fila do modelo roteirizado; com o juiz ligado, cada passagem por `research` passa a consumir **um item estruturado a mais** (o `VeredictoRelevancia`). Ajustar `tests/orchestration/test_graph.py`: ou acrescentar um `VeredictoRelevancia(relevantes=[0])` por ciclo às filas, ou construir o `Settings` daqueles testes com `juiz_relevancia=False`. Preferir a segunda: aqueles testes existem para exercitar o roteamento do grafo, não o juiz, e a fila deles já é longa.

- [ ] **Step 6: Conferir que nada foi escrito no projeto research**

Run: `git -C C:/dev/research status --short`
Expected: nada modificado em `dados/`.

- [ ] **Step 7: Atualizar o `CLAUDE.md`**

Na seção `### Acervo`, acrescentar ao fim:

```markdown
Depois da busca, um juiz de relevância (`FORGE_JUIZ_RELEVANCIA`, ligado por
padrão) decide quais passagens realmente respondem — busca semântica devolve
pontuação alta para material fora de assunto. Uma query cujas passagens foram
todas reprovadas vira lacuna: a pergunta é anexada ao
`unanswered_questions.txt` do acervo (só a pergunta, deduplicada — aquele
projeto lê o arquivo de volta) e a evidência completa vai para
`respostas_ruins.jsonl` ao lado. Nenhuma das duas escritas pode derrubar o
roteiro.
```

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: judge acervo results and report failed queries as gaps

Research now filters passages through the relevance judge before paying for
synthesis — the most expensive call in the pipeline — and a query whose every
passage was rejected is reported back to the acervo. The gap is per query, not
per theme: the specific question is what tells you which book is missing.
Passing settings is optional so existing callers keep the old behaviour.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Cobertura do spec

| Requisito | Tarefa |
|---|---|
| Defeito medido: `Verificar` usado como checklist | Task 1 |
| D8 — LLM julga se as passagens respondem | Task 2 |
| D8 — nenhuma serve ⇒ mesmo caminho de `_brief_lacuna` | Task 4 |
| D9 — só a pergunta no arquivo do acervo, com dedupe | Task 3 |
| D9 — evidência completa em `respostas_ruins.jsonl` | Task 3 |
| S8 — escrita tolerante a falha, nunca derruba o roteiro | Task 3 |
| S8 — `FORGE_JUIZ_RELEVANCIA`, `FORGE_GAPS_FILE`, `FORGE_RESPOSTAS_RUINS_FILE` | Tasks 2 e 3 |

Fora deste plano: S5 (narração), S6 (imagens), S7 (montagem), S9 (canal autônomo), e o requisito de S9 de sobreviver a um descarregamento externo do modelo.
