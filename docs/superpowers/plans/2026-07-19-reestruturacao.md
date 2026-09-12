# Reestruturação de `src/forge` — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganizar `src/forge` conforme a "Estrutura sugerida" do documento de arquitetura, e fechar as lacunas de V1 que a reorganização expõe: skills, isolamento de state por agente, artefatos por run e handoff dinâmico.

**Architecture:** Quatro fases sequenciais. A fase 1 é movimentação pura sem mudança de comportamento. As fases 2-4 constroem em cima: subsistema de skills com corte de `## Procedimento` por dono; artefatos em `output/runs/` com contrato curado separado do bruto; handoff dinâmico limitado a três rotas, com orçamento global de passos garantindo terminação.

**Tech Stack:** Python 3.12+, uv, LangGraph 1.x, langchain-core, Pydantic v2, pydantic-settings, structlog, pytest.

**Spec:** `docs/superpowers/specs/2026-07-19-reestruturacao-design.md`

## Global Constraints

- **NUNCA rodar `git add` nem `git commit`.** Restrição explícita do usuário. Nenhuma tarefa deste plano commita. As etapas de verificação substituem as de commit.
- **Nenhuma dependência nova.** O parse de frontmatter é feito à mão; não adicionar `pyyaml`.
- Python `>=3.12`. Rodar tudo por `uv run`.
- `langgraph>=1.2,<2`, `langchain-core>=1.4,<2`, `pydantic>=2.7`.
- Prompts, skills e artefatos em português. Identificadores de código seguem o padrão existente (mistura de português e inglês — não normalizar).
- **Não corrigir** os defeitos do branch OpenAI em `llms/model.py` (`model` hardcoded, fallback de `api_key`). Estão fora de escopo por decisão registrada no spec.
- **Política de testes:** a Tarefa 1 atualiza os imports da suíte existente (higiene da movimentação, não é escrever teste). As Tarefas 2-7 e 9 não ganham cobertura nova. A Tarefa 8 inclui um único teste — terminação por orçamento — porque um defeito ali queima crédito de API silenciosamente.

**Desvio consciente do spec:** o spec descreve o seletor de skills de domínio como "implementado e dormente". Este plano cria apenas o campo `skills_dominio` no state (Tarefa 5) e **nenhum código de seleção**. Como as quatro skills iniciais são todas `dominio: false`, um seletor hoje seria código morto — nada a selecionar, nenhuma chamada a fazer. Ele entra junto da primeira skill de domínio, que é quando passa a ter comportamento observável.

---

## Estrutura de Arquivos

**Criados:**

| Arquivo | Responsabilidade |
| --- | --- |
| `src/forge/llms/parsing.py` | `_texto()` — desempacota blocos de conteúdo da resposta do LLM |
| `src/forge/skills/loader.py` | Carrega skills `.md`, corta `## Procedimento` por dono |
| `src/forge/skills/fact_check.md` | Critérios de citação (dono: `research`) |
| `src/forge/skills/retention.md` | Critérios de retenção (dono: `write`) |
| `src/forge/skills/writing.md` | Critérios de voz e escrita (dono: `write`) |
| `src/forge/skills/story.md` | Critérios de avanço narrativo (dono: `plan`) |
| `src/forge/services/artefatos.py` | Grava e lê artefatos de run |

**Movidos** (14 arquivos + 6 prompts `.md`):

| De | Para |
| --- | --- |
| `writer/tema.py` | `agents/tema.py` |
| `writer/research.py` | `agents/research.py` |
| `writer/plan.py` | `agents/plan.py` |
| `writer/write.py` | `agents/write.py` |
| `writer/review.py` | `agents/review.py` |
| `writer/models.py` | `domain/models.py` |
| `writer/_prompts.py` | `prompts/loader.py` |
| `writer/prompts/*.md` | `prompts/*.md` |
| `orchestrator/graph.py` | `orchestration/graph.py` |
| `orchestrator/state.py` | `orchestration/state.py` |
| `llm/model.py` | `llms/model.py` |
| `output/storage.py` | `services/storage.py` |
| `config.py` | `infrastructure/config.py` |
| `logging.py` | `infrastructure/logging.py` |
| `tests/writer/` | `tests/agents/` |
| `tests/orchestrator/` | `tests/orchestration/` |

**Removidos:** `src/forge/writer/`, `src/forge/orchestrator/`, `src/forge/llm/`, `src/forge/output/`.

---

## Tarefa 1: Movimentação da árvore

Movimentação mecânica. Zero mudança de comportamento — a suíte existente deve passar igual, e `forge roteiro` deve produzir a mesma saída.

Não é divisível: um repositório meio-movido não importa.

**Files:**
- Create: `src/forge/agents/__init__.py`, `src/forge/orchestration/__init__.py`, `src/forge/domain/__init__.py`, `src/forge/llms/__init__.py`, `src/forge/prompts/__init__.py`, `src/forge/services/__init__.py`, `src/forge/infrastructure/__init__.py` (todos vazios)
- Create: `src/forge/llms/parsing.py`
- Move: os 14 arquivos + 6 prompts da tabela acima
- Modify: `src/forge/prompts/loader.py` (caminho do `files()`)
- Modify: `src/forge/agents/tema.py` (remove `_texto`, importa de `llms.parsing`)
- Modify: todos os arquivos com `from forge.<antigo>`
- Modify: todos os arquivos em `tests/`

**Interfaces:**
- Consumes: nada (primeira tarefa)
- Produces: os módulos nos caminhos novos. Assinaturas públicas **inalteradas**: `gerar_tema(model, tema=None) -> str`, `pesquisar(model, tema, provider="anthropic") -> tuple[str, list[Fonte]]`, `planejar(model, tema, research) -> tuple[str, str]`, `escrever(model, tema, tese, esboco, research, fontes, notas=None) -> Roteiro`, `revisar(model, roteiro) -> ReviewResult`, `build_graph(model, settings)`, `gravar_roteiro(roteiro, settings, rounds=None, aprovado=None) -> Path`, `get_settings() -> Settings`, `build_chat_model(settings) -> BaseChatModel`, `load_prompt(name) -> str`, `_texto(resp) -> str`.

- [ ] **Step 1: Criar os pacotes novos**

```bash
cd /c/dev/forge-videos
for p in agents orchestration domain llms prompts services infrastructure skills; do
  mkdir -p "src/forge/$p"
  touch "src/forge/$p/__init__.py"
done
```

- [ ] **Step 2: Mover os arquivos**

```bash
git mv src/forge/writer/tema.py        src/forge/agents/tema.py
git mv src/forge/writer/research.py    src/forge/agents/research.py
git mv src/forge/writer/plan.py        src/forge/agents/plan.py
git mv src/forge/writer/write.py       src/forge/agents/write.py
git mv src/forge/writer/review.py      src/forge/agents/review.py
git mv src/forge/writer/models.py      src/forge/domain/models.py
git mv src/forge/writer/_prompts.py    src/forge/prompts/loader.py
git mv src/forge/writer/prompts/fontes.md    src/forge/prompts/fontes.md
git mv src/forge/writer/prompts/plan.md      src/forge/prompts/plan.md
git mv src/forge/writer/prompts/research.md  src/forge/prompts/research.md
git mv src/forge/writer/prompts/review.md    src/forge/prompts/review.md
git mv src/forge/writer/prompts/tema.md      src/forge/prompts/tema.md
git mv src/forge/writer/prompts/write.md     src/forge/prompts/write.md
git mv src/forge/orchestrator/graph.py src/forge/orchestration/graph.py
git mv src/forge/orchestrator/state.py src/forge/orchestration/state.py
git mv src/forge/llm/model.py          src/forge/llms/model.py
git mv src/forge/output/storage.py     src/forge/services/storage.py
git mv src/forge/config.py             src/forge/infrastructure/config.py
git mv src/forge/logging.py            src/forge/infrastructure/logging.py
git mv tests/writer                    tests/agents
git mv tests/orchestrator              tests/orchestration
rm -rf src/forge/writer src/forge/orchestrator src/forge/llm src/forge/output
```

`git mv` aqui é só renomeação rastreada — **não** é `git add` de conteúdo novo e não cria commit. Se preferir evitar o comando `git` por completo, use `mv` simples; o resultado em disco é idêntico.

- [ ] **Step 3: Criar `llms/parsing.py`**

Conteúdo integral (a função sai de `writer/tema.py:20-26`):

```python
def _texto(resp) -> str:
    content = resp.content
    if isinstance(content, str):
        return content
    return "".join(
        b.get("text", "") for b in content if isinstance(b, dict)
    )
```

- [ ] **Step 4: Remover `_texto` de `agents/tema.py` e importar**

Apagar as linhas 20-26 (a definição de `_texto`) e trocar o bloco de imports por:

```python
from langchain_core.messages import HumanMessage

from forge.infrastructure.logging import get_logger
from forge.llms.parsing import _texto
from forge.prompts.loader import load_prompt

logger = get_logger(__name__)
```

O corpo de `gerar_tema` fica inalterado.

- [ ] **Step 5: Corrigir o caminho em `prompts/loader.py`**

Os `.md` agora vivem dentro do pacote `forge.prompts`, não em subpasta. Arquivo completo:

```python
from importlib.resources import files


def load_prompt(name: str) -> str:
    return (files("forge.prompts") / f"{name}.md").read_text(encoding="utf-8")
```

- [ ] **Step 6: Reescrever os imports em todo o repositório**

Aplicar estas 13 substituições em `src/` e `tests/`:

| De | Para |
| --- | --- |
| `forge.writer.tema` | `forge.agents.tema` |
| `forge.writer.research` | `forge.agents.research` |
| `forge.writer.plan` | `forge.agents.plan` |
| `forge.writer.write` | `forge.agents.write` |
| `forge.writer.review` | `forge.agents.review` |
| `forge.writer.models` | `forge.domain.models` |
| `forge.writer._prompts` | `forge.prompts.loader` |
| `forge.orchestrator.graph` | `forge.orchestration.graph` |
| `forge.orchestrator.state` | `forge.orchestration.state` |
| `forge.llm.model` | `forge.llms.model` |
| `forge.output.storage` | `forge.services.storage` |
| `forge.config` | `forge.infrastructure.config` |
| `forge.logging` | `forge.infrastructure.logging` |

```bash
cd /c/dev/forge-videos
FILES=$(find src tests -name '*.py')
sed -i \
  -e 's/forge\.writer\.tema/forge.agents.tema/g' \
  -e 's/forge\.writer\.research/forge.agents.research/g' \
  -e 's/forge\.writer\.plan/forge.agents.plan/g' \
  -e 's/forge\.writer\.write/forge.agents.write/g' \
  -e 's/forge\.writer\.review/forge.agents.review/g' \
  -e 's/forge\.writer\.models/forge.domain.models/g' \
  -e 's/forge\.writer\._prompts/forge.prompts.loader/g' \
  -e 's/forge\.orchestrator\.graph/forge.orchestration.graph/g' \
  -e 's/forge\.orchestrator\.state/forge.orchestration.state/g' \
  -e 's/forge\.llm\.model/forge.llms.model/g' \
  -e 's/forge\.output\.storage/forge.services.storage/g' \
  -e 's/forge\.config/forge.infrastructure.config/g' \
  -e 's/forge\.logging/forge.infrastructure.logging/g' \
  $FILES
```

Ordem importa: `forge.writer.plan` antes de qualquer regra mais curta que pudesse casar parcialmente. As regras acima são todas disjuntas, então a ordem listada é segura.

- [ ] **Step 7: Verificar que nenhum caminho antigo sobrou**

Run: `grep -rn "forge\.\(writer\|orchestrator\|llm\.\|output\.\|config\|logging\)" src tests --include='*.py'`
Expected: nenhuma saída. Qualquer linha que apareça é import não migrado.

Atenção a dois falsos positivos aceitáveis: `forge.infrastructure.config` e `forge.infrastructure.logging` contêm as palavras `config`/`logging` mas já estão corretos — o padrão acima não casa com eles porque exige `forge.` imediatamente antes.

- [ ] **Step 8: Rodar a suíte**

Run: `uv run pytest`
Expected: mesma contagem de testes passando que antes da tarefa. Nenhum `ImportError`, nenhum `ModuleNotFoundError`.

Se algum teste falhar por motivo que não seja import, pare — a movimentação alterou comportamento e isso é um defeito, não um ajuste.

- [ ] **Step 9: Verificar o entrypoint**

Run: `uv run forge roteiro --help`
Expected: o help do subcomando, com `--tema` e `--provider`. Confirma que o `console_script` resolve e que o pacote importa fora do pytest.

---

## Tarefa 2: Loader de skills

**Files:**
- Create: `src/forge/skills/loader.py`

**Interfaces:**
- Consumes: nada de tarefas anteriores.
- Produces:
  - `Skill` — dataclass congelada com `nome: str`, `dono: str | None`, `dominio: bool`, `secoes: dict[str, str]`
  - `carregar(nome: str) -> Skill`
  - `load_skills(nomes: list[str], agente: str) -> str`

- [ ] **Step 1: Escrever `src/forge/skills/loader.py`**

Arquivo completo. O parse de frontmatter é manual e suporta exatamente as três chaves do formato — sem `pyyaml`, conforme a restrição global.

```python
import re
from dataclasses import dataclass
from importlib.resources import files

from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)

_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n(.*)\Z", re.DOTALL)
_SECAO = re.compile(r"^## +(.+?)\s*$", re.MULTILINE)

SECAO_EXCLUSIVA = "Procedimento"


@dataclass(frozen=True)
class Skill:
    nome: str
    dono: str | None
    dominio: bool
    secoes: dict[str, str]


def _parse_frontmatter(bruto: str) -> dict[str, str]:
    dados: dict[str, str] = {}
    for linha in bruto.splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or ":" not in linha:
            continue
        chave, _, valor = linha.partition(":")
        dados[chave.strip()] = valor.strip()
    return dados


def _parse_secoes(corpo: str) -> dict[str, str]:
    marcas = list(_SECAO.finditer(corpo))
    secoes: dict[str, str] = {}
    for i, m in enumerate(marcas):
        fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(corpo)
        secoes[m.group(1)] = corpo[m.end():fim].strip()
    return secoes


def carregar(nome: str) -> Skill:
    texto = (files("forge.skills") / f"{nome}.md").read_text(encoding="utf-8")
    m = _FRONTMATTER.match(texto)
    if m is None:
        raise ValueError(f"skill '{nome}' sem frontmatter")
    meta = _parse_frontmatter(m.group(1))
    dono = meta.get("dono") or None
    return Skill(
        nome=meta.get("nome", nome),
        dono=dono,
        dominio=meta.get("dominio", "false").lower() == "true",
        secoes=_parse_secoes(m.group(2)),
    )


def load_skills(nomes: list[str], agente: str) -> str:
    if not nomes:
        return "(nenhuma)"
    blocos: list[str] = []
    for nome in nomes:
        skill = carregar(nome)
        partes = [f"# Skill: {skill.nome}"]
        for titulo, corpo in skill.secoes.items():
            if titulo == SECAO_EXCLUSIVA and skill.dono != agente:
                continue
            partes.append(f"## {titulo}\n{corpo}")
        blocos.append("\n\n".join(partes))
        logger.debug("Skill loaded", skill=nome, agente=agente, dono=skill.dono)
    return "\n\n---\n\n".join(blocos)
```

- [ ] **Step 2: Verificar o corte de procedimento à mão**

O loader ainda não tem skills para carregar (chegam na Tarefa 3). Verificar o parse com um arquivo temporário:

```bash
cd /c/dev/forge-videos
cat > src/forge/skills/_teste_tmp.md <<'EOF'
---
nome: _teste_tmp
dono: research
dominio: false
---

## Critérios
visível a todos

## Procedimento
só o dono vê
EOF

uv run python -c "
from forge.skills.loader import load_skills
dono = load_skills(['_teste_tmp'], 'research')
outro = load_skills(['_teste_tmp'], 'review')
assert 'só o dono vê' in dono, 'dono deveria ver Procedimento'
assert 'só o dono vê' not in outro, 'não-dono NÃO deveria ver Procedimento'
assert 'visível a todos' in outro, 'não-dono deveria ver Critérios'
print('OK')
"
rm src/forge/skills/_teste_tmp.md
```

Expected: `OK`, e nenhum `AssertionError`.

---

## Tarefa 3: As quatro skills

Conteúdo extraído de texto que já existe — nos prompts atuais e na seção "Regras" do documento de arquitetura (`docs/CreatorBrain_Plataforma_Arquitetura_Visao.md:212-222`). Nada inventado do zero.

**Files:**
- Create: `src/forge/skills/fact_check.md`
- Create: `src/forge/skills/retention.md`
- Create: `src/forge/skills/writing.md`
- Create: `src/forge/skills/story.md`

**Interfaces:**
- Consumes: `carregar()` e `load_skills()` da Tarefa 2.
- Produces: quatro skills carregáveis por nome. Donos: `fact_check` → `research`, `retention` → `write`, `writing` → `write`, `story` → `plan`.

- [ ] **Step 1: `src/forge/skills/fact_check.md`**

Origem: `prompts/research.md:5-11`, `prompts/write.md:14`, e as regras "Nunca inventar fatos" / "Priorizar fontes primárias" do documento de arquitetura.

```markdown
---
nome: fact_check
dono: research
dominio: false
---

## Critérios
Padrão é ZERO aspas. Um roteiro forte sem nenhuma citação literal é o normal.
Só use aspas se frase, autor e obra estiverem confirmados por busca nesta sessão.
Ideias amplamente conhecidas (dicotomia do controle estoica, má-fé sartriana,
eterno retorno) dispensam busca — explique e atribua sem aspas.
Na dúvida, parafraseie e nomeie o autor, sem aspas.
Fonte primária vale mais que comentário sobre a fonte.

## Anti-padrões
- Site de coletânea de frases não confirma nada.
- Aspa sem obra identificada.
- Atribuir a um autor uma frase que só aparece parafraseada.
- Inventar data, edição ou capítulo para dar aparência de rigor.

## Procedimento
Monta a query com autor + obra + trecho literal, nessa ordem.
Fonte terciária (coletânea, agregador de citações, rede social) não fecha
verificação — serve no máximo para achar a fonte real.
Confirmado significa: a frase aparece atribuída à mesma obra em fonte que
identifica edição ou capítulo.
Na dúvida, devolve não-confirmado. Não-confirmado não é falha da pesquisa;
é resultado válido, e o roteiro segue sem a aspa.
```

- [ ] **Step 2: `src/forge/skills/retention.md`**

Origem: a dimensão "retenção" de `prompts/review.md:1`, e as regras "Um problema principal por vídeo" / "Hook forte" / "Alternar teoria e exemplos" / "Conclusão transformadora" do documento de arquitetura.

```markdown
---
nome: retention
dono: write
dominio: false
---

## Critérios
Um problema principal por vídeo. Se há dois, o segundo vira outro vídeo.
O Hook estabelece a tensão nos primeiros segundos, sem preâmbulo e sem
apresentar o tema em terceira pessoa.
Teoria e exemplo se alternam. Dois blocos abstratos seguidos são um defeito.
Cada seção deixa uma pergunta aberta que a próxima responde.
A Conclusão devolve o Hook transformado, não resumido.

## Anti-padrões
- Abrir com definição de dicionário ou com a história do conceito.
- "Antes de começar, deixa eu explicar..." — preâmbulo é queda de retenção.
- Resumo que apenas repete o que já foi dito, sem reposicionar a tese.
- Seção que poderia ser removida sem o roteiro perder nada.

## Procedimento
Ao escrever, verifique seção a seção qual pergunta ela abre e qual ela fecha.
Se uma seção não abre nenhuma, ela é um platô — reescreva ou funda com a
vizinha.
```

- [ ] **Step 3: `src/forge/skills/writing.md`**

Origem: `prompts/write.md:11-13` (bloco "Voz").

```markdown
---
nome: writing
dono: write
dominio: false
---

## Critérios
Primeira pessoa, acessível, sem jargão não explicado.
Concreto antes de abstrato: o exemplo vem antes da definição.
Uma posição clara — o roteiro defende algo.
Um contra-argumento honesto em algum ponto, tratado pelo seu lado mais forte.
PT-BR.

## Anti-padrões
- Jargão introduzido sem tradução na mesma frase.
- Neutralidade morna: expor duas visões sem tomar partido.
- Contra-argumento montado fraco só para ser derrubado.
- Frase longa que empilha três ideias sem respiro.

## Procedimento
Escreva o exemplo primeiro, a definição depois. Se a definição não couber
em uma frase após o exemplo, o exemplo está errado.
```

- [ ] **Step 4: `src/forge/skills/story.md`**

Origem: `prompts/plan.md:8-10`.

```markdown
---
nome: story
dono: plan
dominio: false
---

## Critérios
A tese é uma afirmação discutível — alguém informado poderia discordar.
Tese não é paráfrase do tema.
Cada uma das nove partes empurra a tese adiante.
Nada apenas reformula o movimento anterior.

## Anti-padrões
- Tese que ninguém contestaria ("o autoconhecimento é importante").
- Tese que é o tema com outras palavras.
- Duas seções que fazem o mesmo trabalho argumentativo.
- Esboço que lista assuntos em vez de descrever movimentos.

## Procedimento
Para cada uma das nove partes, escreva em uma frase o que ela acrescenta
que a anterior não tinha. Se a frase não sair, a parte é redundante.
```

- [ ] **Step 5: Verificar que as quatro carregam**

Run:

```bash
uv run python -c "
from forge.skills.loader import carregar
esperado = {'fact_check':'research','retention':'write','writing':'write','story':'plan'}
for nome, dono in esperado.items():
    s = carregar(nome)
    assert s.dono == dono, f'{nome}: dono {s.dono}, esperado {dono}'
    assert s.dominio is False, f'{nome}: dominio deveria ser False'
    for secao in ('Critérios','Anti-padrões','Procedimento'):
        assert secao in s.secoes, f'{nome}: falta seção {secao}'
print('OK — 4 skills')
"
```

Expected: `OK — 4 skills`

---

## Tarefa 4: Ligar skills aos agentes

Cada agente declara `SKILLS` no próprio arquivo. Os prompts perdem o texto que virou skill e ganham o slot `{skills}`.

**Files:**
- Modify: `src/forge/agents/research.py`, `plan.py`, `write.py`, `review.py` (constante `SKILLS` + slot)
- Modify: `src/forge/prompts/research.md`, `plan.md`, `write.md`, `review.md`

**Interfaces:**
- Consumes: `load_skills(nomes, agente)` da Tarefa 2; as quatro skills da Tarefa 3.
- Produces: constante `SKILLS: list[str]` em cada módulo de agente. `tema.py` não recebe `SKILLS` (não usa skill nenhuma).

- [ ] **Step 1: `SKILLS` em cada agente**

Adicionar logo abaixo do `logger = get_logger(__name__)` de cada arquivo:

```python
# agents/research.py
SKILLS = ["fact_check"]

# agents/plan.py
SKILLS = ["story"]

# agents/write.py
SKILLS = ["writing", "story", "retention", "fact_check"]

# agents/review.py
SKILLS = ["story", "retention", "fact_check"]
```

- [ ] **Step 2: Substituir `prompts/research.md`**

O bloco "Regra de citação (dura)" sai — virou `fact_check`. Arquivo completo:

```markdown
Pesquise na web material sólido para um roteiro sobre: {tema}

Confirme fatos, escolas e ideias em fontes primárias. Use a ferramenta de busca.

{skills}

Produza notas de pesquisa densas: ideias-chave, filósofos e escolas relevantes,
exemplos concretos e, quando confirmadas, referências com autor e obra.
```

- [ ] **Step 3: Substituir `prompts/plan.md`**

As instruções sobre tese discutível e avanço saem — viraram `story`. Arquivo completo:

```markdown
Tema: {tema}

Notas de pesquisa:
{research}

{skills}

Produza:
1. tese — a afirmação central do roteiro.
2. esboco — como cada uma das nove partes (Hook, Problema, História,
   Explicação, Filósofo, Psicologia, Aplicação, Resumo, Conclusão)
   avança a tese.
```

- [ ] **Step 4: Substituir `prompts/write.md`**

O bloco "Voz" e a regra de aspas saem — viraram `writing` e `fact_check`. Arquivo completo:

```markdown
Escreva o roteiro completo de um vídeo em PT-BR, com exatamente nove seções,
nesta ordem: Hook, Problema, História, Explicação, Filósofo, Psicologia,
Aplicação, Resumo, Conclusão.

Tese: {tese}

Esboço: {esboco}

Material de pesquisa: {research}

{skills}

Notas de revisão a corrigir nesta versão (se houver):
{notas}
```

- [ ] **Step 5: Substituir `prompts/review.md`**

A lista solta de dimensões sai — os critérios agora chegam pelas skills. Arquivo completo:

```markdown
Revise este roteiro contra os critérios abaixo.

{skills}

Aprove (aprovado=true) somente se o roteiro passa em todos. Caso contrário,
aprovado=false e liste notas objetivas: dimensão, problema, sugestão.

Roteiro:
{roteiro}
```

- [ ] **Step 6: Injetar nas chamadas `.format()`**

Cada agente passa `skills=load_skills(SKILLS, "<nome do agente>")`. O nome do agente é o literal que casa com `dono` nas skills.

`agents/research.py` — o import e as duas chamadas de prompt:

```python
from forge.skills.loader import load_skills

# em _pesquisar_server_side:
resp = search.invoke([HumanMessage(content=load_prompt("research").format(
    tema=tema, skills=load_skills(SKILLS, "research")
))])

# em _pesquisar_client_side:
messages = [HumanMessage(content=load_prompt("research").format(
    tema=tema, skills=load_skills(SKILLS, "research")
))]
```

`agents/plan.py`:

```python
prompt = load_prompt("plan").format(
    tema=tema, research=research, skills=load_skills(SKILLS, "plan")
)
```

`agents/write.py`:

```python
prompt = load_prompt("write").format(
    tese=tese,
    esboco=esboco,
    research=research,
    notas=_fmt_notas(notas),
    skills=load_skills(SKILLS, "write"),
)
```

`agents/review.py`:

```python
prompt = load_prompt("review").format(
    roteiro=_render(roteiro), skills=load_skills(SKILLS, "review")
)
```

O prompt `fontes.md` não muda e não recebe slot — a extração de fontes não usa skill.

- [ ] **Step 7: Verificar que o corte por dono vale no fluxo real**

Run:

```bash
uv run python -c "
from forge.agents import research, write, review, plan
from forge.skills.loader import load_skills

r = load_skills(research.SKILLS, 'research')
w = load_skills(write.SKILLS, 'write')
v = load_skills(review.SKILLS, 'review')
p = load_skills(plan.SKILLS, 'plan')

# research é dono de fact_check: vê o procedimento
assert 'Fonte terciária' in r, 'research deveria ver Procedimento de fact_check'
# write e review NÃO são donos de fact_check
assert 'Fonte terciária' not in w, 'write NÃO deveria ver Procedimento de fact_check'
assert 'Fonte terciária' not in v, 'review NÃO deveria ver Procedimento de fact_check'
# mas ambos veem os critérios
assert 'ZERO aspas' in w and 'ZERO aspas' in v, 'critérios de fact_check devem ser compartilhados'
# review não é dono de nada: nenhum procedimento
assert 'Procedimento' not in v, 'review não deveria receber nenhum Procedimento'
# plan é dono de story
assert 'a parte é redundante' in p, 'plan deveria ver Procedimento de story'
print('OK — ownership')
"
```

Expected: `OK — ownership`

- [ ] **Step 8: Rodar a suíte**

Run: `uv run pytest`
Expected: tudo passando. Os testes usam `ScriptedModel`, que ignora o conteúdo do prompt — a mudança de texto não deve quebrar nada. Se `tests/agents/test_prompts.py` afirmar sobre o conteúdo dos `.md`, ajuste as asserções ao texto novo.

---

## Tarefa 5: State e escrita de artefatos

**Files:**
- Modify: `src/forge/orchestration/state.py`
- Create: `src/forge/services/artefatos.py`
- Modify: `src/forge/infrastructure/config.py` (novo campo `max_passos`)

**Interfaces:**
- Consumes: `Fonte`, `Roteiro`, `ReviewResult` de `forge.domain.models`; `_slug` de `forge.services.storage`.
- Produces:
  - `RoteiroState` com `skills_dominio: list[str]`, `pedido: str | None`, `passos: int`, `run_dir: Path`
  - `criar_run_dir(settings: Settings, tema: str) -> Path`
  - `gravar_artefato(run_dir: Path, agente: str, resultado: dict) -> Path`
  - `Settings.max_passos: int` (padrão 20)

- [ ] **Step 1: Campos novos no state**

`src/forge/orchestration/state.py` completo:

```python
from pathlib import Path
from typing import TypedDict

from forge.domain.models import Fonte, ReviewResult, Roteiro


class RoteiroState(TypedDict, total=False):
    # --- conteúdo: espelhado nos artefatos, reconstruível do disco ---
    tema: str | None
    research_notes: str
    fontes: list[Fonte]
    tese: str
    esboco: str
    roteiro: Roteiro | None
    review: ReviewResult | None
    # --- controle: orquestração, nunca vai para artefato ---
    rounds: int
    passos: int
    pedido: str | None
    run_dir: Path
    skills_dominio: list[str]
```

- [ ] **Step 2: `max_passos` no Settings**

Em `src/forge/infrastructure/config.py`, adicionar ao lado de `max_review_rounds` (linha 31):

```python
    max_passos: int = 20
```

- [ ] **Step 3: Escrever `src/forge/services/artefatos.py`**

Arquivo completo. Um renderizador explícito por agente — nada genérico, porque a forma de cada resultado é conhecida.

```python
import json
from datetime import datetime
from pathlib import Path

from forge.domain.models import Fonte
from forge.infrastructure.config import Settings
from forge.infrastructure.logging import get_logger
from forge.services.storage import _slug

logger = get_logger(__name__)

ORDEM = ["tema", "research", "plan", "write", "review"]
_POR_RODADA = {"write", "review"}


def criar_run_dir(settings: Settings, tema: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = settings.output_dir.parent / "runs" / f"{ts}-{_slug(tema)}"
    run_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Run directory created", run_dir=str(run_dir))
    return run_dir


def _nome_arquivo(run_dir: Path, agente: str) -> str:
    """Numera pela contagem de arquivos já presentes, não por `rounds`.

    `rounds` só é incrementado em node_review, então o primeiro e o segundo
    `write` chegariam aqui ambos valendo r1 e o rascunho inicial seria
    sobrescrito. Contar o que já existe é independente do state e continua
    correto numa retomada.
    """
    indice = ORDEM.index(agente)
    if agente not in _POR_RODADA:
        return f"{indice:02d}-{agente}.md"
    n = len(list(run_dir.glob(f"{indice:02d}-{agente}-r*.md"))) + 1
    return f"{indice:02d}-{agente}-r{n}.md"


def _fmt_fontes(fontes: list[Fonte]) -> str:
    """Serializa como JSON — que é YAML válido e faz round-trip exato.

    YAML solto quebra em título com dois-pontos ("A Ética: Uma Introdução"),
    que é a forma comum de título de livro.
    """
    dados = [{"titulo": f.titulo, "autor": f.autor, "url": f.url} for f in fontes]
    return "fontes: " + json.dumps(dados, ensure_ascii=False)


def _render(agente: str, resultado: dict) -> str:
    if agente == "tema":
        return f"---\nagente: tema\n---\n\n{resultado['tema']}\n"

    if agente == "research":
        return (
            "---\nagente: research\n"
            + _fmt_fontes(resultado.get("fontes", []))
            + "\n---\n\n## Brief\n\n"
            + resultado["research_notes"]
            + "\n"
        )

    if agente == "plan":
        return (
            f"---\nagente: plan\n---\n\n## Tese\n\n{resultado['tese']}\n\n"
            f"## Esboço\n\n{resultado['esboco']}\n"
        )

    if agente == "write":
        roteiro = resultado["roteiro"]
        partes = [f"---\nagente: write\ntese: {roteiro.tese}\n---\n"]
        for s in roteiro.secoes:
            partes.append(f"## {s.nome}\n\n{s.conteudo}\n")
        return "\n".join(partes)

    if agente == "review":
        review = resultado["review"]
        partes = [
            f"---\nagente: review\naprovado: {review.aprovado}\n---\n",
            "## Notas\n",
        ]
        for n in review.notas:
            partes.append(f"- [{n.dimensao}] {n.problema} → {n.sugestao}")
        if review.verificar:
            partes.append("\n## Verificar\n")
            for v in review.verificar:
                partes.append(f"- {v}")
        return "\n".join(partes) + "\n"

    raise ValueError(f"agente sem renderizador: {agente}")


def gravar_artefato(run_dir: Path, agente: str, resultado: dict) -> Path:
    path = run_dir / _nome_arquivo(run_dir, agente)
    path.write_text(_render(agente, resultado), encoding="utf-8")
    logger.debug("Artifact written", agente=agente, path=str(path))
    return path


def gravar_bruto(run_dir: Path, agente: str, bruto: str) -> Path:
    indice = ORDEM.index(agente)
    path = run_dir / f"{indice:02d}-{agente}.raw.md"
    path.write_text(bruto, encoding="utf-8")
    logger.debug("Raw artifact written", agente=agente, path=str(path))
    return path
```

`_render` de `review` já referencia `review.verificar`, campo que só existe a partir da Tarefa 8. Até lá o atributo não existe e o acesso falharia — por isso a Tarefa 8 vem antes de qualquer run completa com review. Se quiser rodar o pipeline entre as Tarefas 5 e 8, troque por `getattr(review, "verificar", [])`.

- [ ] **Step 4: Verificar nomes e renderização**

Run:

```bash
uv run python -c "
from pathlib import Path
from forge.services.artefatos import _nome_arquivo, _render, gravar_artefato
from forge.domain.models import Roteiro, Secao, Fonte

import tempfile
d = Path(tempfile.mkdtemp())
assert _nome_arquivo(d, 'tema') == '00-tema.md'
assert _nome_arquivo(d, 'research') == '01-research.md'
assert _nome_arquivo(d, 'plan') == '02-plan.md'
# numeracao por contagem: grava e confere que nao sobrescreve
p1 = gravar_artefato(d, 'write', {'roteiro': Roteiro(tema='t', tese='x', secoes=[Secao(nome='Hook', conteudo='c')])})
p2 = gravar_artefato(d, 'write', {'roteiro': Roteiro(tema='t', tese='x', secoes=[Secao(nome='Hook', conteudo='c')])})
assert (p1.name, p2.name) == ('03-write-r1.md', '03-write-r2.md'), (p1.name, p2.name)
assert p1.exists() and p2.exists()

r = _render('research', {'research_notes':'brief denso','fontes':[Fonte(titulo='Obra', autor='Autor')]})
assert 'titulo: Obra' in r and 'brief denso' in r

w = _render('write', {'roteiro': Roteiro(tema='t', tese='tese', secoes=[Secao(nome='Hook', conteudo='c')])})
assert '## Hook' in w
print('OK — artefatos')
"
```

Expected: `OK — artefatos`

---

## Tarefa 6: Wrapper no grafo e separação brief/bruto

**Files:**
- Modify: `src/forge/agents/research.py` (devolver `(brief, raw)`)
- Modify: `src/forge/orchestration/graph.py` (wrapper, `LE`)
- Modify: `src/forge/agents/research.py`, `plan.py`, `write.py`, `review.py`, `tema.py` (constante `LE`)
- Modify: `src/forge/cli.py` (criar `run_dir`, semear `passos`)

**Interfaces:**
- Consumes: `gravar_artefato`, `gravar_bruto`, `criar_run_dir` da Tarefa 5; `SKILLS` da Tarefa 4.
- Produces:
  - `pesquisar(model, tema, provider="anthropic") -> tuple[str, list[Fonte], str]` — **assinatura mudou**: agora devolve `(brief, fontes, raw)`
  - `LE: list[str]` em cada módulo de agente
  - `com_wrapper(nome, fn, le)` em `orchestration/graph.py`

- [ ] **Step 1: `LE` em cada agente**

Ao lado da constante `SKILLS`:

```python
# agents/tema.py
LE = ["tema"]

# agents/research.py
SKILLS = ["fact_check"]
LE = ["tema", "pedido"]

# agents/plan.py
SKILLS = ["story"]
LE = ["tema", "research_notes"]

# agents/write.py
SKILLS = ["writing", "story", "retention", "fact_check"]
LE = ["tema", "tese", "esboco", "research_notes", "fontes", "review"]

# agents/review.py
SKILLS = ["story", "retention", "fact_check"]
LE = ["roteiro", "rounds"]
```

`review` inclui `rounds` — que é campo de controle — porque `node_review` o
incrementa. `LE` lista o que o node lê, não apenas conteúdo: um campo de
controle que o node precisa tem de estar aqui, senão o `state.get("rounds", 0)`
sempre lê 0 e o contador de rodadas trava.

O wrapper enxerga o state **inteiro** — é só o `fn` interno que recebe a fatia.
Por isso `run_dir`, `passos` e `rounds` continuam acessíveis ao wrapper sem
aparecer em nenhum `LE`.

- [ ] **Step 2: `research` devolve brief e bruto separados**

Em `src/forge/agents/research.py`, as três funções mudam. `_texto(resp)` continua vindo de `forge.llms.parsing`.

```python
def pesquisar(model, tema: str, provider: str = "anthropic") -> tuple[str, list[Fonte], str]:
    if provider == "anthropic":
        brief, raw = _pesquisar_server_side(model, tema)
    else:
        brief, raw = _pesquisar_client_side(model, tema)
    fontes = _extrair_fontes(model, brief)
    return brief, fontes, raw


def _pesquisar_server_side(model, tema: str) -> tuple[str, str]:
    search = model.bind_tools([WEB_SEARCH_TOOL])
    resp = search.invoke([HumanMessage(content=load_prompt("research").format(
        tema=tema, skills=load_skills(SKILLS, "research")
    ))])
    brief = _texto(resp)
    return brief, str(resp.content)


def _pesquisar_client_side(model, tema: str) -> tuple[str, str]:
    """Busca alternativa (DuckDuckGo) para providers sem web_search server-side."""
    tool_model = model.bind_tools([buscar_web])
    messages = [HumanMessage(content=load_prompt("research").format(
        tema=tema, skills=load_skills(SKILLS, "research")
    ))]
    bruto: list[str] = []
    for _ in range(MAX_SEARCH_ROUNDS):
        resp = tool_model.invoke(messages)
        if not getattr(resp, "tool_calls", None):
            return _texto(resp), "\n\n".join(bruto)
        messages.append(resp)
        for call in resp.tool_calls:
            resultado = buscar_web.invoke(call["args"])
            bruto.append(f"### query: {call['args']}\n{resultado}")
            messages.append(ToolMessage(content=resultado, tool_call_id=call["id"]))
    resp = tool_model.invoke(messages)
    return _texto(resp), "\n\n".join(bruto)
```

O brief é o que entra no state. O bruto vai só para disco — nunca para `research_notes`.

- [ ] **Step 3: Wrapper em `orchestration/graph.py`**

Adicionar antes de `build_graph`:

```python
from forge.services.artefatos import gravar_artefato, gravar_bruto


def com_wrapper(nome, fn, le):
    """Estreita o state pelo LE do agente, grava o artefato, conta o passo."""
    def wrapped(state):
        entrada = {k: state[k] for k in le if k in state}
        resultado = fn(entrada)
        bruto = resultado.pop("_raw", None)
        gravar_artefato(state["run_dir"], nome, resultado)
        if bruto is not None:
            gravar_bruto(state["run_dir"], nome, bruto)
        return {**resultado, "passos": state.get("passos", 0) + 1}
    return wrapped
```

`_raw` é a chave de transporte do bruto: o node a devolve, o wrapper a retira antes de gravar o artefato de contrato e antes de mesclar no state. Ela nunca chega ao `RoteiroState`.

- [ ] **Step 4: Ajustar `node_research` e registrar os nodes com o wrapper**

`node_research` passa a devolver `_raw`:

```python
    def node_research(state):
        logger.debug("Starting research phase", tema=state["tema"])
        brief, fontes, raw = research_stage.pesquisar(model, state["tema"], settings.provider)
        logger.info("Research completed", num_fontes=len(fontes))
        return {"research_notes": brief, "fontes": fontes, "_raw": raw}
```

E o registro dos nodes usa o wrapper, puxando o `LE` de cada módulo:

```python
    g = StateGraph(RoteiroState)
    g.add_node("tema",     com_wrapper("tema",     node_tema,     tema_stage.LE))
    g.add_node("research", com_wrapper("research", node_research, research_stage.LE))
    g.add_node("plan",     com_wrapper("plan",     node_plan,     plan_stage.LE))
    g.add_node("write",    com_wrapper("write",    node_write,    write_stage.LE))
    g.add_node("review",   com_wrapper("review",   node_review,   review_stage.LE))
```

`node_review` continua incrementando `rounds` como hoje (`graph.py:71`) — `rounds` conta rodadas de revisão, `passos` conta execuções de qualquer node. São contadores diferentes e ambos ficam.

- [ ] **Step 5: `cli.py` cria o `run_dir`**

Em `src/forge/cli.py`, antes de invocar o grafo, e depois de resolver o tema — o `run_dir` precisa do slug do tema. Como o tema pode ser gerado pelo próprio grafo, use o tema fornecido ou um placeholder:

```python
    from forge.services.artefatos import criar_run_dir

    run_dir = criar_run_dir(settings, args.tema or "roteiro")
    estado_inicial = {
        "tema": args.tema,
        "rounds": 0,
        "passos": 0,
        "run_dir": run_dir,
    }
    state: dict = dict(estado_inicial)
    for step in graph.stream(estado_inicial):
        node_name = next(iter(step))
        logger.info("Node finished", node=node_name)
        print(f"[{node_name}]", file=sys.stderr)
        state.update(step[node_name])
    final = state
```

E ao final, além do `print(str(path))` que já existe, imprimir o diretório da run:

```python
    print(f"run: {run_dir}", file=sys.stderr)
```

- [ ] **Step 6: Corrigir as chamadas de `pesquisar` na suíte**

A assinatura mudou de 2 para 3 valores de retorno. Achar os pontos:

Run: `grep -rn "pesquisar(" tests src --include='*.py'`

Ajustar cada desempacotamento de `notes, fontes = pesquisar(...)` para `notes, fontes, raw = pesquisar(...)`.

- [ ] **Step 7: Rodar a suíte**

Run: `uv run pytest`
Expected: tudo passando.

Os testes de grafo (`tests/orchestration/test_graph.py:43`) invocam com `{"tema": None, "rounds": 0}` e agora o wrapper acessa `state["run_dir"]`. Adicionar `"run_dir": tmp_path` e `"passos": 0` ao dict inicial desses dois testes, recebendo `tmp_path` como fixture.

- [ ] **Step 8: Verificar uma run real**

Run: `uv run forge roteiro --tema "teste de artefatos"`
Expected: `output/runs/<timestamp>-teste-de-artefatos/` contendo `00-tema.md`, `01-research.md`, `01-research.raw.md`, `02-plan.md`, `03-write-r1.md`, `04-review-r1.md`.

Conferir à mão que `01-research.md` traz o brief e `01-research.raw.md` traz os resultados de busca — e que os dois **não** são o mesmo texto.

---

## Tarefa 7: Retomada

**Files:**
- Modify: `src/forge/services/artefatos.py` (leitura)
- Modify: `src/forge/orchestration/graph.py` (`build_graph(model, settings, inicio="tema")`)
- Modify: `src/forge/cli.py` (flag `--retomar`)

**Interfaces:**
- Consumes: `ORDEM`, `_nome_arquivo` da Tarefa 5.
- Produces:
  - `carregar_run(run_dir: Path) -> tuple[dict, str]` — devolve `(conteudo, primeiro_estagio_pendente)`
  - `build_graph(model, settings, inicio: str = "tema")`

- [ ] **Step 1: Leitura de artefatos em `artefatos.py`**

Os dois imports vão para o **topo** do arquivo, junto dos existentes — não ao
final. O resto do código é acrescentado depois de `gravar_bruto`.

```python
# no topo, junto dos imports já presentes:
import re
from forge.domain.models import Fonte, Roteiro, Secao
```

```python
# depois de gravar_bruto:
_SECAO_MD = re.compile(r"^## +(.+?)\s*$", re.MULTILINE)


def _corpo(texto: str) -> str:
    partes = texto.split("---", 2)
    return partes[2].strip() if len(partes) >= 3 else texto.strip()


def _ler_fontes(texto: str) -> list[Fonte]:
    """Contraparte exata de `_fmt_fontes`: uma linha `fontes: ` + JSON."""
    for linha in texto.splitlines():
        if linha.startswith("fontes: "):
            dados = json.loads(linha.removeprefix("fontes: "))
            return [Fonte(**d) for d in dados]
        if linha.startswith("---") and linha is not texto.splitlines()[0]:
            break
    return []


def _ultimo(run_dir: Path, agente: str) -> Path | None:
    """Última passagem do agente, por número de rodada — não por ordem alfabética.

    `sorted()` puro colocaria `-r10` antes de `-r2`. A partir de dez rodadas
    isso devolveria o artefato errado silenciosamente.
    """
    indice = ORDEM.index(agente)
    achados = [
        p for p in run_dir.glob(f"{indice:02d}-{agente}*.md")
        if not p.name.endswith(".raw.md")
    ]
    if not achados:
        return None

    def _rodada(p: Path) -> int:
        m = re.search(r"-r(\d+)\.md$", p.name)
        return int(m.group(1)) if m else 0

    return max(achados, key=_rodada)


def carregar_run(run_dir: Path) -> tuple[dict, str]:
    """Reconstrói os campos de conteúdo e devolve o primeiro estágio pendente."""
    conteudo: dict = {}
    for agente in ORDEM:
        path = _ultimo(run_dir, agente)
        if path is None:
            return conteudo, agente
        texto = path.read_text(encoding="utf-8")
        if agente == "tema":
            conteudo["tema"] = _corpo(texto)
        elif agente == "research":
            conteudo["research_notes"] = _corpo(texto).removeprefix("## Brief").strip()
            conteudo["fontes"] = _ler_fontes(texto)
        elif agente == "plan":
            secoes = _parse_blocos(_corpo(texto))
            conteudo["tese"] = secoes.get("Tese", "")
            conteudo["esboco"] = secoes.get("Esboço", "")
        elif agente == "write":
            secoes = _parse_blocos(_corpo(texto))
            conteudo["roteiro"] = Roteiro(
                tema=conteudo.get("tema", ""),
                tese=conteudo.get("tese", ""),
                secoes=[Secao(nome=k, conteudo=v) for k, v in secoes.items()],
                fontes=conteudo.get("fontes", []),
            )
    return conteudo, "review"


def _parse_blocos(corpo: str) -> dict[str, str]:
    marcas = list(_SECAO_MD.finditer(corpo))
    blocos: dict[str, str] = {}
    for i, m in enumerate(marcas):
        fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(corpo)
        blocos[m.group(1)] = corpo[m.end():fim].strip()
    return blocos
```

O `review` não é reconstruído: é sempre reexecutado na retomada, porque é ele que decide se o fluxo continua.

- [ ] **Step 2: `build_graph` aceita ponto de entrada**

Trocar a assinatura e a linha do entry point em `orchestration/graph.py`:

```python
def build_graph(model, settings, inicio: str = "tema"):
    ...
    g.set_entry_point(inicio)
```

O restante das arestas fica igual — elas descrevem o fluxo, não o começo.

- [ ] **Step 3: Flag `--retomar` na CLI**

Em `src/forge/cli.py`, no parser:

```python
    r.add_argument(
        "--retomar",
        default=None,
        help="Diretório de uma run anterior; pula estágios já concluídos",
    )
```

E na montagem do estado inicial, substituindo o bloco da Tarefa 6:

```python
    from forge.services.artefatos import carregar_run, criar_run_dir

    if args.retomar:
        run_dir = Path(args.retomar)
        if not run_dir.is_dir():
            logger.error("Run directory not found", run_dir=str(run_dir))
            sys.exit(1)
        conteudo, inicio = carregar_run(run_dir)
        logger.info("Resuming run", run_dir=str(run_dir), inicio=inicio,
                    carregados=sorted(conteudo))
    else:
        run_dir = criar_run_dir(settings, args.tema or "roteiro")
        conteudo, inicio = {"tema": args.tema}, "tema"

    graph = build_graph(model, settings, inicio=inicio)
    estado_inicial = {**conteudo, "rounds": 0, "passos": 0, "run_dir": run_dir}
```

`build_graph` passa a ser chamado depois de resolver `inicio` — mover a linha `graph = build_graph(...)` (hoje em `cli.py:34`) para cá. Adicionar `from pathlib import Path` ao topo.

- [ ] **Step 4: Verificar retomada**

```bash
cd /c/dev/forge-videos
RUN=$(ls -dt output/runs/* | head -1)
echo "retomando: $RUN"
rm -f "$RUN"/03-write-*.md "$RUN"/04-review-*.md
uv run forge roteiro --retomar "$RUN"
```

Expected: o stream mostra `[write]` e `[review]`, **sem** `[tema]`, `[research]` ou `[plan]`. Nenhuma chamada de busca acontece — confirmar pelo tempo de execução e pela ausência de log `Search completed`.

- [ ] **Step 5: Rodar a suíte**

Run: `uv run pytest`
Expected: tudo passando. `build_graph` ganhou parâmetro com padrão, então as chamadas existentes nos testes continuam válidas.

---

## Tarefa 8: Handoff e orçamento

Única tarefa com teste novo. Terminação é o ponto onde um defeito custa dinheiro em silêncio.

**Files:**
- Modify: `src/forge/domain/models.py`
- Modify: `src/forge/orchestration/graph.py`
- Test: `tests/orchestration/test_graph.py`

**Interfaces:**
- Consumes: `Settings.max_passos` da Tarefa 5.
- Produces:
  - `ReviewResult.verificar: list[str]`
  - `RoteiroDraft.falta_pesquisa: str | None`
  - `rotear(state, max_rounds, max_passos) -> str` — substitui `should_continue`

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar a `tests/orchestration/test_graph.py`:

```python
from forge.orchestration.graph import rotear


def test_rotear_orcamento_vence_verificar():
    """Orçamento estourado encerra mesmo com verificação pendente."""
    state = {
        "review": ReviewResult(aprovado=False, verificar=["aspa de Nietzsche"]),
        "rounds": 0,
        "passos": 20,
    }
    assert rotear(state, max_rounds=8, max_passos=20) == END


def test_rotear_orcamento_vence_reprovacao():
    """Orçamento estourado encerra mesmo com review reprovado e rounds baixo."""
    state = {"review": ReviewResult(aprovado=False), "rounds": 0, "passos": 25}
    assert rotear(state, max_rounds=8, max_passos=20) == END


def test_rotear_verificar_vai_para_research():
    state = {
        "review": ReviewResult(aprovado=False, verificar=["aspa"]),
        "rounds": 1,
        "passos": 3,
    }
    assert rotear(state, max_rounds=8, max_passos=20) == "research"


def test_rotear_aprovado_encerra():
    state = {"review": ReviewResult(aprovado=True), "rounds": 1, "passos": 3}
    assert rotear(state, max_rounds=8, max_passos=20) == END


def test_rotear_reprovado_volta_para_write():
    state = {"review": ReviewResult(aprovado=False), "rounds": 1, "passos": 3}
    assert rotear(state, max_rounds=8, max_passos=20) == "write"


def test_grafo_termina_com_modelo_patologico(scripted, tmp_path):
    """Model que sempre pede verificação não pode rodar para sempre."""
    review_infinito = [ReviewResult(aprovado=False, verificar=["x"])] * 40
    draft_infinito = [_draft()] * 40
    estruturados = [FonteList(), Plano(tese="t", esboco="e")]
    for d, r in zip(draft_infinito, review_infinito):
        estruturados += [d, r]
    model = scripted(
        invoke_texts=["tema", "notas"] * 40,
        structured=estruturados,
    )
    settings = Settings(_env_file=None, max_review_rounds=99, max_passos=12)
    graph = build_graph(model, settings)
    final = graph.invoke({
        "tema": None, "rounds": 0, "passos": 0, "run_dir": tmp_path,
    })
    assert final["passos"] <= 13, f"orçamento furou: {final['passos']} passos"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/orchestration/test_graph.py -v -k rotear`
Expected: FAIL com `ImportError: cannot import name 'rotear'`.

- [ ] **Step 3: Campos de sinalização nos modelos**

Em `src/forge/domain/models.py`:

```python
class ReviewResult(BaseModel):
    aprovado: bool
    notas: list[Nota] = Field(default_factory=list)
    verificar: list[str] = Field(
        default_factory=list,
        description="Alegações que precisam de verificação por busca antes de decidir.",
    )


class RoteiroDraft(BaseModel):
    secoes: list[Secao]
    falta_pesquisa: str | None = Field(
        default=None,
        description="Preencher se o material de pesquisa não sustenta alguma seção.",
    )
```

As descrições vão para o schema entregue ao modelo — é assim que ele aprende quando preencher os campos.

- [ ] **Step 4: `rotear` substitui `should_continue`**

Em `src/forge/orchestration/graph.py`, trocar `should_continue` (linhas 15-25) por:

```python
def rotear(state: dict, max_rounds: int, max_passos: int) -> str:
    passos = state.get("passos", 0)
    if passos >= max_passos:
        logger.warning("Budget exhausted - stopping", passos=passos, max=max_passos)
        return END

    review = state.get("review")
    rounds = state.get("rounds", 0)
    if review is None:
        return "write"

    if review.verificar:
        logger.info("Handoff to research", alegacoes=len(review.verificar))
        return "research"

    if review.aprovado:
        logger.info("Review approved - stopping", round=rounds)
        return END

    if rounds >= max_rounds:
        logger.warning("Max review rounds reached", round=rounds, max=max_rounds)
        return END

    logger.debug("Continuing to write phase", round=rounds)
    return "write"
```

O orçamento é a primeira checagem e não depende de mais nada. É o que torna a terminação garantida em vez de heurística.

- [ ] **Step 5: Ligar a aresta condicional**

Substituir o bloco `add_conditional_edges` (`graph.py:87-91`):

```python
    g.add_conditional_edges(
        "review",
        lambda s: rotear(s, settings.max_review_rounds, settings.max_passos),
        {"write": "write", "research": "research", END: END},
    )
```

- [ ] **Step 6: `pedido` preenchido no handoff de review**

Em `node_review`, gravar o motivo para o `research` reentrante da Tarefa 9:

```python
    def node_review(state):
        logger.debug("Starting review phase")
        result = review_stage.revisar(model, state["roteiro"])
        rounds = state.get("rounds", 0) + 1
        pedido = "\n".join(result.verificar) if result.verificar else None
        logger.info("Review completed", aprovado=result.aprovado, round=rounds)
        return {"review": result, "rounds": rounds, "pedido": pedido}
```

- [ ] **Step 7: Rodar os testes**

Run: `uv run pytest tests/orchestration/test_graph.py -v`
Expected: PASS em todos, incluindo `test_grafo_termina_com_modelo_patologico`.

Os testes antigos `test_should_continue_*` referenciam a função removida — reescreva-os como os `test_rotear_*` do Step 1 (já cobrem os mesmos casos) e apague os antigos.

- [ ] **Step 8: Rodar a suíte inteira**

Run: `uv run pytest`
Expected: tudo passando.

---

## Tarefa 9: `research` reentrante e rota `write → research`

**Files:**
- Modify: `src/forge/prompts/research.md`
- Modify: `src/forge/agents/research.py`
- Modify: `src/forge/orchestration/graph.py`

**Interfaces:**
- Consumes: `pedido` no state (Tarefa 8); `falta_pesquisa` em `RoteiroDraft` (Tarefa 8); `LE` de `research` (Tarefa 6).
- Produces: `pesquisar(model, tema, provider="anthropic", pedido=None) -> tuple[str, list[Fonte], str]`

- [ ] **Step 1: Slot `{pedido}` no prompt**

`src/forge/prompts/research.md` completo:

```markdown
Pesquise na web material sólido para um roteiro sobre: {tema}

Confirme fatos, escolas e ideias em fontes primárias. Use a ferramenta de busca.

{skills}

{pedido}

Produza notas de pesquisa densas: ideias-chave, filósofos e escolas relevantes,
exemplos concretos e, quando confirmadas, referências com autor e obra.
```

- [ ] **Step 2: `pesquisar` aceita `pedido`**

Em `src/forge/agents/research.py`:

```python
def _fmt_pedido(pedido: str | None) -> str:
    if not pedido:
        return ""
    return (
        "ATENÇÃO — esta é uma passagem dirigida, não uma pesquisa do zero.\n"
        "Verifique apenas os pontos abaixo e devolva o que confirmou ou não:\n"
        f"{pedido}"
    )


def pesquisar(
    model, tema: str, provider: str = "anthropic", pedido: str | None = None
) -> tuple[str, list[Fonte], str]:
    if provider == "anthropic":
        brief, raw = _pesquisar_server_side(model, tema, pedido)
    else:
        brief, raw = _pesquisar_client_side(model, tema, pedido)
    fontes = _extrair_fontes(model, brief)
    return brief, fontes, raw
```

E as duas funções internas aceitam e repassam `pedido`:

```python
def _pesquisar_server_side(model, tema: str, pedido: str | None) -> tuple[str, str]:
    search = model.bind_tools([WEB_SEARCH_TOOL])
    resp = search.invoke([HumanMessage(content=load_prompt("research").format(
        tema=tema, skills=load_skills(SKILLS, "research"), pedido=_fmt_pedido(pedido)
    ))])
    brief = _texto(resp)
    return brief, str(resp.content)


def _pesquisar_client_side(model, tema: str, pedido: str | None) -> tuple[str, str]:
    tool_model = model.bind_tools([buscar_web])
    messages = [HumanMessage(content=load_prompt("research").format(
        tema=tema, skills=load_skills(SKILLS, "research"), pedido=_fmt_pedido(pedido)
    ))]
    bruto: list[str] = []
    for _ in range(MAX_SEARCH_ROUNDS):
        resp = tool_model.invoke(messages)
        if not getattr(resp, "tool_calls", None):
            return _texto(resp), "\n\n".join(bruto)
        messages.append(resp)
        for call in resp.tool_calls:
            resultado = buscar_web.invoke(call["args"])
            bruto.append(f"### query: {call['args']}\n{resultado}")
            messages.append(ToolMessage(content=resultado, tool_call_id=call["id"]))
    resp = tool_model.invoke(messages)
    return _texto(resp), "\n\n".join(bruto)
```

- [ ] **Step 3: `node_research` repassa o pedido e acumula o brief**

Numa reentrada, o brief novo é dirigido e não substitui o anterior — acumula:

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

`pedido` é zerado ao ser consumido — senão a próxima passagem por `research` acha que ainda é dirigida.

`LE` de `research` já inclui `pedido` e `tema` (Tarefa 6), mas agora precisa de `research_notes` para acumular. Atualizar:

```python
# agents/research.py
LE = ["tema", "pedido", "research_notes"]
```

- [ ] **Step 4: Rota `write → research`**

`node_write` passa a poder redirecionar. `escrever` precisa devolver o draft junto do roteiro para expor `falta_pesquisa` — trocar o retorno em `agents/write.py`:

```python
def escrever(
    model,
    tema: str,
    tese: str,
    esboco: str,
    research: str,
    fontes: list[Fonte],
    notas: list[Nota] | None = None,
) -> tuple[Roteiro, str | None]:
    logger.debug("Starting write phase", tema=tema[:50] + "..." if len(tema) > 50 else tema)
    prompt = load_prompt("write").format(
        tese=tese,
        esboco=esboco,
        research=research,
        notas=_fmt_notas(notas),
        skills=load_skills(SKILLS, "write"),
    )
    draft = model.with_structured_output(RoteiroDraft).invoke([HumanMessage(content=prompt)])
    roteiro_resultado = Roteiro(tema=tema, tese=tese, secoes=draft.secoes, fontes=fontes)
    logger.info(
        "Write phase completed",
        num_secoes=len(roteiro_resultado.secoes),
        falta_pesquisa=bool(draft.falta_pesquisa),
    )
    return roteiro_resultado, draft.falta_pesquisa
```

E em `graph.py`, `node_write` devolve `Command` quando falta pesquisa:

```python
from langgraph.types import Command


    def node_write(state):
        review = state.get("review")
        notas = review.notas if review is not None else None
        logger.debug("Starting write phase", tema=state["tema"])
        roteiro, falta = write_stage.escrever(
            model,
            state["tema"],
            state["tese"],
            state["esboco"],
            state["research_notes"],
            state["fontes"],
            notas,
        )
        if falta:
            logger.info("Handoff to research from write", motivo=falta[:120])
            return Command(goto="research", update={"roteiro": roteiro, "pedido": falta})
        logger.debug("Write phase completed", secoes_count=len(roteiro.secoes))
        return {"roteiro": roteiro}
```

O wrapper da Tarefa 6 recebe um `Command` em vez de dict quando há handoff. Ajustar `com_wrapper` para não tentar gravar artefato de um `Command`:

```python
def com_wrapper(nome, fn, le):
    def wrapped(state):
        entrada = {k: state[k] for k in le if k in state}
        resultado = fn(entrada)
        if isinstance(resultado, Command):
            return resultado
        bruto = resultado.pop("_raw", None)
        gravar_artefato(state["run_dir"], nome, resultado)
        if bruto is not None:
            gravar_bruto(state["run_dir"], nome, bruto)
        return {**resultado, "passos": state.get("passos", 0) + 1}
    return wrapped
```

Um `Command` de handoff não conta passo nem gera artefato: o trabalho do `write` não foi concluído, foi devolvido.

Para que `Command(goto=...)` funcione a partir de `write`, declarar os destinos possíveis no `add_node`:

```python
    g.add_node("write", com_wrapper("write", node_write, write_stage.LE),
               destinations=("research",))
```

- [ ] **Step 5: Corrigir as chamadas de `escrever` na suíte**

Run: `grep -rn "escrever(" tests --include='*.py'`

Ajustar cada `roteiro = escrever(...)` para `roteiro, falta = escrever(...)`.

- [ ] **Step 6: Rodar a suíte**

Run: `uv run pytest`
Expected: tudo passando.

- [ ] **Step 7: Verificar o ciclo completo**

Run: `uv run forge roteiro --tema "estoicismo e ansiedade"`
Expected: a run termina. Se o review pedir verificação, o stream mostra `[review]` seguido de `[research]` e o diretório ganha um `01-research.md` atualizado com a seção "Verificação dirigida".

Conferir que `04-review-r1.md` e `04-review-r2.md` coexistem quando há mais de uma rodada, e que nenhum arquivo foi sobrescrito.

---

## Verificação final

- [ ] `uv run pytest` — suíte inteira verde
- [ ] `grep -rn "forge\.\(writer\|orchestrator\)" src tests --include='*.py'` — sem saída
- [ ] `uv run forge roteiro --tema "teste final"` — produz roteiro e diretório de run completo
- [ ] `uv run forge roteiro --retomar <run>` após apagar `03-*` e `04-*` — reexecuta só write e review
- [ ] Nenhum `git add` e nenhum `git commit` foi executado em nenhuma etapa
