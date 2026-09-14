"""Testes para executor de validação final."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.domain.execucao import GateResult, StageChildResult, ArtifactOutput
from forge.domain.operacao import StageName, Artifact
from forge.domain.operacao import WorkItem, ItemStatus
from forge.executors.validacao import ValidationExecutor
from forge.domain.execucao import RunSnapshot


class FakeArtifact:
    def __init__(self, kind, relative_path, is_current=True, metadata=None):
        self.kind = kind
        self.relative_path = relative_path
        self.is_current = is_current
        self.metadata = metadata or {}


def _artifact(kind, path, is_current=True, meta=None):
    return Artifact(
        id="a1", run_id="run-1", stage_run_id="s1", work_item_id=None,
        kind=kind, relative_path=path,
        sha256="a" * 64, size_bytes=1024, mime_type="audio/wav" if kind.startswith("audio") else "image/png",
        metadata=meta or {}, is_current=is_current,
        created_at="2026-09-13T00:00:00Z",
    )


def _work_item(key, status=ItemStatus.SUCCEEDED):
    return WorkItem(
        id=f"w-{key}", stage_run_id="s1", item_key=key,
        status=status, input={}, input_hash="a" * 64,
        attempts=1, duration_ms=100,
    )


def _snapshot(tmp_path: Path, stage=StageName.VALIDACAO, artifacts=None, work_items=(), run_dir=None) -> RunSnapshot:
    root = tmp_path / "runs"
    rd = run_dir or (root / "run-1")
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "video").mkdir(parents=True, exist_ok=True)
    real_arts = []
    for a in (artifacts or []):
        if isinstance(a, Artifact):
            real_arts.append(a)
        else:
            # Convert FakeArtifact to Artifact
            real_arts.append(_artifact(
                a.kind, a.relative_path, a.is_current, a.metadata
            ))
    real_items = []
    for w in work_items:
        if isinstance(w, WorkItem):
            real_items.append(w)
        else:
            # Assume fake item; skip if not WorkItem
            real_items.append(_work_item(str(w)))
    return RunSnapshot(
        run_id="run-1",
        video_id="v1",
        tema="Tema",
        tese="Tese",
        stage=stage,
        attempt=1,
        output_root=root,
        run_dir=rd,
        config_snapshot={},
        artifacts=real_arts,
        work_items=real_items,
    )


def test_final_gate_cross_checks_plan_items_and_artifacts(tmp_path):
    artifacts = [_artifact("audio.wav", f"video/audio/b{i:03d}.wav") for i in range(40)]
    work_items = [_work_item(f"b{i:03d}", ItemStatus.SUCCEEDED) for i in range(41)]
    snapshot = _snapshot(tmp_path, artifacts=artifacts, work_items=work_items)
    result = ValidationExecutor().run(snapshot, lambda **e: None)
    assert result.gate.code == "final_validation_failed"
    assert any(f.code == "audio_count_mismatch" for f in result.gate.findings)


def _wav_de_silencio(path: Path, segundos: float = 0.2) -> None:
    """Narração real (silêncio puro) para o gate analisar."""
    import wave

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x00\x00" * int(24000 * segundos))


def _runner_sem_silencio(argv, **kwargs):
    return 0, "size=N/A time=00:00:00.20 bitrate=N/A", b""


def _runner_com_silencio(argv, **kwargs):
    return 0, "silence_start: 1.0\nsilence_duration: 3.30\n", b""


def test_silencio_real_da_narracao_reprova(tmp_path):
    snapshot = _snapshot(tmp_path)
    _wav_de_silencio(snapshot.run_dir / "video" / "narration.wav")

    result = ValidationExecutor(
        max_unplanned_silence_seconds=2.0, runner=_runner_com_silencio
    ).run(snapshot, lambda **e: None)

    assert "unexpected_silence" in [f.code for f in result.gate.findings]


def test_fixtures_de_teste_nao_valem_como_analise_da_narracao(tmp_path):
    """A fixture `silence-failed.txt` (45,32 s) não é análise desta run.

    Enquanto o gate lia `tests/fixtures/ffmpeg/silence-*.txt`, toda validação em
    produção — CWD na raiz do repo — reprovava por um silêncio que o vídeo não
    tem, e a run terminava com o gate final reprovado sem defeito real.
    """
    fixtures = [
        Path("tests/fixtures/ffmpeg/silence-failed.txt"),
        Path("tests/fixtures/ffmpeg/silence-ok.txt"),
    ]
    assert all(item.is_file() for item in fixtures), "fixtures ausentes"
    texto = "".join(item.read_text(encoding="utf-8") for item in fixtures)
    assert "silence_duration: 45.32" in texto

    snapshot = _snapshot(tmp_path)
    _wav_de_silencio(snapshot.run_dir / "video" / "narration.wav")

    result = ValidationExecutor(
        max_unplanned_silence_seconds=2.0, runner=_runner_sem_silencio
    ).run(snapshot, lambda **e: None)

    assert "unexpected_silence" not in [f.code for f in result.gate.findings]


def test_all_sample_frames_must_be_extractable(tmp_path):
    snapshot = _snapshot(tmp_path)
    (snapshot.run_dir / "video" / "final.mp4").write_bytes(b"not a video")
    result = ValidationExecutor().run(snapshot, lambda **e: None)
    assert any(f.code == "frame_sample_failed" for f in result.gate.findings)


def test_valid_report_is_registered_before_worker_can_complete(tmp_path):
    artifacts = [_artifact("audio.wav", f"video/audio/b{i:03d}.wav") for i in range(41)]
    artifacts += [_artifact("image/png", f"video/images/i{i:03d}.png") for i in range(9)]
    snapshot = _snapshot(tmp_path, artifacts=artifacts)
    (snapshot.run_dir / "video" / "final.mp4").write_bytes(b"fake")
    result = ValidationExecutor().run(snapshot, lambda **e: None)
    assert (snapshot.run_dir / "video" / "validation.json").is_file()
    kinds = [art.kind for art in result.artifacts]
    assert "validation.report" in kinds


def test_gate_approved_for_complete_run(tmp_path):
    artifacts = [_artifact("audio.wav", f"video/audio/b{i:03d}.wav") for i in range(41)]
    artifacts += [_artifact("image/png", f"video/images/i{i:03d}.png") for i in range(9)]
    snapshot = _snapshot(tmp_path, artifacts=artifacts)
    result = ValidationExecutor().run(snapshot, lambda **e: None)
    assert not any(f.code == "audio_count_mismatch" for f in result.gate.findings)
    assert not any(f.code == "image_artifact_missing" for f in result.gate.findings)
    assert (snapshot.run_dir / "video" / "validation.json").is_file()
