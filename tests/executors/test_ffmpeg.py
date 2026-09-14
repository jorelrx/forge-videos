from __future__ import annotations

import pytest

from forge.executors.ffmpeg import (
    MediaProbe,
    build_ken_burns_filter,
    concat_files,
    probe_media,
    run_ffmpeg,
)


def test_ken_burns_filter_scales_before_zoom_and_outputs_1080p():
    value = build_ken_burns_filter(seconds=12.0, index=0, portrait=False)
    assert value.index("scale=7680:4320") < value.index("zoompan=")
    assert "s=1920x1080" in value
    assert "format=yuv420p" in value


def test_concat_list_escapes_single_quotes_without_shell(tmp_path):
    path = tmp_path / "image's clip.mp4"
    path.write_bytes(b"dummy")
    list_path = tmp_path / "list.txt"
    concat_files([path], list_path)
    text = list_path.read_text(encoding="utf-8")
    # The concat file uses single-quote escaping; verify no bare single quote leaks.
    assert text.startswith("file '")
    # Verify escaped quote appears correctly: image'\\''s
    assert "image'\\''s clip.mp4" in text


def test_run_ffmpeg_uses_argv_list_without_a_shell(monkeypatch):
    """Sem shell: um caminho com espaço não pode virar dois argumentos."""
    captured: dict = {}

    class Result:
        returncode = 0
        stdout = b""
        stderr = b""

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured.update(kwargs)
        return Result()

    monkeypatch.setattr("forge.executors.ffmpeg.subprocess.run", fake_run)

    code, stderr, _ = run_ffmpeg(["ffmpeg", "-i", "imagem com espaço.png", "out.mp4"])

    assert code == 0
    assert stderr == ""
    assert captured["argv"] == ["ffmpeg", "-i", "imagem com espaço.png", "out.mp4"]
    assert captured["shell"] is False
    assert captured["capture_output"] is True


def test_run_ffmpeg_bounds_and_decodes_stderr():
    """stderr de ffmpeg é enorme e pode não ser UTF-8; o tail precisa vir inteiro."""
    grande = ("x" * 5000).encode("utf-8") + b"\xff\xfe"

    class Result:
        returncode = 1
        stdout = b""
        stderr = grande

    import forge.executors.ffmpeg as modulo

    original = modulo.subprocess.run
    modulo.subprocess.run = lambda argv, **kwargs: Result()
    try:
        code, stderr, _ = run_ffmpeg(["ffmpeg"], capture_stderr_limit=64)
    finally:
        modulo.subprocess.run = original

    assert code == 1
    assert len(stderr.encode("utf-8", errors="replace")) <= 70


def test_probe_media_struct_exists():
    probe = MediaProbe(
        codec="h264",
        audio_codec="aac",
        width=1920,
        height=1080,
        duration=10.5,
        has_video_stream=True,
        has_audio_stream=True,
    )
    assert probe.codec == "h264"
    assert probe.audio_codec == "aac"
    assert probe.width == 1920
    assert probe.height == 1080
    assert probe.duration == 10.5
    assert probe.has_video_stream is True
    assert probe.has_audio_stream is True
