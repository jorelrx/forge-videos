from pathlib import Path

from forge.domain.execucao import GateResult, RunSnapshot, StageExecutionResult
from forge.domain.models import Fonte, Roteiro, Secao
from forge.domain.operacao import StageName
from forge.agents.research import ResearchBundle
from forge.executors.roteiro import ScriptExecutor
from forge.infrastructure.config import Settings
from forge.services.persistencia import gravar_modelo


def _snapshot(tmp_path: Path) -> RunSnapshot:
    root = tmp_path / "runs"
    return RunSnapshot(
        run_id="run-1", video_id="video-1", tema="Tema", tese="Tese",
        stage=StageName.ROTEIRO, attempt=1, output_root=root,
        run_dir=root / "run-1", config_snapshot={}, artifacts=[], work_items=[],
    )


def test_prepare_hash_includes_research_artifact_and_preset(tmp_path):
    context = _snapshot(tmp_path)
    executor = ScriptExecutor(settings=Settings(_env_file=None))
    first = executor.prepare(context)
    context.artifacts.append({
        "id": "a1", "run_id": "run-1", "stage_run_id": "s1",
        "kind": "research_bundle", "relative_path": "video/research.json",
        "sha256": "a" * 64, "size_bytes": 1, "mime_type": "application/json",
        "metadata": {}, "is_current": True, "created_at": "2026-09-13T00:00:00Z",
    })
    second = executor.prepare(context)
    assert first.input_hash != second.input_hash


def test_validate_rejects_script_even_when_model_review_was_optimistic(tmp_path):
    executor = ScriptExecutor(settings=Settings(_env_file=None))
    executor._roteiro = {"tema": "Tema", "tese": "Tese", "secoes": [{"nome": "Gancho", "conteudo": "curto"}]}
    result = StageExecutionResult(current_items=1, total_items=1)
    gate = executor.validate(_snapshot(tmp_path), executor.prepare(_snapshot(tmp_path)), result)
    assert not gate.approved
    assert gate.code == "script_gate_failed"
    assert any(finding.code == "script_sections_invalid" for finding in gate.findings)


def test_execute_passes_reentered_research_evidence_to_gate(tmp_path, monkeypatch):
    context = _snapshot(tmp_path)
    context.run_dir.mkdir(parents=True)
    initial = {"path": "1/ch1/p1", "title": "Fonte inicial", "authors": ["Autor 1"], "text": "x"}
    reentered = {"path": "2/ch2/p2", "title": "Fonte dirigida", "authors": ["Autor 2"], "text": "y"}
    bundle = ResearchBundle(
        brief="brief", fontes=[Fonte(titulo="Fonte inicial", autor="Autor 1", path="1/ch1/p1")],
        raw_markdown="raw", passages=[initial], passage_count=1,
        canonical_paths=["1/ch1/p1"],
    )
    gravar_modelo(context.run_dir / "video" / "research.json", bundle)

    roteiro = Roteiro(
        tema="Tema", tese="Tese",
        secoes=[Secao(nome=name, conteudo="Autor 2 sustenta esta ideia com clareza.") for name in [
            "Gancho", "Estake", "Tensao", "Virada", "Filosofo", "Prova",
            "Espelho", "Aplicacao", "Fecho",
        ]],
    )

    class Graph:
        def invoke(self, state):
            return {"roteiro": roteiro, "research_passages": [reentered]}

    monkeypatch.setattr("forge.executors.roteiro.build_graph", lambda *args, **kwargs: Graph())
    executor = ScriptExecutor(settings=Settings(_env_file=None), model=object())
    executor.execute(context, executor.prepare(context), lambda **event: None)
    assert executor._passages_by_section["Prova"][0].path == "2/ch2/p2"
