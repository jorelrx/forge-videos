from __future__ import annotations


def test_pitch_tracks_fundamental_when_upper_harmonics_dominate(tmp_path):
    import numpy as np
    import soundfile as sf
    from forge.executors.audio import AudioExecutor

    rate = 24000
    time = np.arange(rate, dtype=np.float64) / rate
    fundamental = 150.0
    plain = 0.5 * np.sin(2 * np.pi * fundamental * time)
    bright = 0.1 * np.sin(2 * np.pi * fundamental * time)
    bright += 0.5 * np.sin(2 * np.pi * fundamental * 5 * time)
    for name, samples in (("plain", plain), ("bright", bright)):
        path = tmp_path / f"{name}.wav"
        sf.write(path, samples, rate)
        measured = AudioExecutor._f0(path, rate)
        assert abs(measured - fundamental) < 3, (name, measured)


def test_pitch_reports_zero_for_silence(tmp_path):
    import numpy as np
    import soundfile as sf
    from forge.executors.audio import AudioExecutor

    path = tmp_path / "silence.wav"
    sf.write(path, np.zeros(24000), 24000)
    assert AudioExecutor._f0(path, 24000) == 0.0


def test_voice_gate_accepts_small_pitch_variation_but_flags_octave_change():
    from types import SimpleNamespace
    from forge.executors.audio import AudioExecutor

    executor = AudioExecutor(settings=Settings(_env_file=None))
    samples = {str(index): SimpleNamespace(metadata={"F0": pitch})
               for index, pitch in enumerate([130, 132, 134, 136, 145])}
    assert executor._voice_outlier_keys(samples) == []
    samples["other_voice"] = SimpleNamespace(metadata={"F0": 268})
    assert executor._voice_outlier_keys(samples) == ["other_voice"]

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


def test_tts_request_receives_only_spoken_text(tmp_path):
    from forge.domain.execucao import WorkItemPlan

    item = WorkItemPlan(
        item_key="b001",
        input={"texto": "fala", "referencias": ["12/ch1/p2"], "prompt_visual": "imagem"},
        input_hash="a" * 64,
    )
    request = AudioExecutor._request(item)
    assert request.text == "fala"
    assert not hasattr(request, "referencias")
    assert not hasattr(request, "prompt_visual")


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


@pytest.mark.parametrize("cpu_succeeds", [True, False])
def test_max_tokens_isolates_only_failed_item_and_uses_cpu_once(tmp_path, cpu_succeeds):
    from forge.executors.audio_generate import classify_audio_failure

    class DeviceClient:
        def __init__(self):
            self.calls = []

        def synthesize_batch(self, items, output_dir, *, backend=None):
            keys = [item.item_key for item in items]
            self.calls.append((keys, backend or "vulkan"))
            outcomes = []
            for item in items:
                path = output_dir / f"{item.item_key}.wav"
                if len(items) > 1 and item.item_key == "b001":
                    _wav(path)
                    outcomes.append(AudioOutcome.succeeded(item.item_key, path))
                elif len(items) > 1 or (item.item_key == "b002" and backend != "cpu"):
                    failure = classify_audio_failure(
                        "Higgs TTS generation reached max_tokens before EOC",
                        exit_code=1, item_key=item.item_key,
                    )
                    outcomes.append(AudioOutcome(item.item_key, failure=failure))
                elif item.item_key == "b002" and backend == "cpu" and not cpu_succeeds:
                    failure = classify_audio_failure(
                        "Higgs TTS generation reached max_tokens before EOC",
                        exit_code=1, item_key=item.item_key,
                    )
                    outcomes.append(AudioOutcome(item.item_key, failure=failure))
                else:
                    _wav(path)
                    outcomes.append(AudioOutcome.succeeded(item.item_key, path))
            return outcomes

    client, events = DeviceClient(), []
    executor = AudioExecutor(
        settings=_settings(tmp_path, tts_batch_size=3), client=client, broker=Broker()
    )

    result = executor.run(_snapshot(tmp_path), lambda **event: events.append(event))

    # CPU que também estoura tenta as sementes alternativas antes de desistir.
    cpu_calls = 1 if cpu_succeeds else 3
    assert client.calls == [
        (["b001", "b002", "b003"], "vulkan"),
        (["b002"], "vulkan"),
        *[(["b002"], "cpu")] * cpu_calls,
        (["b003"], "vulkan"),
    ]
    assert result.current_items == 2 + int(cpu_succeeds)
    cpu_starts = [event for event in events if event["kind"] == "audio.recovery.started"]
    assert len(cpu_starts) == 1
    assert cpu_starts[0]["payload"]["item_key"] == "b002"
    assert cpu_starts[0]["payload"]["backend"] == "cpu"
    assert cpu_starts[0]["payload"]["fallback_from"] == "vulkan"
    assert cpu_starts[0]["payload"]["original_failure_code"] == "tts_max_tokens_before_eoc"
    assert "reached max_tokens before EOC" in cpu_starts[0]["payload"]["original_failure_stderr"]
    assert ("b003", "vulkan") in [(keys[0], backend) for keys, backend in client.calls if len(keys) == 1]
    if not cpu_succeeds:
        failed = [event for event in events if event["kind"] == "item.failed"]
        assert len(failed) == 1
        assert failed[0]["payload"]["item_key"] == "b002"
        assert failed[0]["payload"]["fallback_backend"] == "cpu"
        assert failed[0]["payload"]["original_failure_code"] == "tts_max_tokens_before_eoc"
        assert "reached max_tokens before EOC" in failed[0]["payload"]["original_failure_stderr"]
        completed = [event for event in events if event["kind"] == "audio.recovery.completed"]
        assert len(completed) == 1
        assert completed[0]["payload"]["status"] == "failed"
        assert completed[0]["payload"]["cpu_failure_code"] == "tts_max_tokens_before_eoc"


def test_max_tokens_na_cpu_troca_a_semente_antes_de_desistir(tmp_path):
    """Semente fixa repete a mesma geração sem fim: só outra semente destrava."""
    from forge.executors.audio_generate import classify_audio_failure

    class SeedClient:
        def __init__(self):
            self.calls = []

        def synthesize_batch(self, items, output_dir, *, backend=None):
            outcomes = []
            for item in items:
                self.calls.append((item.item_key, backend or "vulkan", item.seed))
                path = output_dir / f"{item.item_key}.wav"
                if item.item_key == "b002" and item.seed != 1042:
                    failure = classify_audio_failure(
                        "Higgs TTS generation reached max_tokens before EOC",
                        exit_code=1, item_key=item.item_key,
                    )
                    outcomes.append(AudioOutcome(item.item_key, failure=failure))
                else:
                    _wav(path)
                    outcomes.append(AudioOutcome.succeeded(item.item_key, path))
            return outcomes

    client, events = SeedClient(), []
    executor = AudioExecutor(
        settings=_settings(tmp_path, tts_batch_size=1), client=client, broker=Broker()
    )

    result = executor.run(_snapshot(tmp_path), lambda **event: events.append(event))

    assert [call for call in client.calls if call[0] == "b002"] == [
        ("b002", "vulkan", None), ("b002", "cpu", None), ("b002", "cpu", 1042),
    ]
    assert result.current_items == result.total_items == 3
    assert result.gate.approved
    criado = next(
        e for e in events
        if e["kind"] == "artifact.created" and e["payload"]["item_key"] == "b002"
    )
    assert criado["payload"]["metadata"]["seed"] == 1042
    assert not [e for e in events if e["kind"] == "item.failed"]


def test_non_retriable_max_tokens_is_not_retried_when_cpu_is_primary(tmp_path):
    from forge.executors.audio_generate import classify_audio_failure

    class CpuClient:
        def __init__(self):
            self.calls = []

        def synthesize_batch(self, items, output_dir):
            self.calls.append([item.item_key for item in items])
            return [AudioOutcome(
                item_key=item.item_key,
                failure=classify_audio_failure(
                    "Higgs TTS generation reached max_tokens before EOC",
                    exit_code=1, item_key=item.item_key,
                ),
            ) for item in items]

    client, events = CpuClient(), []
    executor = AudioExecutor(
        settings=_settings(tmp_path, tts_backend="cpu", tts_batch_size=3),
        client=client, broker=Broker(),
    )

    result = executor.run(_snapshot(tmp_path), lambda **event: events.append(event))

    assert client.calls == [["b001", "b002", "b003"]]
    assert result.current_items == 0
    failures = [event for event in events if event["kind"] == "item.failed"]
    assert [event["payload"]["item_key"] for event in failures] == ["b001", "b002", "b003"]


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
            input_hash=hash_json({"id": "b001", "secao": "A", "texto": "Primeiro texto."}),
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


# --- silêncio longo dentro de um bloco ---

def _fala(path: Path, *, silencio: float = 0.0, rate: int = 24000) -> None:
    """Tom de 1 s, `silencio` segundos mudos, tom de 1 s."""
    import math
    import struct

    path.parent.mkdir(parents=True, exist_ok=True)
    tom = [int(9000 * math.sin(2 * math.pi * 200 * i / rate)) for i in range(rate)]
    amostras = tom + [0] * int(silencio * rate) + tom
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(struct.pack(f"<{len(amostras)}h", *amostras))


class _ClienteComBuraco:
    """b002 sai com 5 s mudos no meio, a menos que a semente esteja em `curam`."""

    def __init__(self, curam=()):
        self.curam = set(curam)
        self.calls = []

    def synthesize_batch(self, items, output_dir, *, backend=None):
        outcomes = []
        for item in items:
            self.calls.append((item.item_key, item.seed))
            path = output_dir / f"{item.item_key}.wav"
            buraco = item.item_key == "b002" and item.seed not in self.curam
            _fala(path, silencio=5.0 if buraco else 0.3)
            outcomes.append(AudioOutcome.succeeded(item.item_key, path))
        return outcomes


def test_bloco_com_silencio_longo_e_regenerado_com_outra_semente(tmp_path):
    """O TTS às vezes trava mudo no meio da frase; só a validação final via."""
    client, events = _ClienteComBuraco(curam={1042}), []
    executor = AudioExecutor(
        settings=_settings(tmp_path, tts_batch_size=3), client=client, broker=Broker()
    )

    result = executor.run(_snapshot(tmp_path), lambda **event: events.append(event))

    assert client.calls[-1] == ("b002", 1042)
    assert result.gate.approved
    final = next(a for a in result.artifacts if a.item_key == "b002")
    assert final.metadata["seed"] == 1042
    assert final.metadata["silencio_max"] < 1.0


def test_silencio_longo_que_nenhuma_semente_cura_reprova_o_audio(tmp_path):
    client = _ClienteComBuraco()
    executor = AudioExecutor(
        settings=_settings(tmp_path, tts_batch_size=3), client=client, broker=Broker()
    )

    result = executor.run(_snapshot(tmp_path), lambda **event: None)

    assert [seed for key, seed in client.calls if key == "b002"] == [None, 1042, 2042]
    assert not result.gate.approved
    achado = next(f for f in result.gate.findings if f.code == "audio_silence")
    assert achado.item_key == "b002"
    assert achado.details["silencio_max"] > 4.5
