from langchain_core.messages import HumanMessage

from forge.infrastructure.logging import get_logger
from forge.prompts.loader import load_prompt
from forge.domain.models import Fonte, Nota, Roteiro, Secao, SecaoDraft
from forge.domain.roteiro import ARQUITETURA, SECOES_NOMES, NarrativeSection, canonizar_nome
from forge.llms.model import invoke_structured
from forge.narracao.fatiar import texto_narravel
from forge.skills.loader import carregar_eixo, load_skills

logger = get_logger(__name__)

SKILLS = ["writing", "story", "retention", "fact_check", "canal"]
LE = [
    "tema", "tese", "esboco", "research_notes", "fontes", "research_passages",
    "review", "roteiro", "eixo", "run_dir",
]


def escrever(
    model,
    tema: str,
    tese: str,
    esboco: str,
    research: str,
    fontes: list[Fonte],
    notas: list[Nota] | None = None,
    *,
    research_passages=None,
    run_dir=None,
    anterior: Roteiro | None = None,
    eixo: str | None = None,
    diretrizes: str = "",
) -> tuple[Roteiro, str | None]:
    """Escreve o roteiro uma seção por chamada.

    Pedir as nove seções de uma vez fazia o modelo encurtar o texto — um vídeo
    de 11 a 16 minutos são ~2.000 palavras, emitidas duas vezes (`conteudo` e
    `blocos`). Por seção, cada chamada tem alvo próprio e enxerga o que já foi
    escrito.

    Na revisão, só as seções apontadas pelas notas são reescritas; as demais
    passam intactas. Antes a rodada de revisão regenerava o roteiro inteiro sem
    sequer receber a versão anterior.
    """
    logger.debug("Starting write phase", tema=tema[:50] + "..." if len(tema) > 50 else tema)
    evidencias = {
        getattr(p, "path", None): p for p in (research_passages or [])
        if getattr(p, "path", None)
    }
    notas = list(notas or [])
    alvo, notas_por_secao, notas_gerais = _plano_de_revisao(notas, anterior, tese)
    antigas = {secao.nome: secao for secao in anterior.secoes} if anterior else {}

    comuns = {
        "tese": tese,
        "esboco": esboco,
        "research": research,
        "fontes": _fmt_fontes(fontes),
        "passagens": _fmt_passagens(research_passages or []),
        "eixo_referencia": carregar_eixo(eixo),
        "skills": load_skills(SKILLS, "write"),
        "fluxo_geracao": (
            "\n\n## Fluxo de geração\n\nAplique nesta seção as diretrizes que cabem ao "
            "papel dela. Preserve as regras de conteúdo, blocos e referências.\n\n"
            f"{diretrizes}" if diretrizes else ""
        ),
    }
    secoes: list[Secao] = []
    falta: str | None = None
    for spec in ARQUITETURA:
        if spec.nome not in alvo:
            secoes.append(antigas[spec.nome])
            continue
        antiga = antigas.get(spec.nome)
        prompt = load_prompt("write_secao").format(
            secao=spec.nome,
            papel=spec.papel,
            instrucao=spec.instrucao,
            alvo_min=spec.alvo_palavras[0],
            alvo_max=spec.alvo_palavras[1],
            anteriores=_fmt_anteriores(secoes),
            texto_anterior=antiga.conteudo if antiga and notas else "(nenhuma — primeira versão)",
            notas=_fmt_notas(notas_por_secao.get(spec.nome, []) + notas_gerais),
            **comuns,
        )
        draft = invoke_structured(
            model, SecaoDraft, [HumanMessage(content=prompt)],
            run_dir=run_dir, etapa="write", subfase=spec.nome,
        )
        secoes.append(_validar_secao(spec, draft, evidencias))
        if falta is None and draft.falta_pesquisa:
            falta = draft.falta_pesquisa

    roteiro_resultado = Roteiro(tema=tema, tese=tese, secoes=secoes, fontes=fontes)
    logger.info(
        "Write phase completed",
        num_secoes=len(roteiro_resultado.secoes),
        reescritas=len(alvo),
        falta_pesquisa=bool(falta),
    )
    return roteiro_resultado, falta


def _plano_de_revisao(
    notas: list[Nota], anterior: Roteiro | None, tese: str,
) -> tuple[set[str], dict[str, list[Nota]], list[Nota]]:
    """Quais seções escrever, e com que notas.

    A revisão dirigida só vale quando há o que preservar: um roteiro anterior
    com as nove seções, defendendo a MESMA tese. Depois de uma volta pela
    pesquisa o plano é refeito, e seções antigas mantidas ao lado de novas
    defenderiam teses diferentes no mesmo vídeo.

    Nota sem seção — ou apontando um nome fora do contrato — vira nota geral e
    manda reescrever tudo. Descartá-la em silêncio faria o revisor repetir a
    mesma nota para sempre.
    """
    todas = set(SECOES_NOMES)
    por_secao: dict[str, list[Nota]] = {}
    gerais: list[Nota] = []
    for nota in notas:
        nome = canonizar_nome(nota.secao) if nota.secao else ""
        if nome in todas:
            por_secao.setdefault(nome, []).append(nota)
        else:
            gerais.append(nota)

    preservavel = (
        anterior is not None
        and anterior.tese == tese
        and [secao.nome for secao in anterior.secoes] == SECOES_NOMES
    )
    if not notas or gerais or not preservavel:
        return todas, por_secao, gerais
    return set(por_secao), por_secao, gerais


def _validar_secao(spec: NarrativeSection, draft: SecaoDraft, evidencias: dict) -> Secao:
    """Transforma a saída do modelo numa seção do contrato, ou recusa."""
    nome = spec.nome
    conteudo = draft.conteudo
    if not conteudo.strip():
        # Alguns modelos entregam a narração estruturada, mas deixam o campo
        # espelhado `conteudo` vazio. Os blocos são a fonte completa e ordenada;
        # reconstruí-lo aqui mantém o contrato sem perder texto nem citações.
        conteudo = " ".join(bloco.texto.strip() for bloco in draft.blocos).strip()
        if not conteudo:
            raise ValueError(f"seção sem conteúdo nem blocos de narração: {nome}")

    if evidencias:
        if not draft.blocos:
            raise ValueError(f"seção sem blocos estruturados de narração: {nome}")
        if nome != "Gancho" and not any(bloco.referencias for bloco in draft.blocos):
            raise ValueError(f"seção factual sem referências do acervo: {nome}")
        esperado = texto_narravel(conteudo)
        obtido = " ".join(bloco.texto.strip() for bloco in draft.blocos).strip()
        if esperado != obtido:
            raise ValueError(f"blocos não reproduzem a narração da seção: {nome}")

    for bloco in draft.blocos:
        desconhecidas = set(bloco.referencias) - evidencias.keys()
        if desconhecidas:
            raise ValueError(f"referências sem passagem do acervo: {sorted(desconhecidas)}")
        for citacao in bloco.citacoes_literais:
            passagem = evidencias.get(citacao.path)
            if passagem is None or citacao.path not in bloco.referencias:
                raise ValueError(f"citação literal sem referência válida: {citacao.path}")
            if not _citacao_confere(citacao, passagem.text, bloco.texto):
                raise ValueError(f"trecho literal não confere com roteiro e acervo: {citacao.path}")
    return Secao(nome=nome, conteudo=conteudo, blocos=draft.blocos)


def _sem_espacos_extras(texto: str) -> str:
    return " ".join(texto.split())


def _citacao_confere(citacao, passagem: str, fala: str) -> bool:
    """O original tem de estar na passagem; o que a fala diz, na fala.

    Com `traducao`, o que a fala diz é a tradução — o original fica só na
    passagem. Sem ela, o mesmo trecho precisa estar nos dois lugares. A
    comparação ignora espaço duplicado e quebra de linha: o modelo os troca ao
    copiar, e isso não muda nenhuma palavra.
    """
    trecho = _sem_espacos_extras(citacao.trecho)
    if not trecho or trecho not in _sem_espacos_extras(passagem):
        return False
    falado = _sem_espacos_extras(citacao.traducao) if citacao.traducao else trecho
    return bool(falado) and falado in _sem_espacos_extras(fala)


def _fmt_anteriores(secoes: list[Secao]) -> str:
    if not secoes:
        return "(nenhuma — esta é a primeira seção)"
    return "\n\n".join(f"### {secao.nome}\n{secao.conteudo}" for secao in secoes)


def _fmt_fontes(fontes: list[Fonte]) -> str:
    if not fontes:
        return "(nenhuma fonte citável)"
    return "\n".join(
        f"- {fonte.autor or 'autor desconhecido'} — {fonte.titulo}"
        for fonte in fontes
    )


def _fmt_passagens(passagens) -> str:
    return "\n\n".join(
        f"### {p.path} — {p.title} ({', '.join(p.authors)})\n{p.text}"
        for p in passagens
    ) or "(nenhuma passagem disponível)"


def _fmt_notas(notas: list[Nota] | None) -> str:
    if not notas:
        return "(nenhuma — primeira versão)"
    return "\n".join(f"- [{n.dimensao}] {n.problema} → {n.sugestao}" for n in notas)
