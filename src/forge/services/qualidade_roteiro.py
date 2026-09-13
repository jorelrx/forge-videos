"""Deterministic quality checks for the narrative script gate.

The model review is useful editorial feedback, but never gets to overrule this
module.  Checks intentionally operate on plain text and typed source metadata
so a malformed or optimistic model response fails closed.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from statistics import median
from typing import Any, Iterable, Mapping

from pydantic import BaseModel, ConfigDict, Field

from forge.domain.models import Roteiro, Secao
from forge.domain.roteiro import ARQUITETURA


class GateFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    section: str | None = None
    severity: str = "grave"
    details: dict[str, Any] = Field(default_factory=dict)

    @property
    def serious(self) -> bool:
        return self.severity == "grave"


class ScriptGateReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool
    serious_count: int = Field(ge=0)
    findings: list[GateFinding] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)

    @property
    def codes(self) -> set[str]:
        # ``codes`` summarizes blocking defects.  Advisory findings remain
        # available in ``findings`` without making an approved script appear
        # rejected to callers using this compact view.
        return {finding.code for finding in self.findings if finding.serious}


_ROBOT_LABEL = re.compile(
    r"(?im)(?:^\s*(?:narra[cç][aã]o|cena|imagem|visual|voz|b[- ]?roll|sfx)\s*:\s*|\[(?:narra[cç][aã]o|cena|imagem|visual|voz)\])"
)
_SENTENCE = re.compile(r"[^.!?]+[.!?]?(?=\s|$)", re.UNICODE)


def _termina_com_pergunta(texto: str) -> bool:
    """Return true only when the final sentence itself is a question."""
    final = texto.strip()
    # Markdown/typographic closing punctuation is decoration, not prose after
    # the question.  A declarative sentence following ``?`` remains invalid.
    final = re.sub(r"[\s\"'“”‘’«»)\]}]+$", "", final)
    return final.endswith("?")


def _coerce_roteiro(value: Roteiro | Mapping[str, Any]) -> tuple[Roteiro, Mapping[str, Any]]:
    if isinstance(value, Roteiro):
        return value, {}
    payload = dict(value)
    nested = payload.get("roteiro")
    if isinstance(nested, Mapping):
        roteiro_payload = dict(nested)
        extras = {key: item for key, item in payload.items() if key != "roteiro"}
    else:
        known = {"tema", "tese", "secoes", "fontes"}
        roteiro_payload = {key: item for key, item in payload.items() if key in known}
        extras = {key: item for key, item in payload.items() if key not in known}
    roteiro = Roteiro.model_validate(roteiro_payload)
    return roteiro, extras


def _section_map(
    roteiro: Roteiro, extras: Mapping[str, Any], passages_by_section: Mapping[str, Any] | None
) -> Mapping[str, Any]:
    if passages_by_section is not None:
        return passages_by_section
    from_payload = extras.get("passages_by_section")
    if isinstance(from_payload, Mapping):
        return from_payload
    # Older callers only have global Fonte metadata.  It is still preferable to
    # losing source evidence entirely; per-section anchoring then checks text.
    return {section.nome: roteiro.fontes for section in roteiro.secoes}


def _source_fields(source: Any) -> tuple[str, list[str]]:
    if isinstance(source, Mapping):
        title = source.get("title", source.get("titulo", ""))
        authors = source.get("authors", source.get("autor", []))
    else:
        title = getattr(source, "title", getattr(source, "titulo", ""))
        authors = getattr(source, "authors", getattr(source, "autor", []))
    if isinstance(authors, str):
        authors = [authors]
    return str(title or ""), [str(author) for author in (authors or []) if author]


def _section_sources(section: Secao, source_map: Mapping[str, Any]) -> list[Any]:
    values = source_map.get(section.nome, [])
    if isinstance(values, Mapping) or isinstance(values, str):
        return [values]
    return list(values or [])


def _words(text: str) -> list[str]:
    return re.findall(r"\b[\wÀ-ÿ'’-]+\b", text, re.UNICODE)


def _opening(text: str) -> str:
    words = _words(text)
    return " ".join(words[:18]).casefold()


def _finding(
    code: str, message: str, *, section: str | None = None,
    severity: str = "grave", **details: Any,
) -> GateFinding:
    return GateFinding(
        code=code, message=message, section=section, severity=severity, details=details
    )


def conferir_secao(
    nome: str, secao: Secao | Mapping[str, Any] | str,
    passages: Iterable[Any] | None,
) -> ScriptGateReport:
    """Evaluate one section; Gancho intentionally skips source anchoring."""
    if isinstance(secao, str):
        texto = secao
    elif isinstance(secao, Mapping):
        texto = str(secao.get("conteudo", secao.get("content", "")))
    else:
        texto = secao.conteudo
    findings: list[GateFinding] = []
    spec = next((item for item in ARQUITETURA if item.nome == nome), None)
    if spec is not None:
        words = len(_words(texto))
        minimum, maximum = spec.alvo_palavras
        if words < minimum * 0.60:
            findings.append(_finding(
                "secao_curta", "Seção abaixo do mínimo narrativo", section=nome,
                palavras=words, minimo=minimum,
            ))
        elif words > maximum * 1.60:
            findings.append(_finding(
                "secao_longa", "Seção acima do máximo narrativo", section=nome,
                severity="aviso", palavras=words, maximo=maximum,
            ))
        for sentence in _SENTENCE.findall(texto):
            count = len(_words(sentence))
            if count > 40:
                findings.append(_finding(
                    "frase_longa", "Frase acima de 40 palavras", section=nome,
                    palavras=count,
                ))
                break
            if count > 35 and not any(item.code == "frase_longa_aviso" for item in findings):
                findings.append(_finding(
                    "frase_longa_aviso", "Frase acima de 35 palavras", section=nome,
                    severity="aviso", palavras=count,
                ))
        if nome != "Gancho":
            sources = list(passages or [])
            anchors = []
            for source in sources:
                title, authors = _source_fields(source)
                anchors.extend([title, *authors])
            lowered = texto.casefold()
            if not anchors or not any(anchor.strip().casefold() in lowered for anchor in anchors if anchor.strip()):
                findings.append(_finding(
                    "sem_citacao", "Seção factual sem âncora de autor ou título", section=nome,
                ))
        if nome == "Espelho" and not _termina_com_pergunta(texto):
            findings.append(_finding(
                "espelho_sem_pergunta", "Espelho precisa terminar abrindo uma pergunta ao público",
                section=nome,
            ))
        if nome == "Fecho" and not any(token in texto.casefold() for token in ("pergunta", "escolh", "retorn", "volte", "agora")):
            findings.append(_finding(
                "fecho_sem_loop", "Fecho não evidencia o retorno transformado ao Gancho",
                section=nome, severity="aviso",
            ))
    return ScriptGateReport(
        approved=not any(item.serious for item in findings),
        serious_count=sum(item.serious for item in findings),
        findings=findings,
        metrics={"sections_ok": 1 if spec is not None else 0, "robot_labels": len(_ROBOT_LABEL.findall(texto))},
    )


def avaliar_roteiro(
    roteiro: Roteiro | Mapping[str, Any],
    passages_by_section: Mapping[str, Any] | None = None,
) -> ScriptGateReport:
    """Run section and cross-section deterministic checks."""
    model, extras = _coerce_roteiro(roteiro)
    sources = _section_map(model, extras, passages_by_section)
    findings: list[GateFinding] = []
    metrics: dict[str, Any] = {"sections_ok": 0, "robot_labels": 0}
    names = [section.nome for section in model.secoes]
    expected = [section.nome for section in ARQUITETURA]
    if names != expected:
        findings.append(_finding(
            "script_sections_invalid", "Roteiro precisa ter exatamente as nove seções na ordem aprovada",
            expected=expected, received=names,
        ))
    else:
        metrics["sections_ok"] = len(expected)

    valid_names = set(expected)
    for section in model.secoes:
        if section.nome not in valid_names:
            continue
        result = conferir_secao(section.nome, section, _section_sources(section, sources))
        findings.extend(result.findings)
        metrics["robot_labels"] += result.metrics.get("robot_labels", 0)
    lengths = [_words(section.conteudo) for section in model.secoes if section.nome in valid_names]
    counts = [len(words) for words in lengths if words]
    if len(counts) >= 3:
        typical = float(median(counts))
        if typical:
            for section, words in zip(
                (item for item in model.secoes if item.nome in valid_names), lengths
            ):
                deviation = abs(len(words) - typical) / typical
                # One section can already have a more actionable grave defect
                # (e.g. a 40-word sentence).  Keep the report focused and do
                # not count the same outlier twice; isolated size drift still
                # gets its own blocking finding.
                has_grave = any(
                    item.serious and item.section == section.nome
                    for item in findings
                )
                if deviation > 0.45 and not has_grave:
                    findings.append(_finding(
                        "tamanho_desviante", "Tamanho da seção destoa do conjunto narrativo",
                        section=section.nome, desvio=round(deviation, 3),
                    ))
    labels = sum(len(_ROBOT_LABEL.findall(section.conteudo)) for section in model.secoes)
    metrics["robot_labels"] = labels
    openings = [(section.nome, _opening(section.conteudo)) for section in model.secoes if _opening(section.conteudo)]
    for index, (left_name, left) in enumerate(openings):
        for right_name, right in openings[index + 1:]:
            similarity = SequenceMatcher(None, left, right).ratio()
            if similarity > 0.45:
                findings.append(_finding(
                    "aberturas_parecidas", "Aberturas de seções são excessivamente parecidas",
                    section=right_name, similarity=round(similarity, 3), comparada_com=left_name,
                ))
                break
            if similarity > 0.30:
                findings.append(_finding(
                    "aberturas_parecidas_aviso", "Aberturas de seções têm pouca variação",
                    section=right_name, severity="aviso", similarity=round(similarity, 3), comparada_com=left_name,
                ))
                break
    serious_count = sum(item.serious for item in findings)
    metrics["finding_count"] = len(findings)
    metrics["serious_count"] = serious_count
    return ScriptGateReport(
        approved=serious_count == 0,
        serious_count=serious_count,
        findings=findings,
        metrics=metrics,
    )


def conferir_roteiro(
    roteiro: Roteiro | Mapping[str, Any],
    passages_by_section: Mapping[str, Any] | None = None,
) -> ScriptGateReport:
    return avaliar_roteiro(roteiro, passages_by_section)


__all__ = [
    "GateFinding", "ScriptGateReport", "avaliar_roteiro", "conferir_roteiro", "conferir_secao",
]
