from pathlib import Path

from forge.domain.execucao import RunSnapshot
from forge.domain.operacao import StageName
from forge.executors.preparacao import PreparationExecutor


def _snapshot(tmp_path: Path, **changes) -> RunSnapshot:
    output_root = tmp_path / "runs"
    values = {
        "run_id": "run-1",
        "video_id": "video-1",
        "tema": "A consciência",
        "tese": "A consciência organiza a experiência.",
        "stage": StageName.PREPARACAO,
        "attempt": 1,
        "output_root": output_root,
        "run_dir": output_root / "run-1",
        "config_snapshot": {},
        "artifacts": [],
        "work_items": [],
    }
    values.update(changes)
    return RunSnapshot(**values)


def _events():
    seen = []

    def emit(**event):
        seen.append(event)

    return seen, emit


def test_preparation_creates_only_canonical_run_tree(tmp_path):
    snapshot = _snapshot(tmp_path)
    events, emit = _events()

    result = PreparationExecutor().run(snapshot, emit)

    assert (snapshot.run_dir / "video" / "input.json").is_file()
    assert result.gate.approved
    assert [event["payload"]["relative_path"] for event in events if event["kind"] == "artifact.created"] == [
        "video/input.json"
    ]
    assert sorted(path.relative_to(snapshot.run_dir).as_posix() for path in snapshot.run_dir.rglob("*")) == [
        "video",
        "video/input.json",
    ]


def test_preparation_rejects_unknown_snapshot_fields_before_writing(tmp_path):
    snapshot = _snapshot(tmp_path, config_snapshot={"api_key": "secret"})

    result = PreparationExecutor().run(snapshot, lambda **event: None)

    assert not result.gate.approved
    assert result.gate.code == "preparation_snapshot_invalid"
    assert not snapshot.run_dir.exists()


def test_preparation_gate_rejects_missing_persisted_snapshot(tmp_path):
    snapshot = _snapshot(tmp_path)
    executor = PreparationExecutor()
    plan = executor.prepare(snapshot)
    result = executor.execute(snapshot, plan, lambda **event: None)
    (snapshot.run_dir / "video" / "input.json").unlink()

    gate = executor.validate(snapshot, plan, result)

    assert not gate.approved
    assert gate.code == "preparation_snapshot_invalid"
