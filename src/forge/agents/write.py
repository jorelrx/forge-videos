from langchain_core.messages import HumanMessage

from forge.infrastructure.logging import get_logger
from forge.prompts.loader import load_prompt
from forge.domain.models import Fonte, Nota, Roteiro, RoteiroDraft, Secao
from forge.domain.roteiro import canonizar_nome
from forge.llms.model import invoke_structured
from forge.skills.loader import load_skills

logger = get_logger(__name__)

SKILLS = ["writing", "story", "retention", "fact_check"]
LE = ["tema", "tese", "esboco", "research_notes", "fontes", "review", "run_dir"]


def escrever(
    model,
    tema: str,
    tese: str,
    esboco: str,
    research: str,
    fontes: list[Fonte],
    notas: list[Nota] | None = None,
    *,
    run_dir=None,
) -> tuple[Roteiro, str | None]:
    logger.debug("Starting write phase", tema=tema[:50] + "..." if len(tema) > 50 else tema)
    prompt = load_prompt("write").format(
        tese=tese,
        esboco=esboco,
        research=research,
        fontes=_fmt_fontes(fontes),
        notas=_fmt_notas(notas),
        skills=load_skills(SKILLS, "write"),
    )
    draft = invoke_structured(
        model, RoteiroDraft, [HumanMessage(content=prompt)],
        run_dir=run_dir, etapa="write", subfase="structured",
    )
    # Canoniza na fronteira: é aqui que a saída do modelo vira o contrato
    # fechado das nove seções. `Tensão` do modelo vira `Tensao` do domínio,
    # antes de qualquer gate, artefato ou retomada ler os nomes.
    roteiro_resultado = Roteiro(
        tema=tema,
        tese=tese,
        secoes=[
            Secao(nome=canonizar_nome(secao.nome), conteudo=secao.conteudo)
            for secao in draft.secoes
        ],
        fontes=fontes,
    )
    logger.info(
        "Write phase completed",
        num_secoes=len(roteiro_resultado.secoes),
        falta_pesquisa=bool(draft.falta_pesquisa),
    )
    return roteiro_resultado, draft.falta_pesquisa


def _fmt_fontes(fontes: list[Fonte]) -> str:
    if not fontes:
        return "(nenhuma fonte citável)"
    return "\n".join(
        f"- {fonte.autor or 'autor desconhecido'} — {fonte.titulo}"
        for fonte in fontes
    )


def _fmt_notas(notas: list[Nota] | None) -> str:
    if not notas:
        return "(nenhuma — primeira versão)"
    return "\n".join(f"- [{n.dimensao}] {n.problema} → {n.sugestao}" for n in notas)
