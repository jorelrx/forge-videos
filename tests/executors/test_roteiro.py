from pathlib import Path

from forge.domain.execucao import GateResult, RunSnapshot, StageExecutionResult
from forge.domain.operacao import StageName
from forge.executors.roteiro import ScriptExecutor
from forge.infrastructure.config import Settings


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
