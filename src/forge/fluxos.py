"""Três fluxos de geração de roteiro para teste A/B com google/gemma-4-e4b.

Cada fluxo é um StateGraph compilado com o mesmo RoteiroState, mas topologia
e prompts diferentes. O roteador (`run_tres_fluxos`) executa os três em sequência
num mesmo run_dir e devolve um resumo comparativo.

Fluxo 1 — Iteração focada em fechar notas (setup padrão, prompts reescritos):
    tema → research → plan → write → review → (write de correção → review → …)
    O write recebe as notas e deve fechar itens um a um, não regenerar o texto.

Fluxo 2 — Escrita em lotes com verificação por bloco:
    tema → research → plan → write_lote1(1-3) → verifica_lote1 → write_lote2(4-6)
    → verifica_lote2 → write_lote3(7-9) → review_final
    Cada lote é verificado contra research antes de avançar; erro de citação
    é corrigido no mesmo lote, não adianta para o final.

Fluxo 3 — Rascunho estrutural → preenchimento:
    tema → research → plan → estrutura(schetos por seção) → review_estrutura
    → preenche(seção a seção, ancorada em research) → review_final
    Separa "o que dizer" do "como dizer": a estrutura define o movimento de cada
    seção em 1-2 frases; o preenchimento expande com material do acervo.
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import Command

from forge.infrastructure.logging import get_logger
from forge.orchestration.state import RoteiroState
from forge.agents import plan as plan_stage
from forge.agents import research as research_stage
from forge.agents import review as review_stage
from forge.agents import tema as tema_stage
from forge.agents.write import escrever, LE as WRITE_LE
from forge.services.artefatos import gravar_artefato, gravar_bruto
from forge.llms.model import invoke_structured
from forge.prompts.loader import load_prompt
from forge.domain.models import (
    Roteiro,
    RoteiroDraft,
    ReviewResult,
    Nota,
    Secao,
    Plano,
)
from forge.skills.loader import load_skills

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# helpers compartilhados
# ---------------------------------------------------------------------------

def com_wrapper(nome: str, fn, le: list[str], *, max_passos: int | None = None):
    def wrapped(state: dict):
        entrada = {k: state[k] for k in le if k in state}
        resultado = fn(entrada)
        if isinstance(resultado, Command):
            atualizacao = dict(resultado.update or {})
            bruto = atualizacao.pop("_raw", None)
            gravar_artefato(state["run_dir"], nome, atualizacao)
            if bruto is not None:
                gravar_bruto(state["run_dir"], nome, bruto)
            destino = resultado.goto
            if (
                max_passos is not None
                and destino == "research"
                and state.get("passos", 0) >= max_passos
            ):
                logger.warning(
                    "Handoff ignorado: orçamento estourado",
                    de=nome,
                    para=destino,
                    passos=state.get("passos", 0),
                    max=max_passos,
                )
                destino = "review"
                atualizacao["pedido"] = None
            return Command(
                graph=resultado.graph,
                resume=resultado.resume,
                goto=destino,
                update={**atualizacao, "passos": state.get("passos", 0) + 1},
            )
        bruto = resultado.pop("_raw", None)
        gravar_artefato(state["run_dir"], nome, resultado)
        if bruto is not None:
            gravar_bruto(state["run_dir"], nome, bruto)
        return {**resultado, "passos": state.get("passos", 0) + 1}

    return wrapped


def orcamento_estourado(state: dict, max_passos: int) -> bool:
    return state.get("passos", 0) >= max_passos


def rotear(state: dict, max_rounds: int, max_passos: int) -> str:
    if orcamento_estourado(state, max_passos):
        logger.warning("Budget exhausted - stopping", passos=state.get("passos", 0), max=max_passos)
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


# ===========================================================================
# FLUXO 1 — Iteração focada em fechar notas
# ===========================================================================

FLUXO1_SKILLS = ["writing", "story", "retention", "fact_check"]


def _write_fluxo1(model, state: dict):
    """Write com prompt reescrito: fecha notas, não regenera."""
    notas = None
    review = state.get("review")
    if review is not None:
        notas = review.notas
    roteiro, falta = escrever(
        model,
        state["tema"],
        state["tese"],
        state["esboco"],
        state["research_notes"],
        state["fontes"],
        notas,
        run_dir=state.get("run_dir"),
    )
    if falta:
        return Command(goto="research", update={"roteiro": roteiro, "pedido": falta})
    return Command(goto="review", update={"roteiro": roteiro})


def build_fluxo1(model, settings, inicio: str = "tema"):
    logger.info("Building fluxo 1 — iteração focada em notas")
    g = StateGraph(RoteiroState)
    g.add_node("tema", com_wrapper("tema", tema_stage.gerar_tema, tema_stage.LE))
    g.add_node("research", com_wrapper("research", research_stage.pesquisar, research_stage.LE))
    g.add_node("plan", com_wrapper("plan", plan_stage.planejar, plan_stage.LE))
    g.add_node(
        "write",
        com_wrapper("write", _write_fluxo1, WRITE_LE, max_passos=settings.max_passos),
        destinations=("research", "review"),
    )
    g.add_node("review", com_wrapper("review", review_stage.revisar, review_stage.LE))
    g.set_entry_point(inicio)
    g.add_edge("tema", "research")
    g.add_edge("research", "plan")
    g.add_edge("plan", "write")
    g.add_conditional_edges(
        "review",
        lambda s: rotear(s, settings.max_review_rounds, settings.max_passos),
        {"write": "write", "research": "research", END: END},
    )
    logger.info("Fluxo 1 compiled")
    return g.compile()


# ===========================================================================
# FLUXO 2 — Escrita em lotes com verificação por bloco
# ===========================================================================

# Blocos de 3 seções seguindo a ordem fechada.
_LOTES = [
    ("lote1", ["Gancho", "Estake", "Tensao"]),
    ("lote2", ["Virada", "Filosofo", "Prova"]),
    ("lote3", ["Espelho", "Aplicacao", "Fecho"]),
]

# Prompt de verificação de lote: checa citações e completude do lote, não o
# roteiro inteiro. É mais leve que o review final e serve como guarda-local.
_PROMPT_VERIFICA_LOTE = """
Verifique este lote de 3 seções do roteiro. O lote é parte de um roteiro maior
de 9 seções (Gancho, Estake, Tensao, Virada, Filosofo, Prova, Espelho, Aplicacao, Fecho).

Lote atual: {lote_nome} — seções {secoes}.

Material de pesquisa disponível:
{research}

Fontes citáveis:
{fontes}

{skills}

Para cada seção do lote, responda em uma linha:
- SEÇÃO: <nome>
- CITAÇÃO: OK / FALTA / NÃO APLICA (Gancho e Fecho não exigem)
- COMPLETO: OK / INCOMPLETO / TRUNCADO

Se qualquer seção estiver INCOMPLETA ou TRUNCADA, escreva ela completa aqui.
Se qualquer seção factual FALTA citação, adicione a citação [path] correta.

Produce um texto com as seções corrigidas, no mesmo formato markdown (## Nome).
"""

_LOTE_INDICE = {
    "Gancho": 0,
    "Estake": 1,
    "Tensao": 2,
    "Virada": 3,
    "Filosofo": 4,
    "Prova": 5,
    "Espelho": 6,
    "Aplicacao": 7,
    "Fecho": 8,
}

# Prompt de write de lote: recebe o lote, o esboco, o research. Gera as 3
# seções do lote com citações desde o primeiro rascunho — não espera o review
# para ancorar, porque a verificação já vem depois.
_PROMPT_WRITE_LOTE = """
Escreva 3 seções do roteiro em PT-BR, no formato markdown:

## <nome da seção>
<conteúdo>

As 3 seções são: {secoes}.

Tese do roteiro: {tese}
Esboço do roteiro: {esboco}

Material de pesquisa:
{research}

Fontes citáveis (use [path] para ancorar afirmações factuais):
{fontes}

{skills}

Regras para ESTAS 3 seções:
- Gancho abre a tensão sem preâmbulo. É a única seção dispensada de citação.
- Cada seção factual ancora uma afirmação em autor ou título da lista de fontes.
- Use [path] na forma [6.8.f5] para citações.
- Se o material não cobre algo, diga explicitamente — não preencha com memória.
- Cada seção deve ser completa (não truncada) e avançar a tese.
- Escreva os 3 blocos em ordem, cada um com ## <nome>.
"""

_LOTE_NOMES = {
    "lote1": "Gancho, Estake, Tensao",
    "lote2": "Virada, Filosofo, Prova",
    "lote3": "Espelho, Aplicacao, Fecho",
}


def _lote_name(idx: int) -> str:
    return _LOTES[idx][0]


def _lote_secoes(idx: int) -> list[str]:
    return _LOTES[idx][1]


def _write_lote(model, state: dict, idx: int):
    secoes_nomes = _lote_secoes(idx)
    prompt = _PROMPT_WRITE_LOTE.format(
        secoes=", ".join(secoes_nomes),
        tese=state["tese"],
        esboco=state["esboco"],
        research=state["research_notes"],
        fontes="\n".join(f"- {f.autor or 'autor desconhecido'} — {f.titulo}" for f in state["fontes"]),
        skills=load_skills(FLUXO1_SKILLS, "write"),
    )
    resp = invoke_structured(
        model,
        RoteiroDraft,
        [__import__("langchain_core").messages.HumanMessage(content=prompt)],
        run_dir=state.get("run_dir"),
        etapa="write",
        subfase=f"lote{_lote_name(idx)}",
    )
    # A seção retornada pode ter qualquer nome — filtramos só as do lote e as
    # colocamos na ordem correta.
    desejadas = {n: None for n in secoes_nomes}
    for s in resp.secoes:
        nome_canon = __import__("forge.domain.roteiro", fromlist=["canonizar_nome"]).canonizar_nome(s.nome)
        if nome_canon in desejadas:
            desejadas[nome_canon] = s.conteudo
    secoes = [
        Secao(nome=n, conteudo=conteudo or f"<seção {n} não gerada>")
        for n, conteudo in desejadas.items()
    ]
    return {"secoes_lote": secoes, "lote_idx": idx}


def _accumular_lote(state: dict, idx: int):
    """Acumula as seções do lote idx no roteiro em construção."""
    lote = state.get("secoes_lote", [])
    acumulado = list(state.get("roteiro_parcial", []))
    for s in lote:
        # Substitui seção existente (do lote anterior) ou adiciona.
        for i, antigo in enumerate(acumulado):
            if __import__("forge.domain.roteiro", fromlist=["canonizar_nome"]).canonizar_nome(antigo.nome) == __import__("forge.domain.roteiro", fromlist=["canonizar_nome"]).canonizar_nome(s.nome):
                acumulado[i] = s
                break
        else:
            acumulado.append(s)
    return {"roteiro_parcial": acumulado, "lote_idx": idx + 1}


def _verifica_lote(model, state: dict, idx: int):
    """Verifica o último lote gerado e corrige in-place."""
    secoes_lote = state.get("secoes_lote", [])
    if not secoes_lote:
        return {}
    lote_nome = _lote_name(idx)
    secoes_nomes = _lote_secoes(idx)
    lote_texto = "\n".join(f"## {s.nome}\n{s.conteudo}\n" for s in secoes_lote)
    prompt = _PROMPT_VERIFICA_LOTE.format(
        lote_nome=lote_nome,
        secoes=", ".join(secoes_nomes),
        research=state["research_notes"],
        fontes="\n".join(f"- {f.autor or 'autor desconhecido'} — {f.titulo}" for f in state["fontes"]),
        skills=load_skills(FLUXO1_SKILLS, "write"),
    )
    resp = invoke_structured(
        model,
        RoteiroDraft,
        [__import__("langchain_core").messages.HumanMessage(content=prompt)],
        run_dir=state.get("run_dir"),
        etapa="verifica",
        subfase=f"lote{_lote_name(idx)}",
    )
    # Rebuild secoes_lote com o resultado corrigido, mantendo ordem.
    por_nome = {__import__("forge.domain.roteiro", fromlist=["canonizar_nome"]).canonizar_nome(s.nome): s.conteudo for s in resp.secoes}
    corrigidas = [
        Secao(
            nome=n,
            conteudo=por_nome.get(__import__("forge.domain.roteiro", fromlist=["canonizar_nome"]).canonizar_nome(n), conteudo)
        )
        for n, conteudo in ((s.nome, s.conteudo) for s in secoes_lote)
    ]
    return {"secoes_lote": corrigidas}


def _montar_roteiro_final(state: dict):
    """Junta os lotes acumulados em um Roteiro."""
    parcial = state.get("roteiro_parcial", [])
    if not parcial:
        return {}
    roteiro = Roteiro(
        tema=state["tema"],
        tese=state["tese"],
        secoes=parcial,
        fontes=state["fontes"],
    )
    return {"roteiro": roteiro}


def _proximo_apos_review(state: dict):
    """Decide o próximo lote ou review final após um review."""
    rounds = state.get("rounds", 0) + 1
    review = state.get("review")
    if review is None:
        return {"lote_idx": 0}
    if review.verificar:
        return {"lote_idx": 0, "review": review, "rounds": rounds, "pedido": "\n".join(review.verificar) or None}
    if review.aprovado or rounds >= state.get("max_review_rounds", 4):
        return {"review": review, "rounds": rounds}
    # Reprovaado sem verificar: vai para o lote que o review mais criticou.
    # Por enquanto, reinicia do lote 1.
    return {"lote_idx": 0, "review": review, "rounds": rounds}


def build_fluxo2(model, settings, inicio: str = "tema"):
    logger.info("Building fluxo 2 — escrita em lotes com verificação")
    g = StateGraph(RoteiroState)
    g.add_node("tema", com_wrapper("tema", tema_stage.gerar_tema, tema_stage.LE))
    g.add_node("research", com_wrapper("research", research_stage.pesquisar, research_stage.LE))
    g.add_node("plan", com_wrapper("plan", plan_stage.planejar, plan_stage.LE))
    g.add_node(
        "write_lote",
        com_wrapper("write_lote", lambda s: _write_lote(model, s, s.get("lote_idx", 0) or 0), WRITE_LE),
    )
    g.add_node(
        "verifica_lote",
        com_wrapper("verifica_lote", lambda s: _verifica_lote(model, s, s.get("lote_idx", 0) or 0), WRITE_LE),
    )
    g.add_node("montar_final", com_wrapper("montar_final", _montar_roteiro_final, ["tema", "tese", "roteiro_parcial", "fontes"]))
    g.add_node("review", com_wrapper("review", review_stage.revisar, review_stage.LE))
    g.add_node("next_after_review", com_wrapper("next_after_review", _proximo_apos_review, ["review", "rounds", "max_review_rounds"]))
    g.set_entry_point(inicio)
    g.add_edge("tema", "research")
    g.add_edge("research", "plan")
    g.add_edge("plan", "write_lote")
    g.add_edge("write_lote", "verifica_lote")
    g.add_edge("verifica_lote", "accumulate_lote")
    g.add_edge("accumulate_lote", "lote_done")
    # lote_done decide: mais lotes ou review final?
    g.add_conditional_edges(
        "lote_done",
        lambda s: _decide_proximo_lote(s),
        {"write_lote": "write_lote", "review": "review"},
    )
    g.add_edge("review", "next_after_review")
    g.add_conditional_edges(
        "next_after_review",
        lambda s: _decide_pos_review(s),
        {"write_lote": "write_lote", "review": "review", END: END},
    )
    logger.info("Fluxo 2 compiled")
    return g.compile()


def _decide_proximo_lote(state: dict) -> str:
    """Retorna o nome do próximo nó: mais um lote ou review final."""
    idx = state.get("lote_idx", 0) or 0
    if idx >= len(_LOTES):
        return "review"
    return "write_lote"


def _decide_pos_review(state: dict) -> str:
    """Após review: se aprovado → END, se verificar → research, senão restart lotes."""
    review = state.get("review")
    rounds = state.get("rounds", 0) or 0
    if review is None:
        return "write_lote"
    if review.verificar:
        logger.info("Handoff to research", alegacoes=len(review.verificar))
        return "research"
    if review.aprovado or rounds >= state.get("max_review_rounds", 4):
        logger.info("Review approved or rounds exhausted", aprovado=review.aprovado, round=rounds)
        return END
    logger.debug("Restarting lotes after review", round=rounds)
    return "write_lote"


# ===========================================================================
# FLUXO 3 — Rascunho estrutural → preenchimento
# ===========================================================================

# Prompt da estrutura: o plan gera a tese + o esboço + um esboço por seção
# (1-2 frases sobre o que cada seção faz). Isso é o "rascunho estrutural".
_PROMPT_PLANO_ESTRUTURAL = """
Tema: {tema}

Notas de pesquisa:
{research}

{skills}

Produce:
1. **tese** — a afirmação central do roteiro (1 frase).
2. **esboco** — como as 9 partes avançam a tese (3-4 frases).
3. **estrutura_por_secao** — para cada uma das 9 seções (Gancho, Estake, Tensao,
   Virada, Filosofo, Prova, Espelho, Aplicacao, Fecho), escreva 1-2 frases
   dizendo exatamente o que aquela seção acrescenta que a anterior não tinha.
   Não expandeda em prosa — apenas o movimento argumentativo.
"""

# Modelo para o plano estrutural.
from pydantic import BaseModel, Field


class PlanoEstrutural(BaseModel):
    tese: str
    esboco: str
    estrutura_por_secao: dict[str, str] = Field(
        default_factory=dict,
        description="Para cada seção, 1-2 frases do movimento argumentativo.",
    )


def _plan_estrutural(model, state: dict):
    prompt = _PROMPT_PLANO_ESTRUTURAL.format(
        tema=state["tema"],
        research=state["research_notes"],
        skills=load_skills(FLUXO1_SKILLS, "plan"),
    )
    plano = invoke_structured(
        model,
        PlanoEstratural,
        [__import__("langchain_core").messages.HumanMessage(content=prompt)],
        run_dir=state.get("run_dir"),
        etapa="plan",
        subfase="estrutural",
    )
    return {
        "tese": plano.tese,
        "esboco": plano.esboco,
        "estrutura_por_secao": plano.estrutura_por_secao,
    }


def _preenche_secao(model, state: dict, secao_nome: str):
    """Preenche UMA seção do roteiro, ancorada em research e na estrutura."""
    from forge.domain.roteiro import canonizar_nome

    estrutura = state.get("estrutura_por_secao", {})
    movimento = estrutura.get(secao_nome, "")
    secoes_ja_escritas = state.get("roteiro_parcial", [])
    ja_escritas = "\n".join(f"## {s.nome}\n{s.conteudo}\n" for s in secoes_ja_escritas)

    prompt = f"""
Escreva UMA seção do roteiro em PT-BR, no formato markdown:

## {secao_nome}
<conteúdo completo da seção>

Tema do roteiro: {state['tema']}
Tese: {state['teste']}
Esboço: {state['esboco']}

O que esta seção deve acrescentar (movimento argumentativo):
{movimento}

Seções já escritas (para manter coerência):
{ja_escritas}

Material de pesquisa:
{state['research_notes']}

Fontes citáveis (use [path] para ancorar afirmações factuais):
{chr(10).join(f"- {f.autor or 'autor desconhecido'} — {f.titulo}" for f in state['fontes'])}

{load_skills(FLUXO1_SKILLS, 'write')}

Regras:
- Gancho abre a tensão sem preâmbulo. É a única seção dispensada de citação.
- Cada seção factual ancora uma afirmação em autor ou título da lista de fontes.
- Use [path] na forma [6.8.f5].
- A seção deve ser completa (não truncada) e avançar a tese.
- Escreva APENAS esta seção, em um bloco ## {secao_nome}.
"""
    resp = invoke_structured(
        model,
        RoteiroDraft,
        [__import__("langchain_core").messages.HumanMessage(content=prompt)],
        run_dir=state.get("run_dir"),
        etapa="preenche",
        subfase=secao_nome,
    )
    secao_escrita = None
    for s in resp.secoes:
        if canonizar_nome(s.nome) == canonizar_nome(secao_nome):
            secao_escrita = s
            break
    if secao_escrita is None:
        secao_escrita = Secao(nome=secao_nome, conteudo=resp.secoes[0].conteudo if resp.secoes else "")
    return {"secoes_lote": [secao_escrita]}


def _preenche_proxima_secao(state: dict):
    """Decide qual seção preencher a seguir."""
    secoes_nomes = ["Gancho", "Estake", "Tensao", "Virada", "Filosofo", "Prova", "Espelho", "Aplicacao", "Fecho"]
    idx = state.get("secao_idx", 0) or 0
    if idx >= len(secoes_nomes):
        return {"acao": "montar_final"}
    return {"acao": "preenche_" + secoes_nomes[idx], "secao_nome": secoes_nomes[idx]}


def build_fluxo3(model, settings, inicio: str = "tema"):
    logger.info("Building fluxo 3 — estrutura → preenchimento")
    g = StateGraph(RoteiroState)
    g.add_node("tema", com_wrapper("tema", tema_stage.gerar_tema, tema_stage.LE))
    g.add_node("research", com_wrapper("research", research_stage.pesquisar, research_stage.LE))
    g.add_node("plan_estrutural", com_wrapper("plan_estrutural", _plan_estrutural, plan_stage.LE + ["research_notes"]))
    g.add_node("review_estrutura", com_wrapper("review_estrutura", review_stage.revisar, review_stage.LE))
    g.add_node(
        "preenche_secao",
        com_wrapper("preenche_secao", lambda s: _preenche_secao(model, s, s.get("secao_nome", "")), WRITE_LE),
    )
    g.add_node(
        "preenche_proxima",
        com_wrapper("preenche_proxima", _preenche_proxima_secao, ["secao_idx", "estrutura_por_secao"]),
    )
    g.add_node("montar_final", com_wrapper("montar_final", _montar_roteiro_final, ["tema", "tese", "roteiro_parcial", "fontes"]))
    g.add_node("review_final", com_wrapper("review_final", review_stage.revisar, review_stage.LE))
    g.set_entry_point(inicio)
    g.add_edge("tema", "research")
    g.add_edge("research", "plan_estrutural")
    g.add_edge("plan_estrutural", "review_estrutura")
    g.add_conditional_edges(
        "review_estrutura",
        lambda s: _decide_review_estrutura(s, settings),
        {"preenche_proxima": "preenche_proxima", "plan_estrutural": "plan_estrutural", END: END},
    )
    g.add_conditional_edges(
        "preenche_proxima",
        lambda s: _decide_preenche(s),
        {"preenche_secao": "preenche_secao", "montar_final": "montar_final"},
    )
    g.add_edge("preenche_secao", "preenche_proxima")
    g.add_edge("montar_final", "review_final")
    g.add_conditional_edges(
        "review_final",
        lambda s: rotear(s, settings.max_review_rounds, settings.max_passos),
        {"review_estrutura": "review_estrutura", END: END},
    )
    logger.info("Fluxo 3 compiled")
    return g.compile()


def _decide_review_estrutura(state: dict, settings) -> str:
    review = state.get("review")
    if review is None:
        return "preenche_proxima"
    if review.aprovado:
        return "preenche_proxima"
    # Estrutura reprovada: re-plana.
    return "plan_estrutural"


def _decide_preenche(state: dict) -> str:
    acao = state.get("acao", "")
    if acao == "montar_final":
        return "montar_final"
    return "preenche_secao"


# ===========================================================================
# Roteador — executa os 3 fluxos num mesmo run_dir e compara
# ===========================================================================


def run_tres_fluxos(model, settings, tema: str | None = None, run_dir=None):
    """Executa os 3 fluxos e devolve um dict comparativo."""
    from forge.services.artefatos import criar_run_dir

    if run_dir is None:
        run_dir = criar_run_dir(settings, tema or "teste-tres-fluxos")

    results = {}
    for nome_fluxo, builder in [
        ("fluxo1", build_fluxo1),
        ("fluxo2", build_fluxo2),
        ("fluxo3", build_fluxo3),
    ]:
        logger.info("Executando fluxo", fluxo=nome_fluxo)
        g = builder(model, settings, inicio="tema" if not tema else "tema")
        fd = run_dir / nome_fluxo
        fd.mkdir(parents=True, exist_ok=True)
        estado = {
            "tema": tema,
            "rounds": 0,
            "passos": 0,
            "run_dir": fd,
        }
        try:
            final = g.invoke(estado)
            results[nome_fluxo] = {
                "sucesso": True,
                "aprovado": final.get("review", {}).aprovado if final.get("review") else None,
                "rounds": final.get("rounds", 0),
                "passos": final.get("passos", 0),
                "roteiro": final.get("roteiro"),
                "erro": None,
            }
        except Exception as e:
            logger.error("Fluxo falhou", fluxo=nome_fluxo, error=str(e), exc_info=True)
            results[nome_fluxo] = {
                "sucesso": False,
                "aprovado": None,
                "rounds": 0,
                "passos": 0,
                "roteiro": None,
                "erro": str(e),
            }

    return {
        "run_dir": run_dir,
        "temas": tema,
        "fluxos": results,
    }
