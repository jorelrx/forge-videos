from langchain_core.messages import HumanMessage

from forge.agents.research import ResearchBundle
from forge.domain.editorial import PropostasEditoriais
from forge.llms.model import invoke_structured


def propor_recortes(
    model, tema: str, tese: str | None, bundle: ResearchBundle, *,
    fluxo=None, referencias_editoriais: str = "", run_dir=None,
) -> PropostasEditoriais:
    evidencias = "\n".join(
        f"{p.path} | {p.title} | {p.text[:450]}"
        for p in bundle.passages if p.path
    )
    prompt = (
        "Proponha dois ou três recortes distintos para um ensaio filosófico em português "
        "do Brasil. Em cada proposta, escreva um título de trabalho, uma situação observável "
        "para abrir, uma pergunta específica, a virada filosófica, como retomar a abertura "
        "no fecho e uma direção visual concreta para a thumbnail. Em fonte, use exclusivamente "
        "um caminho do acervo listado abaixo. Apresente um ângulo que as passagens sustentem. "
        "Mantenha a tese fornecida quando houver.\n\n"
        f"Tema: {tema}\nTese fornecida: {tese or '(livre)'}\n"
        f"Fluxo: {fluxo.instrucoes if fluxo and fluxo.instrucoes else 'padrão'}\n\n"
        f"Pesquisa: {bundle.brief}\n\nPassagens:\n{evidencias}\n\n"
        "Use as referências editoriais fornecidas apenas para entender temas e formatos. "
        "Crie recortes originais e sustente as atribuições apenas no acervo.\n"
        f"Referências editoriais: {referencias_editoriais or '(nenhuma)'}"
    )
    recortes = invoke_structured(
        model, PropostasEditoriais, [HumanMessage(content=prompt)],
        run_dir=run_dir, etapa="pesquisa", subfase="recortes-editoriais",
    )
    caminhos = {p.path for p in bundle.passages if p.path}
    if any(p.fonte not in caminhos for p in recortes.propostas):
        raise ValueError("A proposta editorial citou uma passagem fora da pesquisa")
    return recortes
