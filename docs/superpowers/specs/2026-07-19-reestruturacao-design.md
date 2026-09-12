# Reestruturação de `src/forge` — Design

**Data:** 2026-07-19
**Status:** aprovado, pronto para plano de implementação

## Objetivo

Reorganizar o código conforme a "Estrutura sugerida" de
`docs/CreatorBrain_Plataforma_Arquitetura_Visao.md`, e fechar as lacunas de V1
que a reorganização deixa expostas: subsistema de skills, isolamento entre
agentes, handoff dinâmico e artefatos por run.

Quatro restrições vieram do usuário durante o brainstorm e governam o desenho:

1. Cada agente acessa somente as skills de que precisa. Se precisar de
   conhecimento de outro agente, passa o fluxo para o agente responsável.
2. Cada agente tem prompt exclusivo.
3. Cada agente grava o que produziu em arquivo; os arquivos são o registro
   durável da run.
4. Cada agente roda em sessão própria, sem herdar contexto de outro agente.

A restrição 2 já é satisfeita hoje (um prompt por estágio em
`writer/prompts/`). A restrição 4 também: todo agente abre contexto limpo com
`model.invoke([HumanMessage(...)])` e nenhum histórico de mensagens atravessa
estágios. Nenhuma das duas exige código novo — o desenho apenas as preserva.

## Estrutura alvo

```
src/forge/
├── cli.py                      (fica na raiz — entrypoint do console_script)
├── agents/
│   ├── tema.py                 ← writer/tema.py
│   ├── research.py             ← writer/research.py
│   ├── plan.py                 ← writer/plan.py
│   ├── write.py                ← writer/write.py
│   └── review.py               ← writer/review.py
├── orchestration/
│   ├── graph.py                ← orchestrator/graph.py
│   └── state.py                ← orchestrator/state.py
├── domain/
│   └── models.py               ← writer/models.py
├── llms/
│   ├── model.py                ← llm/model.py
│   └── parsing.py              ← `_texto()`, extraído de writer/tema.py
├── prompts/
│   ├── loader.py               ← writer/_prompts.py
│   └── *.md                    ← writer/prompts/*.md
├── skills/                     NOVO
│   ├── loader.py
│   └── *.md
├── services/
│   ├── storage.py              ← output/storage.py
│   └── artefatos.py            NOVO
└── infrastructure/
    ├── config.py               ← config.py
    └── logging.py              ← logging.py
```

`writer/`, `orchestrator/`, `llm/` e `output/` deixam de existir.

### Decisões de fronteira

**Só pastas com código.** `rag/` e `memory/` são V2; `workflows/` só faz
sentido quando houver mais de um fluxo (roteiro, SEO, thumbnail) e
`orchestration/` virar a máquina compartilhada entre eles. Nenhuma pasta
vazia, nenhum `.gitkeep`. A árvore reflete o que existe.

**`orchestration/`, não `workflows/`.** O documento lista as duas sem
distinguir. Existe um fluxo; uma pasta basta.

**`config.py` em `infrastructure/`.** O `config/` do documento é top-level,
irmão de `src/` — lugar de arquivo de configuração, não de código. A classe
`Settings` é adaptador de ambiente.

**`llms/parsing.py` é correção, não movimentação.** Hoje `research.py:7` faz
`from forge.writer.tema import _texto` — um agente importando função privada de
outro. Depois do split isso viraria acoplamento entre irmãos em `agents/`.
`_texto` desempacota blocos de conteúdo de resposta do LLM: pertence a `llms/`.

**Fora de escopo, deliberadamente.** Os dois defeitos do branch OpenAI em
`llm/model.py:22-23` (`model` hardcoded como `gpt-5-nano`, ignorando
`settings.model`; e fallback de `api_key` para a chave da Anthropic) viajam
intactos. Corrigir é mudança de comportamento e merece commit próprio, fora de
um diff de movimentação.

## Skills

### Formato

Uma skill é um arquivo `.md` com frontmatter e seções fixas.

```markdown
---
nome: fact_check
dono: research
dominio: false
---

## Critérios
Aspa só vale com frase + autor + obra confirmados por busca nesta sessão.
Ideia amplamente conhecida dispensa busca — atribui sem aspas.

## Anti-padrões
- Site de coletânea de frases não confirma nada
- "Como disse Nietzsche..." sem obra

## Procedimento
Monta query com autor + obra + trecho literal. Fonte terciária não fecha
verificação. Na dúvida, devolve não-confirmado.
```

### Critério versus procedimento

A divisão reconcilia a restrição 1 (exclusividade) com o motivo pelo qual
skills valem a pena (rubrica compartilhada).

- **Critério** — o que conta como bom. Compartilhado entre quem produz e quem
  julga. Se o `review` não vê o critério de retenção, ele inventa a própria
  régua e reprova por motivo que o `write` nunca foi instruído a atender.
- **Procedimento** — como executar. Exclusivo do `dono`. O procedimento de
  `fact_check` pertence ao `research`, que tem a ferramenta de busca. O
  `review` detecta o problema e passa o fluxo adiante; nunca busca.

### Loader

```python
load_skills(nomes: list[str], agente: str) -> str
```

Concatena as skills pedidas e remove `## Procedimento` quando
`agente != dono`. Devolve markdown pronto para o slot `{skills}` do prompt.

### Quem pede o quê

Declarado no arquivo do agente, não na skill. A inversão importa: com a skill
declarando onde entra, adicionar uma skill nova pode ampliar silenciosamente o
contexto de um agente que ninguém revisou.

| Agente     | `SKILLS`                                        | Dono de                |
| ---------- | ----------------------------------------------- | ---------------------- |
| `tema`     | —                                               | —                      |
| `research` | `fact_check`                                    | `fact_check`           |
| `plan`     | `story`                                         | `story`                |
| `write`    | `writing`, `story`, `retention`, `fact_check`   | `writing`, `retention` |
| `review`   | `story`, `retention`, `fact_check`              | —                      |

`review` não é dono de nada, por desenho: julga contra critério alheio e
devolve o fluxo, nunca executa procedimento.

### Skills iniciais

Quatro, todas transversais (`dominio: false`), extraídas de texto que já existe
nos prompts. Nada inventado:

| Skill        | Origem                        | Dono       |
| ------------ | ----------------------------- | ---------- |
| `fact_check` | `research.md:5-11`, `write.md:14` | `research` |
| `retention`  | `review.md:1`                 | `write`    |
| `writing`    | `write.md:11-13`              | `write`    |
| `story`      | `plan.md:8-10`                | `plan`     |

Os prompts perdem essas linhas e ganham o slot `{skills}`.

### Seleção por domínio

Implementada e dormente. Skills com `dominio: true` seriam escolhidas por LLM
no node `tema` e gravadas em `state["skills_dominio"]`. Como nenhuma das quatro
iniciais é de domínio, o catálogo nasce vazio e o seletor não faz chamada
alguma — custo zero até a primeira skill de filósofo entrar.

## Isolamento entre agentes

Sessões já são isoladas (restrição 4). O vazamento real é o state: todo node
recebe `RoteiroState` inteiro e alcança tudo.

Cada agente declara o que lê, ao lado do que declara em `SKILLS`:

```python
# agents/write.py
SKILLS = ["writing", "story", "retention"]
LE     = ["tema", "tese", "esboco", "research_notes", "fontes", "pedido"]
```

O wrapper monta o sub-dict e passa só isso. Campo novo no state não alcança
nenhum agente sem alguém pedir explicitamente, no diff.

## Artefatos por run

### Layout

```
output/runs/2026-07-19-143012-o-paradoxo-da-escolha/
├── 00-tema.md
├── 01-research.md          contrato: brief curado + fontes no frontmatter
├── 01-research.raw.md      auditoria: notas completas, resultados de busca
├── 02-plan.md
├── 03-write-r1.md
├── 04-review-r1.md
├── 05-write-r2.md
├── 06-review-r2.md
└── roteiro.md              final (o que hoje vai para output/roteiros/)
```

O sufixo `-rN` resolve o handoff sem versionamento: cada passagem por um agente
gera arquivo próprio, e o histórico do ping-pong fica legível em ordem.

Hoje só o `research` produz `.raw.md`: é o único agente com tool calls e
conteúdo externo em volume. Os demais devolvem saída estruturada, onde o
contrato já é a saída integral — não há bruto a separar. A regra vale para
qualquer agente que venha a ter as duas coisas.

### Curado versus bruto

Conteúdo bruto e conteúdo de contrato vivem em **arquivos separados**, sempre.
Nenhum agente lê o bruto.

- `NN-<agente>.md` — contrato. Documento fechado, curado pelo próprio agente,
  com o que o próximo estágio precisa. É o que os agentes seguintes consomem.
- `NN-<agente>.raw.md` — bruto. Saída integral, resultados de busca, tool
  calls. Existe para auditoria e para a ingestão de V2. Fora do contrato.

Isso encolhe o contexto do `write`, que hoje engole as notas de pesquisa
inteiras. A curadoria é segura porque existe válvula de escape: se o corte
jogou fora algo necessário, o `write` sinaliza `falta_pesquisa` e o fluxo
volta para o `research` (ver Handoff).

Para `research`, o brief sai do próprio prompt — sem invoke extra. As funções
`_pesquisar_server_side` e `_pesquisar_client_side` passam a devolver
`(brief, raw)`.

**O bruto nunca entra no state.** `state["research_notes"]` recebe o brief; o
`raw` segue direto para o disco.

```
_pesquisar_*()  ->  (brief, raw)
                     |      |
                     |      +-> 01-research.raw.md   (só disco)
                     +-> state["research_notes"]
                         01-research.md              (mesmo conteúdo)
```

Sem isso a curadoria só teria efeito na retomada: no fluxo normal o `write`
leria o bruto do state e o ganho de contexto desapareceria.

A invariante que isso garante: **state e artefato de contrato carregam
conteúdo idêntico**. Não existe drift possível entre os dois caminhos, e
`--retomar` entrega exatamente o que o fluxo normal entregaria.

### Escrita

Um único decorator aplicado em `build_graph` cobre as três
responsabilidades transversais — estreitar o state pelo `LE` do agente,
gravar o artefato e incrementar o orçamento. O node continua função pura;
nenhum agente conhece caminho de arquivo nem contagem de passos.

```python
def com_wrapper(nome, fn, le):
    def wrapped(state):
        resultado = fn({k: state[k] for k in le if k in state})
        gravar_artefato(state["run_dir"], nome, resultado, state["rounds"])
        return {**resultado, "passos": state.get("passos", 0) + 1}
    return wrapped
```

`passos` é incrementado aqui, num lugar só: qualquer node que executa custa
um passo, independente de como o fluxo chegou nele. É o que torna o orçamento
uma garantia de terminação e não uma heurística.

### Retomada

```bash
forge roteiro --retomar output/runs/2026-07-19-143012-o-paradoxo-da-escolha
```

`build_graph` passa a aceitar `inicio: str`. A CLI varre o `run_dir`, carrega os
artefatos existentes no state inicial e passa o primeiro estágio sem arquivo
como entry point. Sem node roteador extra, sem checagem dentro dos agentes.

No fluxo normal os agentes leem do state — rápido, tipado, sem parse. Leem de
arquivo apenas na retomada. Uma verdade por vez; state e arquivo nunca são
fonte simultânea.

O ganho é o loop de desenvolvimento: iterar no prompt do `write` sem repagar
`research`, que é a chamada mais lenta do pipeline.

## Handoff

Roteamento dinâmico com mecânica completa e superfície restrita. Corresponde à
regra "Revisor pode reprovar qualquer etapa" (documento de arquitetura,
linha 222).

### State

`RoteiroState` permanece — `StateGraph(RoteiroState)` exige um schema, é o tipo
do que trafega entre nodes. Ganha quatro campos:

```python
skills_dominio: list[str]   # escolhidas no node tema (dormente)
pedido: str | None          # por que o fluxo voltou
passos: int                 # orçamento global de execuções
run_dir: Path               # diretório de artefatos desta run
```

#### Conteúdo versus controle

Os campos são de duas naturezas, e a distinção governa o que vai para disco:

| Natureza      | Campos                                                              | Em artefato? |
| ------------- | ------------------------------------------------------------------- | ------------ |
| **Conteúdo**  | `tema`, `research_notes`, `fontes`, `tese`, `esboco`, `roteiro`      | sim          |
| **Controle**  | `rounds`, `passos`, `pedido`, `run_dir`, `skills_dominio`, `review.verificar` | não |

Conteúdo é espelhado nos artefatos de contrato e reconstruível do disco. No
state ele funciona como cache tipado: evita reparsear markdown a cada passo e
evita round-trip lossy de `list[Fonte]`.

Controle é orquestração, não conteúdo — não tem versão em disco e não deve
ter. É por isso que o state não é redundante com os artefatos: metade dele
carrega fluxo que arquivo nenhum deveria segurar.

Consequência para `--retomar`: apenas campos de conteúdo são reconstruídos a
partir dos artefatos. Campos de controle reiniciam.

### Sinalização

Pelo schema do próprio agente, sem parsing de texto livre:

```python
class ReviewResult(BaseModel):
    aprovado: bool
    notas: list[Nota] = Field(default_factory=list)
    verificar: list[str] = Field(default_factory=list)   # NOVO

class RoteiroDraft(BaseModel):
    secoes: list[Secao]
    falta_pesquisa: str | None = None                    # NOVO
```

### Rotas

Ativas agora:

- `review → write` (já existe)
- `review → research` — quando `verificar` não é vazio
- `write → research` — quando `falta_pesquisa` está preenchido

Possíveis mas desligadas: qualquer rota para `plan` ou `tema`. Ligar depois é
uma linha.

### Roteamento

```python
def rotear(state, max_rounds, max_passos) -> str:
    if state["passos"] >= max_passos:
        return END                    # orçamento vence sempre
    review = state["review"]
    if review.verificar:
        return "research"
    if review.aprovado:
        return END
    if state["rounds"] >= max_rounds:
        return END
    return "write"
```

O orçamento é checado primeiro, antes de qualquer lógica: é a garantia de
terminação e não pode depender de mais nada. `FORGE_MAX_PASSOS`, padrão 20.

### `research` reentrante

Quando chega por handoff, `pedido` está preenchido e o prompt ganha slot
`{pedido}`: busca dirigida àquela alegação, não pesquisa do zero. Sem isso o
handoff refaz trabalho e o orçamento evapora.

## Plano de commits

A ordem importa: artefatos antes de handoff, porque o handoff gera os `-r2` e a
camada de artefato precisa estar estável antes.

| # | Commit | Conteúdo |
| - | ------ | -------- |
| 1 | `refactor(structure)` | `git mv` + imports + `llms/parsing.py`. ~40 arquivos, zero mudança de comportamento. |
| 2 | `feat(skills)` | Loader, ownership, slot nos prompts, 4 skills, declarações `SKILLS`/`LE`. |
| 3 | `feat(orchestration)` | Artefatos por run, curado + raw, `--retomar`. |
| 4 | `feat(orchestration)` | Handoff, sinalização por schema, orçamento de passos. |

## Testes

Testes não são foco deste trabalho, por decisão do usuário. A posição adotada,
explícita:

**Commit 1 atualiza os 26 imports dos testes.** Não é escrever teste — é
higiene da movimentação. Sem isso a suíte inteira quebra no import e a única
rede de segurança existente some.

**Commits 2, 3 e 4 vão sem cobertura nova.** Fica descoberto:

- o corte de `## Procedimento` por dono;
- o parse dos artefatos na retomada;
- a terminação por orçamento.

O terceiro é o de maior risco: um defeito de terminação queima crédito de API
silenciosamente. Se houver exceção a abrir para um único teste, é esse.

## Fora de escopo

- Correção dos defeitos do branch OpenAI (`model.py:22-23`) — commit próprio.
- Suporte a Ollama.
- `rag/`, `memory/`, `workflows/` — V2 e V3.
- Skills de domínio com conteúdo (`nietzsche`, `estoicismo`) — a mecânica fica
  pronta, o conteúdo entra depois.
- Agentes de V5+ (`seo`, `thumbnail`, `publisher`).
