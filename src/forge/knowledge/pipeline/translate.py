"""Estágio LLM: traduz um termo de busca para o idioma-alvo de uma fonte.

Fontes só-inglês (ex: SEP) rendem muito mais quando a query vai em inglês.
Traduz só o termo curto — barato. Se já estiver no idioma-alvo, o modelo devolve
inalterado; falha/resposta vazia cai para o texto original (best-effort: tradução
nunca deve impedir a busca).
"""
from langchain_core.messages import HumanMessage

from forge.infrastructure.logging import get_logger
from forge.llms.parsing import _texto

logger = get_logger(__name__)

_NOMES = {
    "en": "inglês",
    "pt": "português",
    "es": "espanhol",
    "fr": "francês",
    "de": "alemão",
    "it": "italiano",
}

_PROMPT = (
    "Traduza o termo de busca a seguir para {idioma}. Se já estiver em {idioma}, "
    "devolva-o inalterado. Responda apenas com a tradução, sem aspas, sem "
    "pontuação extra, sem explicação.\n\nTermo: {texto}"
)


def traduzir(model, texto: str, idioma: str) -> str:
    nome = _NOMES.get(idioma, idioma)
    try:
        resp = model.invoke([HumanMessage(content=_PROMPT.format(idioma=nome, texto=texto))])
        traduzido = _texto(resp).strip()
    except Exception as e:
        logger.warning("Tradução falhou, usando query original", idioma=idioma, error=str(e))
        return texto
    if not traduzido:
        return texto
    logger.info("Query traduzida", idioma=idioma, de=texto, para=traduzido)
    return traduzido
