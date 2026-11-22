"""Confronta a pauta aprovada com as passagens que a pesquisa encontrou."""
from langchain_core.messages import HumanMessage

from forge.agents.research import ResearchBundle
from forge.domain.pauta import ConferenciaPauta, PautaEpisodio
from forge.llms.model import invoke_structured


def conferir_pauta(model, pauta: PautaEpisodio, bundle: ResearchBundle, *, run_dir=None) -> ConferenciaPauta:
    evidencias = "\n".join(f"{p.path} | {p.title} | {p.text[:450]}" for p in bundle.passages if p.path)
    prompt = (
        "Compare a pauta aprovada com as passagens do acervo. Marque compativel=false somente quando as "
        "passagens contrariarem a promessa ou o recorte, ou quando não houver material que os sustente. "
        "Nesse caso, explique a contradição, cite em evidencias os caminhos das passagens que a mostram "
        "e proponha um recorte e/ou uma promessa que as fontes sustentem, preservando o tema. "
        "Use apenas caminhos listados abaixo.\n\n"
        f"Tema: {pauta.tema}\nPromessa: {pauta.promessa}\nRecorte: {pauta.recorte}\n"
        f"Perguntas de pesquisa: {'; '.join(pauta.perguntas_pesquisa) or '(nenhuma)'}\n\n"
        f"Síntese da pesquisa: {bundle.brief}\n\nPassagens:\n{evidencias}"
    )
    conferencia = ConferenciaPauta.model_validate(invoke_structured(
        model, ConferenciaPauta, [HumanMessage(content=prompt)],
        run_dir=run_dir, etapa="pesquisa", subfase="conferencia-pauta",
    ))
    caminhos = {p.path for p in bundle.passages if p.path}
    if set(conferencia.evidencias) - caminhos:
        raise ValueError("A conferência da pauta citou uma passagem fora da pesquisa")
    return conferencia
