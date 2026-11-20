# Conquistas Cósmicas — roteiro de canal e embalagem — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o forge escrever roteiros de 11–16 min com a voz e as técnicas de retenção do canal Conquistas Cósmicas, escolher temas que o acervo sustenta e entregar a embalagem de publicação (títulos, thumbnail, descrição, capítulos, tags).

**Architecture:** O contrato das nove seções fica intacto; `escrever()` passa a fazer uma chamada de modelo por seção e a revisão reescreve só as seções citadas nas notas. Identidade do canal entra por skills/prompts em markdown. Citações e embalagem são artefatos tipados: as citações são derivadas por código, a embalagem tem uma chamada de modelo e montagem/gates determinísticos.

**Tech Stack:** Python 3.12, LangGraph, Pydantic v2, httpx, pytest (modelo simulado por `ScriptedModel`, acervo por `FakeAcervo`). Nenhuma dependência nova.

**Spec:** `docs/superpowers/specs/2026-11-15-conquistas-cosmicas-roteiro-embalagem-design.md`

## Global Constraints

- Nenhuma afirmação sem passagem do acervo; nenhum fallback web; o forge não ingere livros.
- `SECOES_NOMES` (Gancho, Estake, Tensao, Virada, Filosofo, Prova, Espelho, Aplicacao, Fecho) não muda.
- Alvos por seção (mín–máx palavras): Gancho 60–110, Estake 130–220, Tensao 180–280, Virada 180–280, Filosofo 260–380, Prova 280–400, Espelho 180–280, Aplicacao 220–320, Fecho 110–180.
- Total do roteiro: grave abaixo de 1.500 palavras, aviso acima de 2.800.
- Cadência: `PALAVRAS_POR_SEGUNDO = 2.5` (já em `narracao/fatiar.py`).
- Eixos: `estoicismo`, `autoconhecimento`, `niilismo-absurdo`, `etica-digital-ia`.
- Testes sem rede e sem modelo real. Baseline em 2026-11-15: 904 passam, 1 falha pré-existente (`tests/executors/test_audio_generate.py::test_build_argv_uses_fixed_safe_batch_flags_and_no_sampling_knobs`) que não é desta frente.
- **Sem commits.** O branch `feat/codex-oauth-standalone` tem mudanças não commitadas de outra frente; nada é commitado, revertido nem stageado. Onde o plano diria "commit", roda-se a suíte como checkpoint.
- `src/forge/fluxos.py`, `skills/conquistas-cosmicas/SKILL.md` e `scripts/validar_roteiro.py` não são tocados.
- Logs por `structlog` com campos key=value; prosa de log e nomes de domínio em português.

## Review Focus

1. Nota do revisor com seção acentuada, em outra caixa ou inexistente ("Tensão", "introdução") — esperado: canonizar; nome fora do contrato vira nota geral, nunca é descartado em silêncio. Teste na Task 3.
2. `--retomar` de run anterior a esta mudança (plano sem eixo, citação sem `traducao`) — esperado: carrega com `eixo=None`, sem erro. Teste na Task 2.
3. Acervo fora do ar ou catálogo vazio na sugestão de tema; busca individual que estoura o prazo — esperado: busca que falha é pulada com aviso; sem nenhum candidato sustentado, `SemTemaSustentado`, nunca tema inventado. Teste na Task 5.
4. Juiz de temas devolve índice fora da lista ou menos veredictos que candidatos — esperado: índice inválido ignorado, candidato sem veredicto tratado como não sustentado. Teste na Task 5.
5. Modelo devolve rótulo de capítulo para seção inexistente, omite seções ou põe quebra de linha no título — esperado: rótulo ausente cai no papel da seção, texto é achatado em uma linha. Teste na Task 6.

---

## File Structure

| Arquivo | Responsabilidade |
|---|---|
| `src/forge/domain/roteiro.py` (mod) | Alvos e instruções das nove seções |
| `src/forge/services/qualidade_roteiro.py` (mod) | Gate de total, preâmbulo no Gancho, CTA agressivo |
| `src/forge/skills/canal.md` (novo), `writing.md`, `retention.md`, `story.md` (mod) | Identidade e técnicas do canal |
| `src/forge/skills/loader.py` (mod) | `EIXOS`, `carregar_eixo`, `resumo_eixos` |
| `src/forge/domain/models.py` (mod) | `Plano.eixo`, `Nota.secao`, `SecaoDraft`, `CitacaoLiteral.traducao`; sai `RoteiroDraft` |
| `src/forge/agents/plan.py`, `review.py`, `write.py` (mod) | Eixo, notas por seção, escrita por seção |
| `src/forge/prompts/write_secao.md` (novo), `plan.md`, `review.md` (mod), `write.md` (removido) | Prompts |
| `src/forge/orchestration/state.py`, `graph.py`, `services/artefatos.py`, `executors/roteiro.py` (mod) | `eixo` no state, no artefato do plano e na retomada |
| `src/forge/services/citacoes.py` (novo) | `Citacao`, `derivar_citacoes`, `gravar_citacoes`, `carregar_citacoes` |
| `src/forge/agents/research.py` (mod) | `PassageEvidence.url` |
| `src/forge/services/acervo.py` (mod) | `Livro`, `Acervo.livros()` |
| `src/forge/agents/tema.py` (mod), `prompts/tema_candidatos.md`, `prompts/tema_juiz.md` (novos), `prompts/tema.md` (removido) | Seletor de tema |
| `src/forge/domain/embalagem.py` (novo) | Modelos da embalagem |
| `src/forge/services/qualidade_embalagem.py` (novo) | Gates da embalagem |
| `src/forge/agents/embalagem.py`, `prompts/embalagem.md` (novos) | Proposta, montagem, gravação |
| `src/forge/cli.py`, `executors/plano_midia.py`, `infrastructure/config.py` (mod) | `forge temas`, embalagem no CLI e no Studio, `aviso_ia` |
| `CLAUDE.md`, `README.md`, `.env.example` (mod) | Documentação |

Helper de teste compartilhado, em `tests/conftest.py`: `texto_de(n: int) -> str` (n palavras em frases curtas terminadas em ponto) e `roteiro_longo(**sobrescritas) -> Roteiro` (nove seções dentro dos alvos, Espelho terminando em pergunta, blocos com `referencias=["4363/ch2/p7"]`).

---

### Task 1: Alvos longos e gates de retenção

**Files:**
- Modify: `src/forge/domain/roteiro.py`, `src/forge/services/qualidade_roteiro.py`, `tests/conftest.py`
- Test: `tests/domain/test_roteiro.py`, `tests/services/test_qualidade_roteiro.py`

**Interfaces:**
- Produces: `ARQUITETURA` com os alvos novos; `PALAVRAS_TOTAL_MINIMO = 1500`, `PALAVRAS_TOTAL_AVISO = 2800` em `qualidade_roteiro`; códigos de achado `roteiro_curto` (grave), `roteiro_longo` (aviso), `gancho_com_preambulo` (grave), `cta_agressivo` (aviso); `metrics["palavras_total"]`. Helpers `texto_de` e `roteiro_longo` em `tests/conftest.py`.

- [ ] **Step 1: Testes que falham**

```python
# tests/domain/test_roteiro.py
def test_alvos_somam_duracao_de_video_longo():
    assert sum(s.alvo_palavras[0] for s in ARQUITETURA) == 1600
    assert sum(s.alvo_palavras[1] for s in ARQUITETURA) == 2450
    assert {s.nome: s.alvo_palavras for s in ARQUITETURA}["Filosofo"] == (260, 380)

# tests/services/test_qualidade_roteiro.py
def test_roteiro_dentro_dos_alvos_passa():
    report = avaliar_roteiro(roteiro_longo())
    assert report.approved and report.metrics["palavras_total"] >= 1600

def test_total_abaixo_de_1500_reprova():
    curto = roteiro_longo(Prova=texto_de(170), Filosofo=texto_de(160))  # cada seção ≥ 60% do mínimo
    assert "roteiro_curto" in avaliar_roteiro(curto).codes

def test_gancho_com_saudacao_reprova():
    r = roteiro_longo(Gancho="Olá, bem-vindo ao canal. " + texto_de(70))
    assert "gancho_com_preambulo" in avaliar_roteiro(r).codes

@pytest.mark.parametrize("abertura", ["Neste vídeo vamos falar", "Hoje vamos entender", "Antes de começar"])
def test_gancho_com_preambulo_reprova(abertura): ...

def test_cta_agressivo_fora_do_fecho_e_aviso():
    r = roteiro_longo(Tensao=texto_de(200) + " Inscreva-se no canal.")
    report = avaliar_roteiro(r)
    assert report.approved
    assert any(f.code == "cta_agressivo" and f.section == "Tensao" for f in report.findings)
```

- [ ] **Step 2: Rodar e ver falhar** — `uv run pytest tests/domain/test_roteiro.py tests/services/test_qualidade_roteiro.py -q`
- [ ] **Step 3: Implementar**
  - `ARQUITETURA`: alvos das Global Constraints. Instruções reescritas: Gancho — cena ou tensão dirigida a "você", promessa do que se leva, sem saudação; Filosofo e Prova — objeção forte tratada pelo melhor lado; Aplicacao — uma prática para hoje; Fecho — devolve a pergunta do Gancho transformada e faz um convite suave.
  - `avaliar_roteiro`: soma `_words(secao.conteudo)` das seções válidas em `metrics["palavras_total"]`; emite `roteiro_curto`/`roteiro_longo`.
  - `conferir_secao`: no Gancho, regex de preâmbulo sobre as 25 primeiras palavras (`olá|oi|bem-vind|sejam? bem|neste vídeo|hoje (vamos|eu vou|a gente vai|nós vamos)|antes de começar|fala,? (galera|pessoal)`, sem caixa nem acento obrigatório); fora do Fecho, regex de CTA (`inscreva-se|se inscrev|deixe (o |seu )?like|ative o sininho|curta (o|este) vídeo|compartilhe (o|este) vídeo`).
  - Testes existentes que montam roteiros curtos para passar no gate (`test_gancho_66_palavras_passam_com_desenvolvimento_mais_longo` e os de `tests/executors/test_roteiro.py`) passam a usar `roteiro_longo`/`texto_de`; os que testam reprovação por seção curta mantêm a intenção com os números novos.
- [ ] **Step 4: Rodar e ver passar** — os dois arquivos acima e `uv run pytest tests/executors/test_roteiro.py -q`
- [ ] **Step 5: Checkpoint** — `uv run pytest -q`; só a falha de baseline.

### Task 2: Identidade do canal e eixo

**Files:**
- Create: `src/forge/skills/canal.md`
- Modify: `src/forge/skills/writing.md`, `retention.md`, `story.md`, `loader.py`; `src/forge/domain/models.py`; `src/forge/agents/plan.py`, `review.py`; `src/forge/prompts/plan.md`, `review.md`; `src/forge/orchestration/state.py`, `graph.py`; `src/forge/services/artefatos.py`; `src/forge/executors/roteiro.py`
- Test: `tests/agents/test_plan.py`, `tests/agents/test_review.py`, `tests/test_artefatos.py`, `tests/agents/test_models.py`, novo `tests/test_skills_canal.py`

**Interfaces:**
- Produces:
  - `forge.skills.loader.EIXOS: tuple[str, ...]`, `carregar_eixo(eixo: str | None) -> str` (texto de `conquistas-cosmicas/references/<eixo>.md`; `"(sem referência de eixo)"` para `None` ou eixo desconhecido), `resumo_eixos() -> str` (uma linha por eixo: `- <eixo>: <linha "Foco do canal neste eixo">`).
  - `Plano.eixo: Literal[...] | None = None`; `Nota.secao: str | None = None`.
  - `planejar(model, tema, research, *, run_dir=None) -> Plano` (antes devolvia tupla).
  - `revisar(..., eixo: str | None = None)`; `review.LE` e `write.LE` ganham `"eixo"`; `RoteiroState.eixo: str | None`.
  - Artefato do plano: frontmatter `eixo: <valor>` quando houver; `carregar_run` e `ScriptExecutor._resume_content` devolvem `eixo` (ou `None`).

- [ ] **Step 1: Testes que falham**

```python
# tests/test_skills_canal.py
def test_canal_e_carregada_com_procedimento_so_para_o_dono():
    assert "## Procedimento" in load_skills(["canal"], "write")
    assert "## Procedimento" not in load_skills(["canal"], "review")

def test_writing_pede_segunda_pessoa():
    texto = load_skills(["writing"], "write").casefold()
    assert "segunda pessoa" in texto and "primeira pessoa" not in texto

@pytest.mark.parametrize("eixo", EIXOS)
def test_cada_eixo_tem_referencia(eixo):
    assert carregar_eixo(eixo).startswith("#")

def test_eixo_ausente_ou_desconhecido_nao_quebra():
    assert carregar_eixo(None) == carregar_eixo("xyz") == "(sem referência de eixo)"

def test_resumo_lista_os_quatro_eixos():
    assert all(f"- {e}:" in resumo_eixos() for e in EIXOS)

# tests/agents/test_plan.py
def test_planejar_devolve_eixo(scripted):
    model = scripted(structured=[Plano(tese="t", esboco="e", eixo="niilismo-absurdo")])
    assert planejar(model, "tema", "notas").eixo == "niilismo-absurdo"

# tests/test_artefatos.py
def test_plano_persiste_e_retoma_eixo(tmp_path): ...      # gravar_artefato("plan", {..., "eixo": "estoicismo"}) → carregar_run()[0]["eixo"] == "estoicismo"
def test_plano_antigo_sem_eixo_retoma_com_none(tmp_path): ...  # arquivo 02-plan.md no formato atual → eixo is None
```

- [ ] **Step 2: Rodar e ver falhar**
- [ ] **Step 3: Implementar**
  - `canal.md` (`nome: canal`, `dono: write`, `dominio: true`): Critérios — segunda pessoa acolhedora, calmo e contemplativo, imagética cósmica com parcimônia, rigor sem arrogância, honestidade sobre temas duros, citação traduzida anunciada como "em tradução livre", CTA suave só no Espelho (pergunta) e no Fecho (convite). Anti-padrões — hype ("vai mudar sua vida"), superlativo vazio, otimismo raso, frase de efeito sem fonte, pedir inscrição no meio. Procedimento — ler em voz alta mentalmente; trocar a metáfora cósmica por uma concreta se já houver uma na seção.
  - `writing.md`: "Segunda pessoa (você)" no lugar de "Primeira pessoa"; frase falável; o restante fica.
  - `retention.md`: acrescenta promessa no Gancho, troca de registro a cada seção (cena, ideia, objeção, pergunta), prática para hoje na Aplicacao, CTA suave.
  - `story.md`: critério "seções vizinhas não abrem com o mesmo registro".
  - `plan.md`: recebe `{eixos}` e pede `eixo` (um dos quatro ou nulo). `review.md`: recebe `{eixo_referencia}`; manda preencher `secao` de cada nota com um dos nove nomes; manda conferir a fidelidade de toda citação com `traducao` contra o `trecho`.
  - `plan.SKILLS = ["story", "canal"]`, `review.SKILLS = ["story", "retention", "fact_check", "canal"]`.
  - `graph.node_plan` devolve `{"tese", "esboco", "eixo"}`; `node_review` passa `eixo`.
  - `artefatos._render("plan")` e leitura do frontmatter (`^eixo:\s*(.+)$`).
- [ ] **Step 4: Rodar e ver passar** — arquivos acima + `tests/orchestration/test_graph.py`
- [ ] **Step 5: Checkpoint** — `uv run pytest -q`

### Task 3: Escrita por seção e revisão dirigida

**Files:**
- Create: `src/forge/prompts/write_secao.md`
- Delete: `src/forge/prompts/write.md`
- Modify: `src/forge/agents/write.py`, `src/forge/domain/models.py`, `src/forge/orchestration/graph.py`
- Test: `tests/agents/test_write.py`, `tests/orchestration/test_graph.py`, `tests/agents/test_prompts.py`

**Interfaces:**
- Consumes: `ARQUITETURA` (Task 1); `carregar_eixo`, `Nota.secao` (Task 2).
- Produces:
  - `SecaoDraft(conteudo: str, blocos: list[BlocoRoteiro] = [], falta_pesquisa: str | None = None)`; `RoteiroDraft` removido.
  - `escrever(model, tema, tese, esboco, research, fontes, notas=None, *, research_passages=None, run_dir=None, anterior: Roteiro | None = None, eixo: str | None = None) -> tuple[Roteiro, str | None]`.
  - `write.LE` ganha `"roteiro"`; `write.SKILLS = ["writing", "story", "retention", "fact_check", "canal"]`.
  - Helper de teste `secoes_draft(**sobrescritas) -> list[SecaoDraft]` em `tests/conftest.py` (nove rascunhos válidos, na ordem).

- [ ] **Step 1: Testes que falham**

```python
def test_escrever_faz_uma_chamada_por_secao(scripted):
    model = scripted(structured=secoes_draft())
    roteiro, falta = escrever(model, "tema", "tese", "esboço", "notas", [])
    assert [s.nome for s in roteiro.secoes] == SECOES_NOMES
    assert model.structured == [] and falta is None

def test_revisao_reescreve_so_a_secao_citada(scripted):
    anterior = roteiro_longo()
    novo = SecaoDraft(conteudo="Prova refeita.", blocos=[BlocoRoteiro(texto="Prova refeita.", referencias=["4363/ch2/p7"])])
    model = scripted(structured=[novo])
    notas = [Nota(dimensao="retention", problema="p", sugestao="s", secao="Prova")]
    roteiro, _ = escrever(model, "t", "te", "e", "n", [], notas, anterior=anterior)
    por_nome = {s.nome: s for s in roteiro.secoes}
    assert por_nome["Prova"].conteudo == "Prova refeita."
    assert por_nome["Gancho"] == {s.nome: s for s in anterior.secoes}["Gancho"]

def test_nota_com_secao_acentuada_e_canonizada(scripted): ...   # secao="Tensão" → só Tensao reescrita (1 chamada)
def test_nota_sem_secao_ou_com_nome_desconhecido_reescreve_tudo(scripted): ...  # secao=None e secao="Introdução" → 9 chamadas
def test_notas_sem_roteiro_anterior_escrevem_tudo(scripted): ...
def test_falta_pesquisa_devolve_roteiro_completo_e_o_primeiro_pedido(scripted):
    drafts = secoes_draft(Tensao=SecaoDraft(conteudo=..., blocos=..., falta_pesquisa="Confirmar X."))
    roteiro, falta = escrever(scripted(structured=drafts), ...)
    assert len(roteiro.secoes) == 9 and falta == "Confirmar X."
def test_prompt_da_secao_traz_alvo_e_secoes_anteriores(scripted): ...  # captura mensagens: "260" e "380" no prompt do Filosofo; texto do Gancho presente no prompt do Estake
```

Os testes existentes de `test_write.py` sobre referência inventada, citação literal, divergência conteúdo/blocos e `conteudo` vazio são mantidos, adaptados para `secoes_draft(Gancho=...)`/`Estake`. `test_escrever_canoniza_nome_de_secao_com_acento` sai: o nome não vem mais do modelo (`canonizar_nome` segue coberto por seu próprio teste). `test_graph.py`: cada `_draft()` vira `*secoes_draft()`; a nota do primeiro teste ganha `secao="Prova"` e a segunda passagem consome um único `SecaoDraft`.

- [ ] **Step 2: Rodar e ver falhar**
- [ ] **Step 3: Implementar**
  - `write_secao.md` com os campos `{secao} {papel} {instrucao} {alvo_min} {alvo_max} {tese} {esboco} {anteriores} {texto_anterior} {notas} {research} {fontes} {passagens} {eixo_referencia} {skills}`. Regras mantidas de `write.md`: `blocos[].texto` reproduz `conteudo` palavra por palavra; referências só das passagens listadas; Gancho dispensado de referência; Espelho termina em pergunta; Fecho devolve o Gancho. Acrescenta: escrever só esta seção; não repetir abertura das anteriores; ficar entre `alvo_min` e `alvo_max` palavras; se o material não sustenta, preencher `falta_pesquisa`.
  - `escrever`: decide o conjunto a escrever — todas, salvo quando há `notas`, `anterior` tem as nove seções e toda nota aponta (após `canonizar_nome`) para um nome de `SECOES_NOMES`. Notas gerais entram no prompt de todas as seções. Extrair `_validar_secao(nome, draft, evidencias) -> Secao` com as validações atuais.
  - `graph.node_write` passa `anterior=state.get("roteiro")` e `eixo=state.get("eixo")`.
  - `test_prompts.py`: troca `"write"` por `"write_secao"` na lista.
- [ ] **Step 4: Rodar e ver passar** — `uv run pytest tests/agents tests/orchestration -q`
- [ ] **Step 5: Checkpoint** — `uv run pytest -q`

### Task 4: Citações traduzidas e `citacoes.json`

**Files:**
- Create: `src/forge/services/citacoes.py`
- Modify: `src/forge/domain/models.py`, `src/forge/agents/write.py`, `src/forge/agents/research.py`, `src/forge/orchestration/graph.py`, `src/forge/executors/roteiro.py`
- Test: novo `tests/services/test_citacoes.py`, `tests/agents/test_write.py`, `tests/executors/test_roteiro.py`

**Interfaces:**
- Produces:
  - `CitacaoLiteral.traducao: str | None = None`; `PassageEvidence.url: str = ""` (preenchido de `Passagem.url`).
  - `Citacao(secao: str, bloco: int, tipo: Literal["literal","traducao","parafrase"], texto: str, original: str | None, autor: str, obra: str, path: str, book_id: int | None, url: str | None)`.
  - `derivar_citacoes(roteiro: Roteiro, passagens: Iterable[PassageEvidence]) -> list[Citacao]`.
  - `gravar_citacoes(run_dir: Path, citacoes: list[Citacao]) -> Path` (`video/citacoes.json`), `carregar_citacoes(run_dir: Path) -> list[Citacao]` (lista vazia se o arquivo não existir).
  - `ScriptExecutor` registra o artefato `kind="citacoes"`, `relative_path="video/citacoes.json"`.

- [ ] **Step 1: Testes que falham**

```python
def test_traducao_exige_original_na_passagem_e_traducao_na_fala(scripted):
    p = PassageEvidence(path="1998/150.f1", title="Zarathustra", authors=["Nietzsche"], text="All delight longs for repetitions.")
    bloco = BlocoRoteiro(texto='Nietzsche escreve, em tradução livre: "todo deleite anseia por repetição".',
                         referencias=[p.path],
                         citacoes_literais=[CitacaoLiteral(path=p.path, trecho="All delight longs for repetitions.",
                                                           traducao="todo deleite anseia por repetição")])
    ...  # passa; trocar trecho por texto ausente da passagem → ValueError "não confere"; traducao ausente da fala → ValueError

def test_traducao_tolera_diferenca_de_espacos(scripted): ...   # traducao com espaço duplo/quebra de linha ainda confere

def test_derivar_classifica_literal_traducao_e_parafrase():
    citacoes = derivar_citacoes(roteiro, [p1, p2])
    assert [c.tipo for c in citacoes] == ["traducao", "parafrase"]
    assert citacoes[0].texto == "todo deleite anseia por repetição" and citacoes[0].original.startswith("All delight")
    assert citacoes[1].texto == bloco_parafrase.texto and citacoes[1].url == "https://www.gutenberg.org/ebooks/4363"

def test_referencia_sem_passagem_conhecida_e_omitida(): ...   # roteiro legado: path fora das passagens → não entra, sem erro
def test_gravar_e_carregar_ida_e_volta(tmp_path): ...
def test_carregar_sem_arquivo_devolve_vazio(tmp_path): ...
```

- [ ] **Step 2: Rodar e ver falhar**
- [ ] **Step 3: Implementar** — comparação de `traducao` e `trecho` com espaços normalizados (`" ".join(s.split())`). Em `derivar_citacoes`, uma entrada por citação literal/traduzida e uma `parafrase` por referência do bloco que não tenha citação literal no mesmo bloco; autor = `", ".join(authors)`. `graph.node_research` copia `url` para `Fonte`.
- [ ] **Step 4: Rodar e ver passar**
- [ ] **Step 5: Checkpoint** — `uv run pytest -q`

### Task 5: Seletor de tema e `forge temas`

**Files:**
- Create: `src/forge/prompts/tema_candidatos.md`, `src/forge/prompts/tema_juiz.md`
- Delete: `src/forge/prompts/tema.md`
- Modify: `src/forge/services/acervo.py`, `src/forge/agents/tema.py`, `src/forge/orchestration/graph.py`, `src/forge/cli.py`, `tests/conftest.py` (`FakeAcervo.livros`)
- Test: `tests/agents/test_tema.py`, `tests/services/test_acervo.py`, `tests/test_cli.py`, `tests/orchestration/test_graph.py`, `tests/agents/test_prompts.py`

**Interfaces:**
- Consumes: `EIXOS`, `resumo_eixos` (Task 2).
- Produces:
  - `acervo.Livro(id: int, title: str, authors: list[str] = [], languages: list[str] = [], subjects: list[str] = [])`; `Acervo.livros() -> list[Livro]` (`GET /books`, chave `books`).
  - Em `agents/tema.py`: `TemaCandidato(tema, eixo, dor, promessa, buscas: list[str])`, `TemasPropostos(candidatos)`, `VeredictoTema(indice: int, sustentado: bool, apelo: int, motivo: str)`, `VeredictoTemas(veredictos)`, `TemaSugerido(tema, eixo, dor, promessa, livros: list[str], apelo: int, motivo: str)`, `Sugestoes(temas: list[TemaSugerido], eixos_sem_cobertura: list[str])`, `SemTemaSustentado(RuntimeError)`.
  - `temas_feitos(settings) -> list[str]`; `sugerir_temas(model, acervo, settings, *, n: int = 5) -> Sugestoes`; `gerar_tema(model, tema: str | None = None, *, acervo=None, settings=None) -> str`.
  - CLI: `forge temas [--n 5] [--provider ...]`.

- [ ] **Step 1: Testes que falham**

```python
def test_sugere_so_temas_sustentados_ordenados_por_apelo(scripted, acervo_fake, tmp_path):
    propostos = TemasPropostos(candidatos=[cand("A", "niilismo-absurdo", ["q1"]), cand("B", "estoicismo", ["q2"]), cand("C", "autoconhecimento", ["q3"])])
    veredictos = VeredictoTemas(veredictos=[VeredictoTema(indice=0, sustentado=True, apelo=3, motivo="m"),
                                            VeredictoTema(indice=1, sustentado=False, apelo=5, motivo="m"),
                                            VeredictoTema(indice=2, sustentado=True, apelo=5, motivo="m")])
    acervo = acervo_fake(por_query={"q1": [p("1998"), p("52914"), p("4363")], "q2": [], "q3": [p("57628"), p("57634"), p("60333")]})
    s = sugerir_temas(scripted(structured=[propostos, veredictos]), acervo, settings(tmp_path), n=5)
    assert [t.tema for t in s.temas] == ["C", "A"]
    assert "estoicismo" in s.eixos_sem_cobertura and "etica-digital-ia" in s.eixos_sem_cobertura
    assert s.temas[0].livros  # títulos dos livros que sustentam

def test_candidato_com_menos_passagens_que_o_minimo_sai(...): ...        # research_min_sources=3, 2 passagens → fora
def test_indice_invalido_e_veredicto_ausente_nao_sustentam(...): ...     # indice=7 ignorado; candidato sem veredicto fora
def test_busca_que_falha_e_pulada(...): ...                               # acervo.buscar levanta AcervoIndisponivel em uma query → demais seguem
def test_temas_feitos_le_roteiros_e_runs(tmp_path): ...                   # output/roteiros/x.md (frontmatter tema:) + output/runs/y/video/input.json
def test_temas_feitos_entram_no_prompt(...): ...
def test_gerar_tema_sem_sustentacao_levanta(...):
    with pytest.raises(SemTemaSustentado): gerar_tema(model, None, acervo=acervo, settings=settings)
def test_gerar_tema_respeita_tema_informado(scripted): assert gerar_tema(scripted(), "X") == "X"
def test_acervo_livros(...): ...                                          # MockTransport devolve {"total":1,"books":[{...}]}
def test_cli_temas_imprime_lista_e_eixos_sem_cobertura(monkeypatch, capsys): ...
def test_cli_temas_sem_sustentacao_sai_1(monkeypatch, capsys): ...
```

- [ ] **Step 2: Rodar e ver falhar**
- [ ] **Step 3: Implementar**
  - `sugerir_temas`: pede `max(2 * n, 6)` candidatos; prompt com `resumo_eixos()`, catálogo (`título — autores [idiomas]`), temas feitos e a instrução de escrever as buscas no idioma dos livros e de formular o tema pela dor do espectador, não pelo nome da disciplina. Busca com `top=settings.acervo_top`, dedupe por `path`. O juiz recebe, por candidato, até 6 trechos de 300 caracteres. Fica quem tem veredicto `sustentado` e ao menos `settings.research_min_sources` passagens. Ordena por `apelo` decrescente, depois por número de livros distintos. `eixos_sem_cobertura` = eixos de `EIXOS` sem tema sobrevivente.
  - `graph.node_tema` passa `acervo` e `settings`.
  - CLI imprime `N. <tema> [<eixo>] apelo <a>/5 — <livros separados por "; ">` em stdout e `Eixos sem cobertura no acervo: ...` em stderr; `SemTemaSustentado` e `AcervoIndisponivel` saem com código 1 e a mensagem em stderr.
  - `test_graph.py`: testes que partiam de `tema: None` passam a informar um tema; um teste novo cobre o caminho do seletor dentro do grafo.
- [ ] **Step 4: Rodar e ver passar**
- [ ] **Step 5: Checkpoint** — `uv run pytest -q`

### Task 6: Embalagem — modelos, montagem e gates

**Files:**
- Create: `src/forge/domain/embalagem.py`, `src/forge/services/qualidade_embalagem.py`, `src/forge/agents/embalagem.py`, `src/forge/prompts/embalagem.md`
- Test: novos `tests/services/test_qualidade_embalagem.py`, `tests/agents/test_embalagem.py`

**Interfaces:**
- Consumes: `Citacao` (Task 4); `ARQUITETURA`; `texto_narravel`, `dividir_frases`, `PALAVRAS_POR_SEGUNDO`; `GateFinding`, `ScriptGateReport` de `qualidade_roteiro`.
- Produces:
  - `domain/embalagem.py`: `TituloProposto(texto, angulo)`, `ThumbnailProposta(texto, prompt)`, `RotuloCapitulo(secao, titulo)`, `EmbalagemProposta(titulos, thumbnail, abertura, resumo, capitulos, tags, hashtags)`, `Capitulo(secao, titulo, inicio_segundos: int)`, `Embalagem(titulos, thumbnail, descricao, capitulos, capitulos_estimados: bool = True, tags, hashtags, comentario_fixado, fontes: list[str])`.
  - `qualidade_embalagem.conferir_embalagem(e: Embalagem) -> ScriptGateReport`.
  - `agents/embalagem.py`: `AVISO_IA`, `EmbalagemReprovada(RuntimeError)` com `.report`, `estimar_capitulos(roteiro, rotulos) -> list[Capitulo]`, `fontes_da_descricao(citacoes) -> list[str]`, `comentario_fixado(roteiro) -> str`, `montar_descricao(proposta, capitulos, fontes, *, aviso_ia: bool) -> str`, `embalar(model, roteiro, citacoes, *, aviso_ia: bool = True, run_dir=None) -> Embalagem`, `gravar_embalagem(run_dir, embalagem) -> tuple[Path, Path]` (`video/embalagem.json`, `embalagem.md`).

- [ ] **Step 1: Testes que falham**

```python
# gates — um teste por código, partindo de `embalagem_valida()`
@pytest.mark.parametrize("mudanca, codigo", [
    (dict(titulos=dois_titulos), "titulos_quantidade"),
    (dict(titulos=tres_iguais), "titulos_repetidos"),
    (dict(titulos=com_titulo_de_71_caracteres), "titulo_longo"),
    (dict(titulos=com("O SEGREDO QUE NINGUÉM CONTA")), "titulo_gritado"),
    (dict(thumbnail=ThumbnailProposta(texto="cinco palavras são demais aqui", prompt="p")), "thumbnail_texto"),
    (dict(thumbnail=ThumbnailProposta(texto=titulo_1, prompt="p")), "thumbnail_repete_titulo"),
    (dict(thumbnail=ThumbnailProposta(texto="O vazio", prompt=" ")), "thumbnail_sem_prompt"),
    (dict(capitulos=dois_capitulos), "capitulos_insuficientes"),
    (dict(capitulos=comecando_em_5), "capitulo_inicial"),
    (dict(capitulos=com_intervalo_de_8s), "capitulo_curto"),
    (dict(descricao="x" * 5001), "descricao_longa"),
    (dict(descricao="y" * 151 + "\nresto"), "descricao_abertura_longa"),
    (dict(fontes=[]), "descricao_sem_fontes"),
    (dict(tags=["t" * 60] * 9), "tags_longas"),
    (dict(hashtags=["#a", "#b", "#c", "#d"]), "hashtags_excesso"),
])
def test_gate_reprova(mudanca, codigo):
    assert codigo in conferir_embalagem(embalagem_valida().model_copy(update=mudanca)).codes

def test_titulo_entre_61_e_70_e_so_aviso(): ...          # aprovado, achado "titulo_longo_aviso"
def test_embalagem_valida_passa(): assert conferir_embalagem(embalagem_valida()).approved

# montagem
def test_capitulos_estimados_pela_contagem_de_palavras():
    caps = estimar_capitulos(roteiro_longo(), rotulos)
    assert caps[0].inicio_segundos == 0 and len(caps) == 9
    assert caps[1].inicio_segundos == round(palavras_do_gancho / 2.5)
def test_rotulo_ausente_usa_papel_e_rotulo_de_secao_desconhecida_e_ignorado(): ...
def test_rotulo_com_quebra_de_linha_e_achatado(): ...
def test_fontes_deduplicadas_por_autor_e_obra(): ...     # "Nietzsche, Friedrich Wilhelm — Thus Spake Zarathustra (https://www.gutenberg.org/ebooks/1998)"
def test_comentario_fixado_e_a_pergunta_final_do_espelho(): ...
def test_descricao_tem_abertura_capitulos_fontes_e_aviso():
    d = montar_descricao(proposta, caps, fontes, aviso_ia=True)
    assert d.splitlines()[0] == proposta.abertura and "00:00 " in d and "Fontes" in d and AVISO_IA in d
def test_aviso_ia_desligado_sai_da_descricao(): ...
def test_embalar_reprovado_tenta_de_novo_com_os_achados(scripted): ...   # 1ª proposta com título de 80 chars, 2ª válida → 2 chamadas; achado no 2º prompt
def test_embalar_reprovado_duas_vezes_levanta(scripted): ...             # EmbalagemReprovada, .report.codes contém "titulo_longo"
def test_gravar_embalagem_escreve_json_e_markdown(tmp_path): ...
```

- [ ] **Step 2: Rodar e ver falhar**
- [ ] **Step 3: Implementar**
  - Limites: título > 70 grave, 61–70 aviso; `titulo_gritado` = mais de uma palavra de 4+ letras toda em maiúsculas; texto da thumbnail 1–4 palavras; capítulos ≥ 3, primeiro em 0, intervalo ≥ 10 s; descrição ≤ 5.000 e primeira linha ≤ 150; tags: `sum(len(t)) + len(tags) - 1 ≤ 500`; hashtags ≤ 3. `descricao_sem_fontes` olha `Embalagem.fontes`.
  - `AVISO_IA = "Narração e imagens deste vídeo foram geradas com inteligência artificial, a partir de um roteiro baseado nas obras citadas acima."`
  - Descrição, nesta ordem, separada por linha em branco: abertura; resumo; `Capítulos` + linhas `MM:SS título` (`H:MM:SS` a partir de 1 h); `Fontes` + uma linha `- <fonte>` cada; aviso de IA; hashtags.
  - `embalagem.md`: seções `## Títulos`, `## Thumbnail`, `## Descrição` (em bloco de código, pronta para colar), `## Tags`, `## Comentário fixado`.
  - `embalagem.md` (prompt): recebe tese, roteiro renderizado com nomes de seção e a lista de autores/obras citados. Regras: título promete só o que o roteiro entrega, ≤ 60 caracteres, sem caixa alta; três ângulos distintos (pergunta, contraintuitivo, benefício); texto da thumbnail complementa o título em até 4 palavras; prompt da thumbnail em inglês, 16:9, um sujeito focal, alto contraste, espaço livre para texto, sem texto nem rosto de pessoa real; abertura com até 150 caracteres; rótulo de capítulo até 40 caracteres, sem nomes internos de seção; 10–15 tags; até 3 hashtags; nada que o roteiro não afirme.
- [ ] **Step 4: Rodar e ver passar**
- [ ] **Step 5: Checkpoint** — `uv run pytest -q`

### Task 7: Embalagem e citações ligadas no CLI e no Studio

**Files:**
- Modify: `src/forge/infrastructure/config.py`, `src/forge/cli.py`, `src/forge/executors/plano_midia.py`, `web/components/run-outputs.tsx` (só se a classificação por `kind` esconder o artefato), `.env.example`
- Test: `tests/test_cli.py`, `tests/executors/test_plano_midia.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: `embalar`, `gravar_embalagem`, `EmbalagemReprovada` (Task 6); `derivar_citacoes`, `gravar_citacoes`, `carregar_citacoes` (Task 4).
- Produces: `Settings.aviso_ia: bool = True` (`FORGE_AVISO_IA`); artefatos `kind="embalagem"` (`video/embalagem.json`) e `kind="embalagem_markdown"` (`embalagem.md`); falha de etapa `code="packaging_gate_failed"`, `FailureClass.DETERMINISTIC`, `retriable=True`.

- [ ] **Step 1: Testes que falham**

```python
# tests/executors/test_plano_midia.py
def test_etapa_grava_embalagem_antes_do_plano_de_midia(...):
    # modelo roteirizado: [EmbalagemProposta válida, BeatsDaSecao × 9]; run com video/roteiro.json e video/citacoes.json
    result = executor.run(context, emit)
    assert (run_dir / "video/embalagem.json").is_file() and (run_dir / "embalagem.md").is_file()
    assert {"embalagem", "embalagem_markdown", "media_plan"} <= {a.kind for a in result.artifacts}

def test_embalagem_reprovada_falha_a_etapa_sem_gastar_beats(...):
    # duas propostas inválidas → failure.code == "packaging_gate_failed"; fila do modelo ainda com os BeatsDaSecao; midia.json ausente

def test_sem_citacoes_json_deriva_do_roteiro_e_das_evidencias(...): ...   # só research-evidence.json presente

def test_aviso_ia_entra_no_hash_de_entrada(...): ...                      # prepare() com aviso_ia True/False → hashes diferentes

# tests/test_cli.py
def test_roteiro_aprovado_grava_citacoes_e_embalagem(...): ...            # run_dir/video/citacoes.json e run_dir/embalagem.md
def test_embalagem_reprovada_nao_derruba_o_roteiro(...): ...              # retorno 0, roteiro gravado, erro logado
def test_roteiro_reprovado_nao_gera_embalagem(...): ...
```

- [ ] **Step 2: Rodar e ver falhar**
- [ ] **Step 3: Implementar**
  - CLI: `_embalagem(model, settings, run_dir, final, aprovado)` chamado depois de `_plano_de_midia`, só com `aprovado is True`; grava `citacoes.json` (de `final["roteiro"]` + `final["research_passages"]`) e a embalagem; `EmbalagemReprovada` e erro transitório são logados, o comando sai 0.
  - `MediaPlanExecutor.execute`: dentro do slot `llm`, embalagem primeiro, plano de mídia depois. Citações: `carregar_citacoes`; vazio → `derivar_citacoes` com `video/research-evidence.json` quando existir.
  - Dashboard: se `run-outputs.tsx` agrupa por lista fechada de tipos, incluir `embalagem_markdown` no grupo do roteiro; conferir `web/components/run-outputs.test.tsx`.
- [ ] **Step 4: Rodar e ver passar** — `uv run pytest tests/test_cli.py tests/executors/test_plano_midia.py tests/test_config.py -q`; se o dashboard mudou, `npm test --prefix web -- run-outputs`
- [ ] **Step 5: Checkpoint** — `uv run pytest -q`

### Task 8: Documentação e verificação real

**Files:**
- Modify: `CLAUDE.md`, `README.md`, `.env.example`

- [ ] **Step 1:** `CLAUDE.md` — comandos (`uv run forge temas`), seção nova "Canal: Conquistas Cósmicas" (identidade por skills, eixos e referências, escrita por seção, revisão dirigida, citações traduzidas, `citacoes.json`, seletor de tema, embalagem e seus gates), e ajuste do parágrafo do grafo (`write` por seção; `plan` define `eixo`). `README.md` — `forge temas` e os artefatos novos. `.env.example` — `FORGE_AVISO_IA`.
- [ ] **Step 2:** `uv run pytest -q` — só a falha de baseline.
- [ ] **Step 3:** `uv run forge temas --n 3` com o acervo local e o provider atual; conferir que os temas vêm com livros e que os eixos sem cobertura aparecem.
- [ ] **Step 4:** `uv run forge roteiro --tema "<primeiro tema sugerido>"`; conferir na run: total de palavras entre 1.500 e 2.800, `video/citacoes.json` com caminhos reais, `embalagem.md` com três títulos, capítulos começando em 00:00 e seção de fontes.
- [ ] **Step 5:** Registrar o resultado (contagens, caminho da run, o que falhou) na resposta ao usuário.
