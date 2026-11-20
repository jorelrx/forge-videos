"""Seletor de tema do canal: só entra o que o acervo sustenta.

Antes o tema era uma frase inventada pelo modelo, sem olhar os livros nem o
público — o último run real saiu com "O que é ética?", que é nome de disciplina
e não motivo para clicar. Aqui o modelo propõe candidatos pela dor do
espectador, o código busca cada um no acervo, e um segundo passo julga, com os
trechos na mão, quais têm fonte de verdade e quanto atraem.

A regra do canal começa aqui: tema sem fonte não vira roteiro.
"""

from __future__ import annotations

import json
import re

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from forge.domain.models import Eixo
from forge.infrastructure.logging import get_logger
from forge.llms.model import invoke_structured
from forge.prompts.loader import load_prompt
from forge.services.acervo import AcervoIndisponivel, Passagem, fmt_catalogo
from forge.skills.loader import EIXOS, resumo_eixos

logger = get_logger(__name__)

LE = ["tema"]

# Trechos mostrados ao juiz por candidato. Seis de 300 caracteres bastam para
# distinguir "fala do tema" de "menciona a palavra" sem estourar o contexto com
# uma dúzia de candidatos.
TRECHOS_POR_CANDIDATO = 6
CARACTERES_POR_TRECHO = 300


class SemTemaSustentado(RuntimeError):
    """O acervo não sustenta nenhum dos temas propostos.

    Levantar em vez de devolver um tema qualquer é deliberado: um tema inventado
    sem fonte é exatamente o conteúdo que o canal não publica.
    """


class TemaCandidato(BaseModel):
    tema: str
    eixo: Eixo
    dor: str = ""
    promessa: str = ""
    buscas: list[str] = Field(default_factory=list)


class TemasPropostos(BaseModel):
    candidatos: list[TemaCandidato] = Field(default_factory=list)


class VeredictoTema(BaseModel):
    indice: int
    sustentado: bool
    apelo: int = 3
    motivo: str = ""


class VeredictoTemas(BaseModel):
    veredictos: list[VeredictoTema] = Field(default_factory=list)


class TemaSugerido(BaseModel):
    tema: str
    eixo: str
    dor: str
    promessa: str
    livros: list[str]
    apelo: int
    motivo: str


class Sugestoes(BaseModel):
    temas: list[TemaSugerido] = Field(default_factory=list)
    # Eixos do canal para os quais nenhum candidato teve fonte: é o recado de
    # quais livros falta ingerir no projeto `research`.
    eixos_sem_cobertura: list[str] = Field(default_factory=list)


_TEMA_FRONTMATTER = re.compile(r"^tema:\s*(.+?)\s*$", re.MULTILINE)


def temas_feitos(settings) -> list[str]:
    """Temas de roteiros já produzidos, pelo CLI e pelo Studio.

    Arquivo ilegível ou malformado é pulado: esta lista só evita repetição, e
    uma run quebrada no disco não pode impedir a próxima de começar.
    """
    feitos: list[str] = []
    if settings.output_dir.is_dir():
        for caminho in sorted(settings.output_dir.glob("*.md")):
            try:
                texto = caminho.read_text(encoding="utf-8")
            except OSError:
                continue
            partes = texto.split("---", 2)
            achado = _TEMA_FRONTMATTER.search(partes[1]) if len(partes) >= 3 else None
            if achado:
                feitos.append(achado.group(1))
    if settings.studio_runs_dir.is_dir():
        for caminho in sorted(settings.studio_runs_dir.glob("*/video/input.json")):
            try:
                tema = json.loads(caminho.read_text(encoding="utf-8")).get("tema")
            except (OSError, ValueError, AttributeError):
                continue
            if isinstance(tema, str) and tema.strip():
                feitos.append(tema.strip())
    return list(dict.fromkeys(feitos))


def sugerir_temas(model, acervo, settings, *, n: int = 5) -> Sugestoes:
    """Temas que o acervo sustenta, do mais atraente para o menos."""
    livros = acervo.livros()
    feitos = temas_feitos(settings)
    prompt = load_prompt("tema_candidatos").format(
        quantidade=max(2 * n, 6),
        eixos=resumo_eixos(),
        catalogo=fmt_catalogo(livros),
        feitos="\n".join(f"- {tema}" for tema in feitos) or "(nenhum ainda)",
    )
    propostos = invoke_structured(
        model, TemasPropostos, [HumanMessage(content=prompt)],
        etapa="tema", subfase="candidatos",
    )
    candidatos = propostos.candidatos
    passagens = [_colher(acervo, candidato, settings.acervo_top) for candidato in candidatos]

    minimo = settings.research_min_sources
    elegiveis = [i for i, achadas in enumerate(passagens) if len(achadas) >= minimo]
    logger.info(
        "Candidatos de tema pesquisados",
        candidatos=len(candidatos), com_passagens=len(elegiveis), minimo=minimo,
    )
    if not elegiveis:
        return Sugestoes(temas=[], eixos_sem_cobertura=list(EIXOS))

    veredictos = invoke_structured(
        model, VeredictoTemas,
        [HumanMessage(content=load_prompt("tema_juiz").format(
            candidatos=_fmt_candidatos(candidatos, passagens, elegiveis),
        ))],
        etapa="tema", subfase="juiz",
    )
    # Índice fora dos elegíveis é descartado e candidato sem veredicto fica de
    # fora: na dúvida o tema não tem fonte, que é o lado seguro do erro.
    aprovados = {
        v.indice: v for v in veredictos.veredictos
        if v.indice in elegiveis and v.sustentado
    }
    sugeridos = [
        TemaSugerido(
            tema=candidatos[i].tema, eixo=candidatos[i].eixo,
            dor=candidatos[i].dor, promessa=candidatos[i].promessa,
            livros=list(dict.fromkeys(p.book_title for p in passagens[i])),
            apelo=min(5, max(1, veredicto.apelo)), motivo=veredicto.motivo,
        )
        for i, veredicto in sorted(aprovados.items())
    ]
    sugeridos.sort(key=lambda tema: (-tema.apelo, -len(tema.livros)))
    cobertos = {tema.eixo for tema in sugeridos}
    logger.info("Temas sugeridos", sustentados=len(sugeridos), pedidos=n)
    return Sugestoes(
        temas=sugeridos[:n],
        eixos_sem_cobertura=[eixo for eixo in EIXOS if eixo not in cobertos],
    )


def gerar_tema(model, tema: str | None = None, *, acervo=None, settings=None) -> str:
    if tema:
        logger.debug("Tema provided", tema=tema)
        return tema
    sugestoes = sugerir_temas(model, acervo, settings, n=1)
    if not sugestoes.temas:
        raise SemTemaSustentado(
            "Nenhum tema sustentado pelo acervo. Informe um tema com --tema ou "
            "ingira no projeto research as obras dos eixos sem cobertura: "
            + ", ".join(sugestoes.eixos_sem_cobertura)
        )
    escolhido = sugestoes.temas[0]
    logger.info("Topic chosen", tema=escolhido.tema, eixo=escolhido.eixo, apelo=escolhido.apelo)
    return escolhido.tema


def _colher(acervo, candidato: TemaCandidato, top: int) -> list[Passagem]:
    """Passagens das buscas do candidato, sem repetir caminho.

    Uma busca que falha é pulada: a busca semântica leva dezenas de segundos e
    um estouro de prazo isolado não pode derrubar a sugestão inteira. Se todas
    falharem, o candidato fica sem passagem e sai sozinho.
    """
    por_caminho: dict[str, Passagem] = {}
    for busca in candidato.buscas:
        try:
            achadas = acervo.buscar(busca, top=top)
        except AcervoIndisponivel as erro:
            logger.warning("Busca de tema pulada", busca=busca, error=str(erro))
            continue
        for passagem in achadas:
            por_caminho.setdefault(passagem.path, passagem)
    return list(por_caminho.values())


def _fmt_catalogo(livros) -> str:
    if not livros:
        return "(catálogo vazio)"
    return "\n".join(
        f"- {livro.title}"
        + (f" — {', '.join(livro.authors)}" if livro.authors else "")
        + (f" [{', '.join(livro.languages)}]" if livro.languages else "")
        for livro in livros
    )


def _fmt_candidatos(candidatos, passagens, elegiveis) -> str:
    blocos = []
    for indice in elegiveis:
        candidato = candidatos[indice]
        trechos = "\n".join(
            f"  - ({p.book_title}) {' '.join(p.text.split())[:CARACTERES_POR_TRECHO]}"
            for p in passagens[indice][:TRECHOS_POR_CANDIDATO]
        )
        blocos.append(
            f"[{indice}] {candidato.tema} — eixo {candidato.eixo}\n"
            f"dor: {candidato.dor}\npromessa: {candidato.promessa}\ntrechos:\n{trechos}"
        )
    return "\n\n".join(blocos)
