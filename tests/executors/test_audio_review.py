from __future__ import annotations

import math
import wave
from contextlib import contextmanager
from pathlib import Path

from forge.domain.execucao import RunSnapshot
from forge.domain.midia import BlocoNarracao, PlanoMidia
from forge.domain.operacao import Artifact, ItemStatus, StageName, WorkItem
from forge.executors.audio import AudioExecutor, validate_wav
from forge.executors.audio_generate import AudioOutcome, classify_audio_failure
from forge.executors.plano_midia import hash_json
from forge.infrastructure.config import Settings
from forge.services.persistencia import gravar_modelo


def _wav(path: Path, *, rate: int = 24000, channels: int = 1, frequency: int = 200) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = bytearray()
    for index in range(2400):
        sample = int(20000 * math.sin(2 * math.pi * frequency * index / rate))
        frames.extend(sample.to_bytes(2, "little", signed=True) * channels)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(frames)
    return path


def _settings(tmp_path: Path, **kwargs) -> Settings:
    return Settings(_env_file=None, audio_generate_dir=tmp_path / "audio-generate", **kwargs)


def _snapshot(tmp_path: Path, *, work_items=(), reusable_outputs=()) -> RunSnapshot:
    root = tmp_path / "runs"
    snapshot = RunSnapshot(
        run_id="run-1", video_id="video-1", tema="Tema", tese="Tese",
        stage=StageName.AUDIO, attempt=2, output_root=root, run_dir=root / "run-1",
        config_snapshot={}, artifacts=[], work_items=list(work_items),
        reusable_outputs=list(reusable_outputs),
    )
    gravar_modelo(snapshot.run_dir / "video" / "midia.json", PlanoMidia(blocos=[
        BlocoNarracao(id="b001", secao="A", texto="Primeiro texto."),
        BlocoNarracao(id="b002", secao="A", texto="Segundo texto."),
    ]))
    return snapshot


class Broker:
    @contextmanager
    def exclusivo(self, resource):
        yield


class Servidor:
    def __init__(self, backend):
        self.backend = backend
        self.url = f"falso://{backend}"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def reiniciar(self):
        return None


def _executor(tmp_path, client, **kwargs):
    return AudioExecutor(
        settings=_settings(tmp_path, **kwargs), client=client, broker=Broker(),
        servidor_factory=lambda backend, pasta: Servidor(backend),
    )


class Client:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.seeds: list[int | None] = []

    def synthesize(self, request, servidor, output_dir):
        self.calls.append(request.item_key)
        self.seeds.append(request.seed)
        frequency = 440 if request.item_key == "b002" and request.seed in (42, 1042) else 200
        return AudioOutcome.succeeded(
            request.item_key, _wav(Path(output_dir) / f"{request.item_key}.wav", frequency=frequency)
        )


def test_public_audio_failure_classifier_has_stable_known_classes():
    deterministic = classify_audio_failure("reached max_tokens before EOC", status=500)
    capacity = classify_audio_failure("ggml_vulkan: Device memory allocation", status=500)

    assert (deterministic.code, deterministic.failure_class, deterministic.retriable) == (
        "tts_max_tokens_before_eoc", "deterministic", False
    )
    assert (capacity.code, capacity.failure_class, capacity.retriable) == (
        "tts_vulkan_oom", "capacity", True
    )


def test_validate_wav_reports_wrong_rate_and_channels_together(tmp_path):
    findings = validate_wav(_wav(tmp_path / "stereo.wav", rate=44100, channels=2), expected_rate=24000, expected_channels=1)

    assert {finding.code for finding in findings} == {"audio_sample_rate", "audio_channels"}


def test_audio_emits_one_terminal_event_only_after_cpu_rescue(tmp_path):
    class RescueClient(Client):
        def synthesize(self, request, servidor, output_dir):
            self.calls.append(request.item_key)
            if request.item_key == "b001" and servidor.backend == "vulkan":
                return AudioOutcome(item_key=request.item_key, failure=classify_audio_failure(
                    "reached max_tokens before EOC", status=500, item_key=request.item_key,
                ))
            return AudioOutcome.succeeded(request.item_key, _wav(Path(output_dir) / f"{request.item_key}.wav"))

    events = []
    result = _executor(tmp_path, RescueClient()).run(
        _snapshot(tmp_path), lambda **event: events.append(event)
    )
    terminal = [event for event in events if event["kind"] in {"item.succeeded", "item.failed"}]

    assert result.gate.approved
    assert sorted((event["kind"], event["payload"]["item_key"]) for event in terminal) == [
        ("item.succeeded", "b001"), ("item.succeeded", "b002")
    ]


def test_reused_output_runs_a_new_valid_item_lifecycle_with_relative_path(tmp_path):
    source = _wav(tmp_path / "runs" / "run-1" / "video" / "audio" / "b001.wav")
    source_hash = __import__("hashlib").sha256(source.read_bytes()).hexdigest()
    prior = Artifact(
        id="prior-audio", run_id="run-1", stage_run_id="old-stage", work_item_id="old-item",
        kind="audio.wav", relative_path="video/audio/b001.wav", sha256=source_hash,
        size_bytes=source.stat().st_size, mime_type="audio/wav", metadata={}, is_current=True,
        created_at="2026-09-13T00:00:00Z",
    )
    events = []
    client = Client()
    result = _executor(tmp_path, client).run(
        _snapshot(tmp_path, reusable_outputs=[{"artifact": prior.model_dump(mode="json"), "input_hash": hash_json({"id": "b001", "secao": "A", "texto": "Primeiro texto."})}]),
        lambda **event: events.append(event),
    )
    reused = [event for event in events if event["payload"].get("item_key") == "b001"]

    assert client.calls == ["b002"]
    assert [event["kind"] for event in reused] == ["item.planned", "item.started", "artifact.created", "item.succeeded"]
    assert reused[2]["payload"]["relative_path"] == "video/audio/b001.wav"
    assert result.current_items == result.total_items == 2


def test_current_succeeded_item_is_not_replanned_or_rerun(tmp_path):
    block = BlocoNarracao(id="b001", secao="A", texto="Primeiro texto.")
    current = WorkItem(
        id="current-b001", stage_run_id="current-stage", item_key="b001", status=ItemStatus.SUCCEEDED,
        input=block.model_dump(mode="json"), input_hash=hash_json({"id": block.id, "secao": block.secao, "texto": block.texto}), attempts=1,
    )
    artifact_path = _wav(tmp_path / "runs" / "run-1" / "video" / "audio" / "b001.wav")
    artifact = Artifact(
        id="current-audio", run_id="run-1", stage_run_id="current-stage", work_item_id=current.id,
        kind="audio.wav", relative_path="video/audio/b001.wav", sha256=__import__("hashlib").sha256(artifact_path.read_bytes()).hexdigest(),
        size_bytes=artifact_path.stat().st_size, mime_type="audio/wav", metadata={}, is_current=True,
        created_at="2026-09-13T00:00:00Z",
    )
    snapshot = _snapshot(tmp_path, work_items=[current]).model_copy(update={"artifacts": [artifact]})
    events = []
    client = Client()

    _executor(tmp_path, client).run(snapshot, lambda **event: events.append(event))

    assert client.calls == ["b002"]
    assert not [event for event in events if event["payload"].get("item_key") == "b001"]


def test_voice_guard_retries_second_alternate_seed_and_records_actual_seed(tmp_path):
    snapshot = _snapshot(tmp_path)
    media = PlanoMidia.model_validate_json((snapshot.run_dir / "video" / "midia.json").read_text())
    media.blocos.extend([
        BlocoNarracao(id="b003", secao="B", texto="Terceiro texto."),
        BlocoNarracao(id="b004", secao="B", texto="Quarto texto."),
        BlocoNarracao(id="b005", secao="B", texto="Quinto texto."),
    ])
    gravar_modelo(snapshot.run_dir / "video" / "midia.json", media)
    events = []
    client = Client()

    result = _executor(tmp_path, client).run(snapshot, lambda **event: events.append(event))

    b002_artifacts = [event["payload"] for event in events if event["kind"] == "artifact.created" and event["payload"].get("item_key") == "b002"]
    assert client.seeds[-2:] == [1042, 2042]
    assert b002_artifacts[-1]["metadata"]["seed"] == 2042
    assert result.gate.approved
