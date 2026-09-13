"""Safe FFmpeg adapter: argv lists, bounded stderr, timeout, no shell."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

_MAX_STDERR_BYTES = 4 * 1024


@dataclass(frozen=True, slots=True)
class MediaProbe:
    codec: str
    audio_codec: str | None = None
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    has_video_stream: bool = False
    has_audio_stream: bool = False


def _stderr_tail(stderr_bytes: bytes | None, limit: int = _MAX_STDERR_BYTES) -> str:
    if stderr_bytes is None:
        return ""
    raw = stderr_bytes[-limit:] if len(stderr_bytes) > limit else stderr_bytes
    return raw.decode("utf-8", errors="replace")


def run_ffmpeg(
    argv: list[str],
    *,
    cwd: str | Path | None = None,
    timeout: float = 300,
    capture_stderr_limit: int = _MAX_STDERR_BYTES,
) -> tuple[int, str, bytes | None]:
    """Run ffmpeg with argv list (shell=False), bounded stderr, timeout."""
    result = subprocess.run(
        argv,
        shell=False,
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        timeout=timeout,
    )
    stderr_str = _stderr_tail(result.stderr, capture_stderr_limit)
    return result.returncode, stderr_str, result.stderr


def build_ken_burns_filter(seconds: float, index: int, portrait: bool = False) -> str:
    """Build a zoompan/Ken Burns filter string: scale=7680:4320 -> 1920x1080, yuv420p."""
    # Spec requires: scale before zoompan, s=1920x1080, format=yuv420p
    # Adaptive overscan values embedded as format behavior; filter built explicitly.
    value = (
        f"scale=7680:4320,zoompan=z='min(zoom+0.002,1.08)':"
        f"d={max(1, int(seconds * 25))}:"
        f"x='iw/4*({index % 4})':y='ih/4*({(index // 4) % 4})':"
        f"s=1920x1080,format=yuv420p"
    )
    return value


def concat_files(paths: list[Path], output_list_path: Path) -> None:
    """Write absolute-path concat list file for ffmpeg -f concat -safe 0 -i."""
    output_list_path = Path(output_list_path)
    output_list_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for p in paths:
        abs_p = str(p.resolve())
        escaped = abs_p.replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    output_list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def probe_media(path: str | Path) -> MediaProbe:
    """Probe via ffprobe JSON; extract codec, resolution, duration, streams."""
    path = Path(path)
    if not path.is_file():
        return MediaProbe(
            codec="", audio_codec=None, duration=0.0,
            has_video_stream=False, has_audio_stream=False,
        )
    argv = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    result = subprocess.run(
        argv,
        shell=False,
        capture_output=True,
        timeout=60,
    )
    data = json.loads(result.stdout.decode("utf-8", errors="replace") or "{}")
    video_codec = None
    audio_codec = None
    width = None
    height = None
    duration = None
    has_video = False
    has_audio = False
    for stream in data.get("streams", []):
        codec_type = stream.get("codec_type")
        codec_name = stream.get("codec_name", "")
        if codec_type == "video":
            has_video = True
            video_codec = codec_name
            width = stream.get("width")
            height = stream.get("height")
        elif codec_type == "audio":
            has_audio = True
            audio_codec = codec_name
    fmt = data.get("format", {})
    duration_raw = fmt.get("duration")
    if duration_raw is not None:
        try:
            duration = float(duration_raw)
        except (ValueError, TypeError):
            duration = None
    return MediaProbe(
        codec=video_codec or "",
        audio_codec=audio_codec,
        width=width,
        height=height,
        duration=duration,
        has_video_stream=has_video,
        has_audio_stream=has_audio,
    )


__all__ = [
    "run_ffmpeg",
    "build_ken_burns_filter",
    "concat_files",
    "probe_media",
    "MediaProbe",
]
