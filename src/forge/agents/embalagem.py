"""Embala o roteiro aprovado para publicação no YouTube.

Roda com o LLM ainda residente, junto do plano de mídia, e só sobre roteiro
aprovado. A entrada é o roteiro e as citações — nenhuma pesquisa nova, para que
não nasça aqui uma afirmação que o roteiro não fez.

O modelo propõe o que é criativo (títulos, thumbnail, abertura, rótulos, tags).
O que é fato sai do código: tempo dos capítulos, fontes e o comentário fixado.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from langchain_core.messages import HumanMessage

from forge.domain.embalagem import (
    Capitulo, Embalagem, EmbalagemProposta, RotuloCapitulo, ThumbnailProposta,
    TituloProposto,
)
from forge.domain.models import Roteiro
from forge.domain.roteiro import ARQUITETURA, canonizar_nome
from forge.infrastructure.logging import get_logger
from forge.llms.model import invoke_structured
from forge.narracao.fatiar import PALAVRAS_POR_SEGUNDO, dividir_frases, texto_narravel
from forge.prompts.loader import load_prompt
from forge.services.citacoes import Citacao
from forge.services.linha_tempo import TrechoTempo, inicio_das_secoes
from forge.services.persistencia import gravar_modelo
from forge.services.qualidade_embalagem import (
    CAPITULO_SEGUNDOS_MINIMO, conferir_embalagem,
)
from forge.services.qualidade_roteiro import ScriptGateReport

logger = get_logger(__name__)

AVISO_IA = (
    "Narração e imagens deste vídeo foram geradas com inteligência artificial, "
    "a partir de um roteiro baseado nas obras citadas acima."
)

_PAPEIS = {secao.nome: secao.papel for secao in ARQUITETURA}


class EmbalagemReprovada(RuntimeError):
    """A embalagem não passou no gate nem depois da segunda tentativa."""

    def __init__(self, report: ScriptGateReport) -> None:
        self.report = report
        super().__init__(
            "embalagem reprovada: " + ", ".join(sorted(report.codes))
        )


def _uma_linha(texto: str) -> str:
    return " ".join(texto.split())


def estimar_capitulos(roteiro: Roteiro, rotulos: Iterable[RotuloCapitulo]) -> list[Capitulo]:
    """Um capítulo por seção, com o início estimado pela contagem de palavras.

    O tempo real só existe depois do TTS; a montagem o substitui. O rótulo vem
    do modelo e por isso é tratado com desconfiança: seção desconhecida é
    ignorada, e seção sem rótulo cai no papel dela na arquitetura — melhor um
    rótulo sem graça que um capítulo faltando, que derruba todos no YouTube.
    """
    por_secao = {
        canonizar_nome(rotulo.secao): _uma_linha(rotulo.titulo)
        for rotulo in rotulos if _uma_linha(rotulo.titulo)
    }
    capitulos: list[Capitulo] = []
    palavras = 0
    for secao in roteiro.secoes:
        titulo = por_secao.get(secao.nome) or _PAPEIS.get(secao.nome, secao.nome).capitalize()
        capitulos.append(Capitulo(
            secao=secao.nome, titulo=titulo,
            inicio_segundos=round(palavras / PALAVRAS_POR_SEGUNDO),
        ))
        palavras += len(texto_narravel(secao.conteudo).split())
    return capitulos


def fontes_da_descricao(citacoes: Iterable[Citacao]) -> list[str]:
    """Uma linha por obra citada, na ordem em que aparece no roteiro."""
    fontes: dict[tuple[str, str], str] = {}
    for citacao in citacoes:
        chave = (citacao.autor, citacao.obra)
        if chave in fontes:
            continue
        linha = f"{citacao.autor} — {citacao.obra}" if citacao.autor else citacao.obra
        if citacao.url:
            linha += f" ({citacao.url})"
        fontes[chave] = linha
    return list(fontes.values())


def comentario_fixado(roteiro: Roteiro) -> str:
    """A pergunta que encerra o Espelho: é ela que puxa comentário."""
    espelho = next((s for s in roteiro.secoes if s.nome == "Espelho"), None)
    if espelho is None:
        return ""
    frases = dividir_frases(texto_narravel(espelho.conteudo))
    if not frases:
        return ""
    ultima = frases[-1]
    # "Há algo mais delicado a reconhecer: qual exigência você...?" — a oração
    # antes dos dois-pontos é ponte da narração, não parte da pergunta. Só corta
    # quando o que sobra ainda é uma pergunta de verdade.
    _, separador, pergunta = ultima.rpartition(": ")
    if separador and pergunta.endswith("?") and len(pergunta.split()) >= 4:
        return pergunta[0].upper() + pergunta[1:]
    return ultima


def _tempo(segundos: int) -> str:
    horas, resto = divmod(segundos, 3600)
    minutos, seg = divmod(resto, 60)
    if horas:
        return f"{horas}:{minutos:02d}:{seg:02d}"
    return f"{minutos:02d}:{seg:02d}"


def montar_descricao(
    proposta: EmbalagemProposta,
    capitulos: list[Capitulo],
    fontes: list[str],
    *,
    aviso_ia: bool,
) -> str:
    return _descricao(
        proposta.abertura, proposta.resumo, capitulos, fontes, proposta.hashtags,
        aviso_ia=aviso_ia,
    )


def _descricao(
    abertura: str,
    resumo: str,
    capitulos: list[Capitulo],
    fontes: list[str],
    hashtags: list[str],
    *,
    aviso_ia: bool,
    musica: str | None = None,
) -> str:
    blocos = [_uma_linha(abertura)]
    if resumo.strip():
        blocos.append(resumo.strip())
    if capitulos:
        blocos.append("\n".join(
            ["Capítulos"] + [f"{_tempo(c.inicio_segundos)} {c.titulo}" for c in capitulos]
        ))
    if fontes:
        blocos.append("\n".join(["Fontes"] + [f"- {fonte}" for fonte in fontes]))
    if musica:
        blocos.append(f"Música: {_uma_linha(musica)}")
    if aviso_ia:
        blocos.append(AVISO_IA)
    if hashtags:
        blocos.append(" ".join(hashtags))
    return "\n\n".join(blocos)


def aplicar_tempos_reais(
    embalagem: Embalagem,
    tempos: list[TrechoTempo],
    *,
    musica: str | None,
    aviso_ia: bool,
) -> Embalagem:
    """Troca a estimativa por palavra pelo tempo real do áudio.

    Roda na montagem, quando a duração de cada bloco já existe. Capítulo que
    começa a menos de 10 s do anterior é absorvido por ele: o YouTube descarta
    TODOS os capítulos se um for curto, e perder um marcador custa menos.
    Seção sem bloco na narração não tem para onde apontar e sai da lista.

    Sem linha do tempo, ou com embalagem gravada antes de a abertura ser
    guardada, devolve a entrada: não há como remontar a descrição, e a
    estimativa — com a marca `capitulos_estimados` — é melhor que nada.
    """
    if not tempos or not embalagem.abertura.strip():
        return embalagem
    inicios = inicio_das_secoes(tempos)
    capitulos: list[Capitulo] = []
    for capitulo in embalagem.capitulos:
        if capitulo.secao not in inicios:
            continue
        inicio = round(inicios[capitulo.secao])
        if capitulos and inicio - capitulos[-1].inicio_segundos < CAPITULO_SEGUNDOS_MINIMO:
            logger.info(
                "Capítulo curto absorvido", secao=capitulo.secao,
                anterior=capitulos[-1].secao,
            )
            continue
        capitulos.append(capitulo.model_copy(update={"inicio_segundos": inicio}))
    return embalagem.model_copy(update={
        "capitulos": capitulos,
        "capitulos_estimados": False,
        "musica": musica,
        "descricao": _descricao(
            embalagem.abertura, embalagem.resumo, capitulos, embalagem.fontes,
            embalagem.hashtags, aviso_ia=aviso_ia, musica=musica,
        ),
    })


def _montar(
    proposta: EmbalagemProposta, roteiro: Roteiro, citacoes: list[Citacao], aviso_ia: bool,
) -> Embalagem:
    capitulos = estimar_capitulos(roteiro, proposta.capitulos)
    fontes = fontes_da_descricao(citacoes)
    return Embalagem(
        titulos=[
            TituloProposto(texto=_uma_linha(t.texto), angulo=_uma_linha(t.angulo))
            for t in proposta.titulos
        ],
        thumbnail=ThumbnailProposta(
            texto=_uma_linha(proposta.thumbnail.texto), prompt=proposta.thumbnail.prompt.strip(),
        ),
        descricao=montar_descricao(proposta, capitulos, fontes, aviso_ia=aviso_ia),
        capitulos=capitulos,
        capitulos_estimados=True,
        tags=[_uma_linha(tag) for tag in proposta.tags if tag.strip()],
        hashtags=[_uma_linha(tag) for tag in proposta.hashtags if tag.strip()],
        comentario_fixado=comentario_fixado(roteiro),
        fontes=fontes,
        abertura=_uma_linha(proposta.abertura),
        resumo=proposta.resumo.strip(),
    )


def _fmt_roteiro(roteiro: Roteiro) -> str:
    return "\n\n".join(f"## {secao.nome}\n{secao.conteudo}" for secao in roteiro.secoes)


def _fmt_achados(report: ScriptGateReport | None) -> str:
    if report is None:
        return "(nenhum — primeira tentativa)"
    return "\n".join(
        f"- {achado.code}: {achado.message}"
        + (f" {achado.details}" if achado.details else "")
        for achado in report.findings if achado.serious
    )


def embalar(
    model,
    roteiro: Roteiro,
    citacoes: list[Citacao],
    *,
    aviso_ia: bool = True,
    run_dir: Path | None = None,
    diretrizes_editoriais: str = "",
) -> Embalagem:
    """Propõe, monta e confere a embalagem; uma segunda tentativa se reprovar.

    Uma só repetição, com os achados no prompt: um título de 72 caracteres não
    justifica derrubar a etapa, mas um modelo que erra duas vezes não vai
    acertar na terceira — e cada tentativa gasta cota.
    """
    fontes = fontes_da_descricao(citacoes)
    report: ScriptGateReport | None = None
    for tentativa in (1, 2):
        prompt = load_prompt("embalagem").format(
            tese=roteiro.tese,
            roteiro=_fmt_roteiro(roteiro),
            fontes="\n".join(f"- {fonte}" for fonte in fontes) or "(nenhuma)",
            achados=_fmt_achados(report),
        )
        if diretrizes_editoriais:
            prompt += "\n\n## Proposta editorial aprovada\n\n" + diretrizes_editoriais
        proposta = invoke_structured(
            model, EmbalagemProposta, [HumanMessage(content=prompt)],
            run_dir=run_dir, etapa="embalagem", subfase=f"tentativa{tentativa}",
        )
        embalagem = _montar(proposta, roteiro, citacoes, aviso_ia)
        report = conferir_embalagem(embalagem)
        if report.approved:
            logger.info(
                "Embalagem aprovada", tentativa=tentativa,
                avisos=len(report.findings), capitulos=len(embalagem.capitulos),
            )
            return embalagem
        logger.warning(
            "Embalagem reprovada", tentativa=tentativa, achados=sorted(report.codes),
        )
    raise EmbalagemReprovada(report)


def _markdown(embalagem: Embalagem) -> str:
    titulos = "\n".join(
        f"{i}. {titulo.texto}" + (f" — {titulo.angulo}" if titulo.angulo else "")
        for i, titulo in enumerate(embalagem.titulos, start=1)
    )
    estimativa = (
        "\n\n> Tempos dos capítulos estimados pela contagem de palavras; "
        "confira com o vídeo final antes de publicar."
        if embalagem.capitulos_estimados else ""
    )
    return (
        "# Embalagem\n\n"
        f"## Títulos\n\n{titulos}\n\n"
        f"## Thumbnail\n\nTexto: {embalagem.thumbnail.texto}\n\n"
        f"Prompt: {embalagem.thumbnail.prompt}\n\n"
        f"## Descrição\n\n```\n{embalagem.descricao}\n```{estimativa}\n\n"
        f"## Tags\n\n{', '.join(embalagem.tags)}\n\n"
        f"## Comentário fixado\n\n{embalagem.comentario_fixado}\n"
    )


def gravar_embalagem(run_dir: Path, embalagem: Embalagem) -> tuple[Path, Path]:
    """`video/embalagem.json` para máquina, `embalagem.md` para colar no YouTube."""
    run_dir = Path(run_dir)
    estruturado = gravar_modelo(run_dir / "video" / "embalagem.json", embalagem)
    legivel = run_dir / "embalagem.md"
    legivel.write_text(_markdown(embalagem), encoding="utf-8")
    logger.info("Embalagem gravada", path=str(legivel))
    return estruturado, legivel


__all__ = [
    "AVISO_IA", "EmbalagemReprovada", "aplicar_tempos_reais", "comentario_fixado", "embalar",
    "estimar_capitulos", "fontes_da_descricao", "gravar_embalagem", "montar_descricao",
]
