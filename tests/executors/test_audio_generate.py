from __future__ import annotations

from pathlib import Path

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

    assert argv == [
        str(settings.tts_binary), "--model", str(settings.tts_model),
        "--voice-reference", str(settings.tts_voice_reference),
        "--batch-text-file", str(batch_file), "--output-dir", str(tmp_path / "out"),
        "--seed", "42",
    ]
    assert not {"--temperature", "--top-k", "--top-p"}.intersection(argv)


def test_synthesize_batch_serializes_plain_text_without_emotion_tags(tmp_path):
    captured = {}

    def run(argv, **kwargs):
        captured["argv"] = argv
        captured.update(kwargs)
        out = Path(argv[argv.index("--output-dir") + 1])
        out.mkdir(parents=True, exist_ok=True)
        (out / "b001.wav").write_bytes(b"RIFF ok")
        return type("Result", (), {"returncode": 0, "stderr": ""})()

    client = AudioGenerateClient(_settings(tmp_path), run=run)
    outcomes = client.synthesize_batch(
        [AudioRequest("b001", "Olá <|emotion:angry|> mundo")], tmp_path / "out"
    )

    assert outcomes[0].ok
    batch_text = Path(captured["argv"][captured["argv"].index("--batch-text-file") + 1]).read_text(encoding="utf-8")
    assert "<|emotion:" not in batch_text
    assert captured["shell"] is False
    assert captured["cwd"] == tmp_path / "audio-generate"
    assert captured["timeout"] == 900


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
