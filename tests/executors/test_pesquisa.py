from pathlib import Path
import os
from types import SimpleNamespace

import pytest

from forge.domain.execucao import FailureClass, RunSnapshot
from forge.domain.operacao import StageName
from forge.executors.pesquisa import ResearchExecutor
from forge.agents.research import ResearchBundle
from forge.domain.models import Fonte, VeredictoRelevancia
from forge.infrastructure.config import Settings
from forge.services.acervo import AcervoIndisponivel


def _snapshot(tmp_path: Path) -> RunSnapshot:
    output_root = tmp_path / "runs"
    return RunSnapshot(
        run_id="run-1",
        video_id="video-1",
        tema="A consciência",
        tese="A consciência organiza a experiência.",
        stage=StageName.PESQUISA,
        attempt=1,
        output_root=output_root,
        run_dir=output_root / "run-1",
        config_snapshot={},
        artifacts=[],
        work_items=[],
    )


class FakeModel:
    def __init__(self):
        self.responses = iter(["consciência", "brief com fontes"])

    def invoke(self, messages):
        from langchain_core.messages import AIMessage

        return AIMessage(content=next(self.responses))


def passage(path):
    return SimpleNamespace(
        path=path,
        book_id=1,
        book_title="Livro público",
        authors=["Autora"],
        breadcrumb="Capítulo 1",
        text="evidência literal",
        url="https://acervo.test/books/1",
        score=0.9,
    )


class FakeAcervo:
    def __init__(self, passages):
        self.passages = passages

    def buscar(self, query, **kwargs):
        return self.passages

    def descobrir(self, query, **kwargs):
        return []


class OfflineAcervo:
    def buscar(self, query, **kwargs):
        raise AcervoIndisponivel("offline")

    def descobrir(self, query, **kwargs):
        raise AssertionError("discover must not be used after unavailable search")


def test_research_requires_minimum_canonical_sources(tmp_path, scripted):
    events = []
    executor = ResearchExecutor(
        model=scripted(invoke_texts=["consciência", "Consciência", "brief com fontes"]),
        acervo=FakeAcervo([passage(None), passage("12/ch1/p2")]),
        minimum_sources=2,
        settings=Settings(_env_file=None, juiz_relevancia=False),
    )

    result = executor.run(
        _snapshot(tmp_path), lambda **event: events.append(event)
    )

    assert not result.gate.approved
    assert result.gate.code == "research_gate_failed"
    assert {finding.code for finding in result.gate.findings} == {
        "research_source_missing_path",
        "research_minimum_not_met",
    }


@pytest.mark.parametrize("aprovar_complemento", [True, False])
def test_research_complements_partial_evidence_before_the_gate(
    tmp_path, scripted, acervo_fake, aprovar_complemento,
):
    acervo = acervo_fake(por_query={
        "conflito entre decisão e vontade": [passage("12/ch1/p1"), passage("12/ch1/p2")],
        "pressão social sobre as decisões": [
            passage("12/ch1/p2"), passage("42/ch3/p7"),
            *(passage(f"78/ch2/p{i}") for i in range(10)),
        ],
    })
    model = scripted(
        invoke_texts=[
            "conflito entre decisão e vontade",
            "Conflito entre decisão e vontade\npressão social sobre as decisões",
            "brief consolidado",
        ],
        structured=[
            VeredictoRelevancia(relevantes=[0, 1], motivo=""),
            VeredictoRelevancia(relevantes=[0, 1] if aprovar_complemento else [], motivo=""),
        ],
    )
    context = _snapshot(tmp_path)
    executor = ResearchExecutor(
        model=model,
        acervo=acervo,
        minimum_sources=3,
        settings=Settings(_env_file=None, juiz_relevancia=True),
    )

    result = executor.run(context, lambda **event: None)

    assert result.gate.approved is aprovar_complemento
    assert acervo.chamadas == [
        "conflito entre decisão e vontade", "pressão social sobre as decisões",
    ]
    bundle = ResearchBundle.model_validate_json(
        (context.run_dir / "video" / "research.json").read_bytes()
    )
    expected = ["12/ch1/p1", "12/ch1/p2"]
    if aprovar_complemento:
        expected.append("42/ch3/p7")
    else:
        assert result.gate.findings[0].details == {"found": 2, "required": 3}
    assert bundle.canonical_paths == expected
    assert bundle.brief == "brief consolidado"


def test_research_persists_bundle_and_emits_counts_without_passage_bodies(tmp_path):
    events = []
    executor = ResearchExecutor(
        model=FakeModel(),
        acervo=FakeAcervo([passage("12/ch1/p1")]),
        minimum_sources=1,
        settings=Settings(_env_file=None, juiz_relevancia=False),
    )

    result = executor.run(
        _snapshot(tmp_path), lambda **event: events.append(event)
    )

    assert result.gate.approved
    assert (result_dir := _snapshot(tmp_path).run_dir / "video" / "research.json").is_file()
    assert (result_dir.parent.parent / "01-research.md").is_file()
    assert (result_dir.parent.parent / "01-research.raw.md").is_file()
    for event in events:
        assert "evidência literal" not in str(event["payload"])
    assert [event["payload"]["metadata"]["passage_count"] for event in events] == [1, 1, 1]


def test_research_markdown_artifacts_use_atomic_replace(tmp_path, monkeypatch):
    import forge.executors.pesquisa as pesquisa_module

    run_dir = tmp_path / "run"
    bundle = ResearchBundle(
        brief="brief",
        fontes=[Fonte(titulo="Livro", path="1/ch1/p1")],
        raw_markdown="raw",
        passages=[
            {"path": "1/ch1/p1", "title": "Livro", "text": "evidência"}
        ],
        passage_count=1,
        canonical_paths=["1/ch1/p1"],
    )
    replaced = []
    real_replace = os.replace

    def record_replace(source, target):
        replaced.append(Path(target).name)
        return real_replace(source, target)

    monkeypatch.setattr(pesquisa_module.os, "replace", record_replace)

    pesquisa_module.ResearchExecutor._write_artifacts(
        run_dir, bundle, lambda **event: None
    )

    assert "01-research.md" in replaced
    assert "01-research.raw.md" in replaced


def test_research_unavailable_has_stable_transient_failure(tmp_path):
    executor = ResearchExecutor(
        model=FakeModel(), acervo=OfflineAcervo(), minimum_sources=1,
        settings=Settings(_env_file=None, juiz_relevancia=False),
    )

    result = executor.run(_snapshot(tmp_path), lambda **event: None)

    assert result.failure_class is FailureClass.TRANSIENT
    assert result.gate.findings[0].code == "research_unavailable"


def test_pesquisa_com_pauta_usa_briefing_e_pausa_em_contradicao(tmp_path, monkeypatch):
    import forge.executors.pesquisa as modulo
    from forge.domain.pauta import ConferenciaPauta

    pedidos = []
    original = modulo.pesquisar

    def espiao(*args, **kwargs):
        pedidos.append(kwargs.get("pedido"))
        return original(*args, **kwargs)

    monkeypatch.setattr(modulo, "pesquisar", espiao)
    monkeypatch.setattr(modulo, "conferir_pauta", lambda *a, **k: ConferenciaPauta(
        compativel=False, explicacao="A fonte contraria.", evidencias=["12/ch1/p1"], recorte_proposto="Outro recorte"))
    snapshot = _snapshot(tmp_path).model_copy(update={"config_snapshot": {"pauta_aprovada": {
        "tema": "A consciência", "promessa": "Promessa", "recorte": "Recorte", "perguntas_pesquisa": ["Quem disse?"]}}})
    events = []
    executor = ResearchExecutor(model=FakeModel(), acervo=FakeAcervo([passage("12/ch1/p1")]), minimum_sources=1,
                                settings=Settings(_env_file=None, juiz_relevancia=False))

    result = executor.run(snapshot, lambda **event: events.append(event))

    assert result.gate.approved
    assert "Pergunta de pesquisa: Quem disse?" in pedidos[0]
    conflito = next(e["payload"] for e in events if e["payload"].get("kind") == "conflito_pauta")
    assert conflito["metadata"]["recorte_proposto"] == "Outro recorte"
    assert conflito["metadata"]["promessa_proposta"] == "Promessa"
    assert conflito["metadata"]["evidencias"][0]["trecho"] == "evidência literal"


def test_falha_da_conferencia_nao_trava_a_pesquisa(tmp_path, monkeypatch):
    import forge.executors.pesquisa as modulo

    def quebra(*a, **k):
        raise TimeoutError()

    monkeypatch.setattr(modulo, "conferir_pauta", quebra)
    snapshot = _snapshot(tmp_path).model_copy(update={"config_snapshot": {"pauta_aprovada": {"tema": "A consciência"}}})
    events = []
    executor = ResearchExecutor(model=FakeModel(), acervo=FakeAcervo([passage("12/ch1/p1")]), minimum_sources=1,
                                settings=Settings(_env_file=None, juiz_relevancia=False))
    result = executor.run(snapshot, lambda **event: events.append(event))
    assert result.gate.approved
    assert not any(e["payload"].get("kind") == "conflito_pauta" for e in events)
    assert any(e["level"] == "warning" for e in events)
