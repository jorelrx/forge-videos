from pathlib import Path
from types import SimpleNamespace

from forge.domain.execucao import FailureClass, RunSnapshot
from forge.domain.operacao import StageName
from forge.executors.pesquisa import ResearchExecutor
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


def test_research_requires_minimum_canonical_sources(tmp_path):
    events = []
    executor = ResearchExecutor(
        model=FakeModel(),
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


def test_research_unavailable_has_stable_transient_failure(tmp_path):
    executor = ResearchExecutor(
        model=FakeModel(), acervo=OfflineAcervo(), minimum_sources=1,
        settings=Settings(_env_file=None, juiz_relevancia=False),
    )

    result = executor.run(_snapshot(tmp_path), lambda **event: None)

    assert result.failure_class is FailureClass.TRANSIENT
    assert result.gate.findings[0].code == "research_unavailable"
