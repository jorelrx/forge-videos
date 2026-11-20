from __future__ import annotations

import json
from pathlib import Path
import wave

from forge.domain.execucao import FailureClass
from forge.executors.audio_generate import AudioGenerateClient, AudioRequest
from forge.infrastructure.config import Settings


def _settings(tmp_path: Path) -> Settings:
    root = tmp_path / "audio-generate"
    return Settings(
        _env_file=None,
        audio_generate_dir=root,
        tts_binary=root / "audio-generate.exe",
        tts_model=root / "model.gguf",
        tts_voice_reference=root / "voice.wav",
    )


def test_build_argv_uses_fixed_safe_batch_flags_and_no_sampling_knobs(tmp_path):
    settings = _settings(tmp_path)
    client = AudioGenerateClient(settings)
    batch_file = tmp_path / "batch.jsonl"

    argv = client.build_argv(batch_file, tmp_path / "out")

    # Contrato verificado contra `audiocpp_cli.exe --help`: --task e --family
    # são obrigatórios, a referência de voz é --voice-ref e a saída é --out-dir.
    assert argv == [
        str(settings.tts_binary),
        "--task", "tts",
        "--family", settings.tts_family,
        "--model", str(settings.tts_model),
        "--backend", settings.tts_backend,
        "--voice-ref", str(settings.tts_voice_reference),
        "--reference-text", settings.tts_reference_text,
        "--batch-text-file", str(batch_file),
        "--out-dir", str(tmp_path / "out"),
        "--seed", "42",
    ]
    assert not {"--temperature", "--top-k", "--top-p"}.intersection(argv)


def test_build_argv_carries_the_mandatory_task_and_family(tmp_path):
    """Sem --task/--family o binário sai 1 sem gerar áudio."""
    argv = AudioGenerateClient(_settings(tmp_path)).build_argv(
        tmp_path / "batch.jsonl", tmp_path / "out"
    )

    assert "--task" in argv and argv[argv.index("--task") + 1] == "tts"
    assert "--family" in argv and argv[argv.index("--family") + 1]
    assert "--voice-ref" in argv
    assert "--out-dir" in argv


def test_build_argv_requests_a_batch_manifest(tmp_path):
    """O nome do WAV é `line_<N>`: o manifest é a única fonte do mapeamento."""
    argv = AudioGenerateClient(_settings(tmp_path)).build_argv(
        tmp_path / "batch.jsonl", tmp_path / "out", manifest_path=tmp_path / "m.json"
    )

    assert "--batch-manifest-out" in argv
    assert argv[argv.index("--batch-manifest-out") + 1] == str(tmp_path / "m.json")


def test_synthesize_batch_maps_outputs_through_the_manifest(tmp_path):
    """O binário ignora o id do pedido e grava `line_<N>.wav`; o manifesto
    devolve esse nome na ordem das linhas. Sem lê-lo, o adaptador anunciaria
    caminhos que não existem."""
    captured = {}

    def run(argv, **kwargs):
        captured["argv"] = argv
        out = Path(argv[argv.index("--out-dir") + 1])
        out.mkdir(parents=True, exist_ok=True)
        manifest = Path(argv[argv.index("--batch-manifest-out") + 1])
        for index in (1, 2):
            (out / f"line_{index}.wav").write_bytes(b"RIFF ok")
        manifest.write_text(
            json.dumps(
                {
                    "requests": [
                        {"id": "line_1", "sample_rate": 24000, "channels": 1, "samples": 10},
                        {"id": "line_2", "sample_rate": 24000, "channels": 1, "samples": 20},
                    ],
                    "chapters": [],
                }
            ),
            encoding="utf-8",
        )
        return type("Result", (), {"returncode": 0, "stderr": ""})()

    client = AudioGenerateClient(_settings(tmp_path), run=run)
    outcomes = client.synthesize_batch(
        [AudioRequest("b001", "Primeira"), AudioRequest("b002", "Segunda")],
        tmp_path / "out",
    )

    assert [outcome.ok for outcome in outcomes] == [True, True]
    assert outcomes[0].path == tmp_path / "out" / "b001.wav"
    assert outcomes[1].path == tmp_path / "out" / "b002.wav"


def test_synthesize_batch_fails_when_the_manifest_does_not_cover_every_item(tmp_path):
    """Manifesto curto não vira sucesso silencioso: item sem arquivo falha."""

    def run(argv, **kwargs):
        out = Path(argv[argv.index("--out-dir") + 1])
        out.mkdir(parents=True, exist_ok=True)
        (out / "line_1.wav").write_bytes(b"RIFF ok")
        Path(argv[argv.index("--batch-manifest-out") + 1]).write_text(
            json.dumps({"requests": [{"id": "line_1"}], "chapters": []}),
            encoding="utf-8",
        )
        return type("Result", (), {"returncode": 0, "stderr": ""})()

    client = AudioGenerateClient(_settings(tmp_path), run=run)
    outcomes = client.synthesize_batch(
        [AudioRequest("b001", "Primeira"), AudioRequest("b002", "Segunda")],
        tmp_path / "out",
    )

    assert outcomes[0].ok
    assert not outcomes[1].ok
    assert outcomes[1].failure is not None
    assert outcomes[1].failure.code == "tts_output_missing"


def test_synthesize_batch_fails_when_a_manifest_entry_has_no_file(tmp_path):
    """Manifesto que anuncia um áudio ausente é falha, não sucesso."""

    def run(argv, **kwargs):
        out = Path(argv[argv.index("--out-dir") + 1])
        out.mkdir(parents=True, exist_ok=True)
        Path(argv[argv.index("--batch-manifest-out") + 1]).write_text(
            json.dumps({"requests": [{"id": "line_1"}], "chapters": []}),
            encoding="utf-8",
        )
        return type("Result", (), {"returncode": 0, "stderr": ""})()

    client = AudioGenerateClient(_settings(tmp_path), run=run)
    outcomes = client.synthesize_batch([AudioRequest("b001", "Primeira")], tmp_path / "out")

    assert not outcomes[0].ok
    assert outcomes[0].failure is not None
    assert outcomes[0].failure.code == "tts_output_missing"


def test_synthesize_batch_serializes_plain_text_without_emotion_tags(tmp_path):
    captured = {}

    def run(argv, **kwargs):
        captured["argv"] = argv
        captured.update(kwargs)
        out = Path(argv[argv.index("--out-dir") + 1])
        out.mkdir(parents=True, exist_ok=True)
        (out / "line_1.wav").write_bytes(b"RIFF ok")
        Path(argv[argv.index("--batch-manifest-out") + 1]).write_text(
            json.dumps({"requests": [{"id": "line_1"}], "chapters": []}),
            encoding="utf-8",
        )
        return type("Result", (), {"returncode": 0, "stderr": ""})()

    client = AudioGenerateClient(_settings(tmp_path), run=run)
    outcomes = client.synthesize_batch(
        [AudioRequest("b001", "Olá <|emotion:angry|> mundo")], tmp_path / "out"
    )

    assert outcomes[0].ok
    batch_text = Path(captured["argv"][captured["argv"].index("--batch-text-file") + 1]).read_text(encoding="utf-8")
    assert "<|emotion:" not in batch_text
    assert batch_text == "Olá  mundo\n"
    assert captured["shell"] is False
    assert captured["cwd"] == tmp_path / "audio-generate"
    assert captured["timeout"] == 900


def test_lotes_diferentes_preservam_audios_anteriores(tmp_path):
    raw_dirs = []

    def run(argv, **kwargs):
        raw = Path(argv[argv.index("--out-dir") + 1])
        raw_dirs.append(raw)
        raw.mkdir(parents=True, exist_ok=True)
        (raw / "line_1.wav").write_bytes(f"lote-{len(raw_dirs)}".encode())
        Path(argv[argv.index("--batch-manifest-out") + 1]).write_text(
            json.dumps({"requests": [{"id": "line_1"}]}), encoding="utf-8",
        )
        return type("Result", (), {"returncode": 0, "stderr": ""})()

    client = AudioGenerateClient(_settings(tmp_path), run=run)
    first = client.synthesize_batch([AudioRequest("b001", "Primeira")], tmp_path / "out")[0]
    second = client.synthesize_batch([AudioRequest("b002", "Segunda")], tmp_path / "out")[0]
    assert first.path.read_bytes() == b"lote-1"
    assert second.path.read_bytes() == b"lote-2"
    assert raw_dirs[0] != raw_dirs[1]


def test_synthesize_batch_classifies_known_stderr_and_bounds_diagnostics(tmp_path):
    stderr = "x" * 5000 + "ggml_vulkan: Device memory allocation"

    def run(*args, **kwargs):
        return type("Result", (), {"returncode": 1, "stderr": stderr})()

    outcome = AudioGenerateClient(_settings(tmp_path), run=run).synthesize_batch(
        [AudioRequest("b001", "Texto")], tmp_path / "out"
    )[0]

    assert outcome.failure is not None
    assert outcome.failure.code == "tts_vulkan_oom"
    assert outcome.failure.failure_class is FailureClass.CAPACITY
    assert len(outcome.stderr) == 4096


def test_synthesize_batch_classifies_max_tokens_as_deterministic(tmp_path):
    def run(*args, **kwargs):
        return type("Result", (), {"returncode": 1, "stderr": "reached max_tokens before EOC"})()

    outcome = AudioGenerateClient(_settings(tmp_path), run=run).synthesize_batch(
        [AudioRequest("b001", "Texto")], tmp_path / "out"
    )[0]

    assert outcome.failure is not None
    assert outcome.failure.code == "tts_max_tokens_before_eoc"
    assert outcome.failure.failure_class is FailureClass.DETERMINISTIC
    assert outcome.failure.retriable is False


def test_failed_batch_preserves_completed_lines_and_maps_unfinished_items(tmp_path):
    def run(argv, **kwargs):
        out = Path(argv[argv.index("--out-dir") + 1])
        out.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out / "line_1.wav"), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(24000)
            output.writeframes(b"\0\0" * 2400)
        return type("Result", (), {
            "returncode": 1,
            "stderr": "Higgs TTS generation reached max_tokens before EOC",
        })()

    outcomes = AudioGenerateClient(_settings(tmp_path), run=run).synthesize_batch(
        [AudioRequest("b001", "Primeira"), AudioRequest("b002", "Segunda"), AudioRequest("b003", "Terceira")],
        tmp_path / "out",
    )

    assert outcomes[0].ok
    assert outcomes[0].path == tmp_path / "out" / "b001.wav"
    assert [outcome.item_key for outcome in outcomes[1:]] == ["b002", "b003"]
    assert [outcome.failure.code for outcome in outcomes[1:]] == [
        "tts_max_tokens_before_eoc", "tts_max_tokens_before_eoc",
    ]


def test_single_failed_line_is_not_accepted_as_completed_partial_audio(tmp_path):
    def run(argv, **kwargs):
        out = Path(argv[argv.index("--out-dir") + 1])
        out.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out / "line_1.wav"), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(24000)
            output.writeframes(b"\0\0" * 2400)
        return type("Result", (), {
            "returncode": 1,
            "stderr": "Higgs TTS generation reached max_tokens before EOC",
        })()

    outcome = AudioGenerateClient(_settings(tmp_path), run=run).synthesize_batch(
        [AudioRequest("b002", "Segunda")], tmp_path / "out",
    )[0]

    assert not outcome.ok
    assert outcome.failure is not None
    assert outcome.failure.code == "tts_max_tokens_before_eoc"


def test_synthesize_batch_can_override_backend_for_one_call(tmp_path):
    captured = {}

    def run(argv, **kwargs):
        captured["backend"] = argv[argv.index("--backend") + 1]
        out = Path(argv[argv.index("--out-dir") + 1])
        out.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out / "line_1.wav"), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(24000)
            output.writeframes(b"\0\0" * 2400)
        Path(argv[argv.index("--batch-manifest-out") + 1]).write_text(
            json.dumps({"requests": [{"id": "line_1"}]}), encoding="utf-8",
        )
        return type("Result", (), {"returncode": 0, "stderr": ""})()

    settings = _settings(tmp_path)
    client = AudioGenerateClient(settings, run=run)
    outcome = client.synthesize_batch(
        [AudioRequest("b002", "Segunda")], tmp_path / "out", backend="cpu",
    )[0]

    assert outcome.ok
    assert captured["backend"] == "cpu"
    assert settings.tts_backend == "vulkan"
