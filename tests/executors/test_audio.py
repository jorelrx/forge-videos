from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import wave

import pytest

from forge.domain.execucao import RunSnapshot
from forge.domain.midia import BlocoNarracao, PlanoMidia
from forge.domain.operacao import ItemStatus, StageName, WorkItem
from forge.executors.audio import AudioExecutor
from forge.executors.audio_generate import AudioOutcome
from forge.infrastructure.config import Settings
from forge.services.persistencia import gravar_modelo


def _wav(path: Path, *, sample_rate: int = 24000, channels: int = 1, frames: int = 2400):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(b"\0\0" * channels * frames)


def _snapshot(tmp_path: Path, *, work_items=(), stage=StageName.AUDIO) -> RunSnapshot:
    root = tmp_path / "runs"
    snapshot = RunSnapshot(
        run_id="run-1", video_id="video-1", tema="Tema", tese="Tese", stage=stage,
        attempt=1, output_root=root, run_dir=root / "run-1", config_snapshot={},
        artifacts=[], work_items=list(work_items),
    )
    gravar_modelo(snapshot.run_dir / "video" / "midia.json", PlanoMidia(blocos=[
        BlocoNarracao(id="b001", secao="A", texto="Primeiro texto."),
        BlocoNarracao(id="b002", secao="A", texto="Segundo texto."),
        BlocoNarracao(id="b003", secao="B", texto="Terceiro texto."),
    ]))
    return snapshot


class Broker:
    def __init__(self): self.calls = []
    @contextmanager
    def exclusivo(self, resource):
        self.calls.append(resource)
        yield


class Client:
    def __init__(self, fail_batch=False):
        self.calls = []
        self.fail_batch = fail_batch
    def synthesize_batch(self, items, output_dir):
        keys = [item.item_key for item in items]
        self.calls.append(keys)
        outcomes = []
        for item in items:
            path = output_dir / f"{item.item_key}.wav"
            if self.fail_batch and len(items) > 1:
                outcomes.append(AudioOutcome.failed(item.item_key, "tts_process_failed", "batch failed"))
            else:
                _wav(path)
                outcomes.append(AudioOutcome.succeeded(item.item_key, path))
        return outcomes


def _settings(tmp_path: Path, **kwargs) -> Settings:
    return Settings(_env_file=None, audio_generate_dir=tmp_path / "audio-generate", **kwargs)


def test_prepare_reads_blocks_and_uses_canonical_hash(tmp_path):
    snapshot = _snapshot(tmp_path)
    plan = AudioExecutor(settings=_settings(tmp_path)).prepare(snapshot)

    assert plan.stage is StageName.AUDIO
    assert [item.item_key for item in plan.items] == ["b001", "b002", "b003"]
    assert plan.items[0].input_hash == "3b1ef995af6583446a3d99eff4d91b0f04bde41df1bb4bef4fd06224ffe49e0b"


def test_prepare_rejects_non_audio_context(tmp_path):
    with pytest.raises(ValueError, match="audio"):
        AudioExecutor(settings=_settings(tmp_path)).prepare(_snapshot(tmp_path, stage=StageName.IMAGENS))


def test_run_batches_then_retries_every_unfinished_block_once_under_one_broker_lock(tmp_path):
    client, broker, events = Client(fail_batch=True), Broker(), []
    executor = AudioExecutor(settings=_settings(tmp_path, tts_batch_size=3), client=client, broker=broker)

    result = executor.run(_snapshot(tmp_path), lambda **event: events.append(event))

    assert client.calls == [["b001", "b002", "b003"], ["b001"], ["b002"], ["b003"]]
    assert broker.calls == ["tts"]
    assert result.current_items == result.total_items == 3
    assert result.gate.approved
    assert all(event["payload"].get("duration_ms") is not None for event in events if event["kind"] == "item.started")
    assert [event["payload"]["item_key"] for event in events if event["kind"] == "artifact.created"] == ["b001", "b002", "b003"]


def test_validate_rejects_incomplete_current_outputs(tmp_path):
    snapshot = _snapshot(tmp_path)
    executor = AudioExecutor(settings=_settings(tmp_path))
    plan = executor.prepare(snapshot)
    _wav(snapshot.run_dir / "video" / "audio" / "b001.wav")
    result = executor._result_for_paths(snapshot, plan, {"b001": snapshot.run_dir / "video" / "audio" / "b001.wav"})

    gate = executor.validate(snapshot, plan, result)

    assert not gate.approved
    assert gate.code == "audio_incomplete"
    assert gate.metrics["current_items"] == 1
    assert gate.metrics["total_items"] == 3


def test_validate_rejects_non_mono_or_wrong_sample_rate(tmp_path):
    snapshot = _snapshot(tmp_path)
    executor = AudioExecutor(settings=_settings(tmp_path))
    plan = executor.prepare(snapshot)
    paths = {}
    for key in ("b001", "b002", "b003"):
        path = snapshot.run_dir / "video" / "audio" / f"{key}.wav"
        _wav(path, sample_rate=22050 if key == "b001" else 24000, channels=2 if key == "b002" else 1)
        paths[key] = path

    gate = executor.validate(snapshot, plan, executor._result_for_paths(snapshot, plan, paths))

    assert {finding.code for finding in gate.findings} >= {"audio_sample_rate", "audio_channels"}


def test_previous_attempt_output_is_reused_from_parent_verified_snapshot(tmp_path):
    snapshot = _snapshot(tmp_path)
    reusable = snapshot.run_dir / "video" / "audio" / "b001.wav"
    _wav(reusable)
    from forge.domain.operacao import Artifact
    from forge.domain.execucao import ReusableOutput
    from forge.executors.plano_midia import hash_json

    artifact = Artifact(
        id="prior-audio", run_id=snapshot.run_id, stage_run_id="previous-stage",
        work_item_id="previous-item", kind="audio.wav",
        relative_path="video/audio/b001.wav",
        sha256=__import__("hashlib").sha256(reusable.read_bytes()).hexdigest(),
        size_bytes=reusable.stat().st_size, mime_type="audio/wav", metadata={"seed": 42},
        is_current=True, created_at="2026-09-13T00:00:00Z",
    )
    client, events = Client(), []
    result = AudioExecutor(settings=_settings(tmp_path), client=client, broker=Broker()).run(
        snapshot.model_copy(update={"reusable_outputs": [ReusableOutput(
            artifact=artifact,
            input_hash=hash_json(BlocoNarracao(id="b001", secao="A", texto="Primeiro texto.")),
        )]}),
        lambda **event: events.append(event),
    )

    assert client.calls == [["b002", "b003"]]
    assert [event["kind"] for event in events if event["payload"].get("item_key") == "b001"] == [
        "item.planned", "item.started", "artifact.created", "item.succeeded"
    ]
    assert result.current_items == 3


def test_voice_outlier_is_retried_with_alternate_seed_before_gate(tmp_path):
    import math

    class VoiceClient:
        def __init__(self): self.seeds = []
        def synthesize_batch(self, items, output_dir):
            result = []
            for item in items:
                self.seeds.append(item.seed)
                path = output_dir / f"{item.item_key}.wav"
                frequency = 440 if item.item_key == "b003" and item.seed is None else 200
                path.parent.mkdir(parents=True, exist_ok=True)
                frames = bytearray()
                for index in range(2400):
                    frames.extend(int(20000 * math.sin(2 * math.pi * frequency * index / 24000)).to_bytes(2, "little", signed=True))
                with wave.open(str(path), "wb") as output:
                    output.setnchannels(1); output.setsampwidth(2); output.setframerate(24000); output.writeframes(frames)
                result.append(AudioOutcome.succeeded(item.item_key, path))
            return result

    snapshot = _snapshot(tmp_path)
    media = PlanoMidia.model_validate_json((snapshot.run_dir / "video" / "midia.json").read_text())
    media.blocos.extend([
        BlocoNarracao(id="b004", secao="B", texto="Quarto texto."),
        BlocoNarracao(id="b005", secao="B", texto="Quinto texto."),
    ])
    gravar_modelo(snapshot.run_dir / "video" / "midia.json", media)
    client = VoiceClient()

    result = AudioExecutor(settings=_settings(tmp_path, tts_batch_size=8), client=client, broker=Broker()).run(snapshot, lambda **event: None)

    assert result.gate.approved
    assert 1042 in client.seeds
