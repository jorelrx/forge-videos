"""Auditoria de fontes do roteiro: quem foi citado, onde e como.

Derivado por código dos blocos estruturados e das passagens do acervo — nenhum
modelo participa. O roteiro já carrega as referências por bloco; este módulo só
as achata num artefato legível (`video/citacoes.json`) que alimenta a seção de
fontes da descrição do vídeo e os cartões de citação da montagem.

Três tipos, e a diferença importa para o que aparece na tela:

- `literal`: o trecho está, igual, na passagem e na fala.
- `traducao`: o original está na passagem; a fala traz a nossa tradução,
  anunciada como tradução livre. Os livros do acervo são em inglês e alemão,
  então é este o caso comum de citação entre aspas.
- `parafrase`: a ideia é atribuída à obra sem reproduzir palavras.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Literal

from pydantic import BaseModel, Field, TypeAdapter

from forge.agents.research import PassageEvidence
from forge.domain.models import Roteiro
from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)

ARQUIVO = Path("video") / "citacoes.json"


class Citacao(BaseModel):
    secao: str
    bloco: int
    tipo: Literal["literal", "traducao", "parafrase"]
    texto: str
    original: str | None = None
    autor: str
    # Cada autor como o acervo o guarda. `autor` é a junção por vírgula, que
    # não distingue dois autores de um "Sobrenome, Nome"; quem precisa mostrar
    # o nome na ordem de leitura usa esta lista. Vazia em arquivos antigos.
    autores: list[str] = Field(default_factory=list)
    obra: str
    path: str
    book_id: int | None = None
    url: str | None = None


_LISTA = TypeAdapter(list[Citacao])


def derivar_citacoes(
    roteiro: Roteiro, passagens: Iterable[PassageEvidence],
) -> list[Citacao]:
    """Uma entrada por citação entre aspas e uma por paráfrase atribuída.

    Referência cujo caminho não está nas passagens é omitida, não inventada:
    sem a passagem não há autor nem obra para atribuir. Acontece em roteiros
    antigos, cujas evidências não foram guardadas.
    """
    por_caminho = {p.path: p for p in passagens if p.path}
    citacoes: list[Citacao] = []
    for secao in roteiro.secoes:
        for indice, bloco in enumerate(secao.blocos):
            citados: set[str] = set()
            for literal in bloco.citacoes_literais:
                passagem = por_caminho.get(literal.path)
                if passagem is None:
                    continue
                citados.add(literal.path)
                traduzida = bool(literal.traducao)
                citacoes.append(_citacao(
                    secao.nome, indice, passagem,
                    tipo="traducao" if traduzida else "literal",
                    texto=literal.traducao if traduzida else literal.trecho,
                    original=literal.trecho if traduzida else None,
                ))
            for caminho in bloco.referencias:
                passagem = por_caminho.get(caminho)
                if passagem is None or caminho in citados:
                    continue
                citados.add(caminho)
                citacoes.append(_citacao(
                    secao.nome, indice, passagem, tipo="parafrase", texto=bloco.texto,
                ))
    return citacoes


def _citacao(
    secao: str, bloco: int, passagem: PassageEvidence, *,
    tipo: str, texto: str, original: str | None = None,
) -> Citacao:
    return Citacao(
        secao=secao, bloco=bloco, tipo=tipo, texto=texto, original=original,
        autor=", ".join(passagem.authors), autores=list(passagem.authors),
        obra=passagem.title,
        path=passagem.path, book_id=passagem.book_id,
        url=getattr(passagem, "url", "") or None,
    )


def gravar_citacoes(run_dir: Path, citacoes: list[Citacao]) -> Path:
    destino = Path(run_dir) / ARQUIVO
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(_LISTA.dump_json(citacoes, indent=2))
    logger.info("Citações gravadas", path=str(destino), citacoes=len(citacoes))
    return destino


def carregar_citacoes(run_dir: Path) -> list[Citacao]:
    """Lista vazia quando a run não tem o arquivo (runs anteriores a ele)."""
    origem = Path(run_dir) / ARQUIVO
    if not origem.is_file():
        return []
    return _LISTA.validate_json(origem.read_bytes())


def citacoes_da_run(run_dir: Path, roteiro: Roteiro) -> list[Citacao]:
    """Citações de uma run do Studio, com ou sem `citacoes.json`.

    Runs anteriores ao arquivo ainda têm as evidências da pesquisa
    (`video/research-evidence.json`): delas dá para derivar a mesma lista. Sem
    nenhum dos dois não há fonte a declarar, e a lista volta vazia.
    """
    citacoes = carregar_citacoes(run_dir)
    if citacoes:
        return citacoes
    evidencias = Path(run_dir) / "video" / "research-evidence.json"
    if not evidencias.is_file():
        return []
    try:
        dados = json.loads(evidencias.read_text(encoding="utf-8"))
        passagens = [PassageEvidence.model_validate(p) for p in dados.get("passages", [])]
    except (OSError, ValueError, AttributeError) as erro:
        logger.warning("Evidências ilegíveis", path=str(evidencias), error=str(erro))
        return []
    return derivar_citacoes(roteiro, passagens)


__all__ = [
    "ARQUIVO", "Citacao", "carregar_citacoes", "citacoes_da_run", "derivar_citacoes",
    "gravar_citacoes",
]
