"""Ponte entre o fluxo de roteiro e a camada de conhecimento.

Chamada só quando `settings.knowledge_enabled`. Duas direções:
- consultar: puxa contexto da biblioteca para o brief de pesquisa;
- aprender: ingere o brief como documento web (aprendizado contínuo).

Nunca deixa a geração cair por causa dos stores: falha de infra vira log e o
research segue com o que já tinha.
"""
from forge.infrastructure.config import Settings
from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)


def formatar_contexto(chunks: list[dict]) -> str:
    """Chunks recuperados -> bloco de texto com proveniência para o brief."""
    if not chunks:
        return ""
    linhas = ["## Contexto da biblioteca\n"]
    for c in chunks:
        proc = c.get("obra") or c.get("fonte") or c.get("url") or "fonte desconhecida"
        cap = f", {c['capitulo']}" if c.get("capitulo") else ""
        linhas.append(f"- ({proc}{cap}) {c.get('texto', '')}")
    return "\n".join(linhas)


def consultar_e_aprender(tema: str, brief: str, settings: Settings) -> str:
    """Devolve o brief possivelmente enriquecido com contexto da biblioteca, e
    ingere o brief atual como material web. Best-effort: erro não propaga."""
    try:
        from forge.knowledge.ingest import _montar
        from forge.knowledge.retriever.hybrid import retrieve

        model, embed_fn, stores = _montar(settings)
        chunks = retrieve(tema, embed_fn=embed_fn, vector=stores.vector, catalog=stores.catalog)
        contexto = formatar_contexto(chunks)

        from forge.knowledge.domain.models import Documento, Proveniencia, id_deterministico
        from forge.knowledge.ingest import ingerir_documentos

        doc = Documento(
            id=id_deterministico("brief", tema),
            titulo=f"Brief: {tema}",
            texto=brief,
            proveniencia=Proveniencia.de_web(url=f"brief://{tema}", titulo=tema),
        )
        ingerir_documentos([doc], model=model, embed_fn=embed_fn, stores=stores, settings=settings)
    except Exception as e:
        logger.warning("Camada de conhecimento indisponível, seguindo sem ela", error=str(e))
        return brief

    return f"{brief}\n\n{contexto}".strip() if contexto else brief
