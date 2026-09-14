"""Adaptador de FFmpeg: argv sem shell, stderr limitado, timeout e Ken Burns.

Regras de acabamento descobertas por inspeção de frame renderizado — cada uma
corrige um defeito real:

1. `scale=W:-1` sozinho deixa BARRA PRETA quando a proporção da fonte difere de
   16:9; por isso o `scale` usa `force_original_aspect_ratio=increase` e um
   `crop` descarta o excedente.
2. O overscan come a moldura da obra fotografada, que apareceria como borda
   escura no quadro.
3. `zoompan` opera na resolução de ENTRADA: com entrada 1080p o zoom pixeliza.
   Escala para 7680 antes e deixa o zoompan reduzir para 1920.
4. `d=` do zoompan conta FRAMES, não segundos.
5. Alternar a direção do movimento entre clipes evita a monotonia que denuncia
   vídeo automático.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

_MAX_STDERR_BYTES = 4 * 1024

FPS = 24
LARGURA, ALTURA = 1920, 1080
# Resolução intermediária: sem ela o zoompan amplia pixels da fonte.
FONTE_LARGA = 7680
OVERSCAN = 0.94          # paisagem: come a moldura da obra
OVERSCAN_RETRATO = 0.86  # retrato precisa perder mais para não mostrar moldura
FADE_PADRAO = 0.5
RETRATO_LIMITE = 1.25    # largura/altura abaixo disto é retrato


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
    """Executa ffmpeg com argv (shell=False), stderr limitado e timeout."""
    result = subprocess.run(
        argv,
        shell=False,
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        timeout=timeout,
    )
    stderr_str = _stderr_tail(result.stderr, capture_stderr_limit)
    return result.returncode, stderr_str, result.stderr


def concat_files(paths: list[Path], output_list_path: Path) -> None:
    """Escreve a lista de concat com caminhos absolutos para `-f concat -safe 0`."""
    output_list_path = Path(output_list_path)
    output_list_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for path in paths:
        absolute = str(Path(path).resolve())
        escaped = absolute.replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    output_list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _ffprobe_json(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ],
        shell=False,
        capture_output=True,
        timeout=60,
    )
    return json.loads(result.stdout.decode("utf-8", errors="replace") or "{}")


def probe_media(path: str | Path) -> MediaProbe:
    """Probe via ffprobe JSON: codec, resolução, duração e streams."""
    path = Path(path)
    if not path.is_file():
        return MediaProbe(
            codec="", audio_codec=None, duration=0.0,
            has_video_stream=False, has_audio_stream=False,
        )
    data = _ffprobe_json(path)
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


def probe_duration(path: str | Path, *, timeout: float = 60) -> float:
    """Duração em segundos; 0.0 quando o arquivo não tem áudio/vídeo legível."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", str(path),
        ],
        shell=False,
        capture_output=True,
        timeout=timeout,
    )
    texto = result.stdout.decode("utf-8", errors="replace").strip()
    try:
        return float(texto)
    except ValueError:
        return 0.0


def image_aspect(path: str | Path, *, timeout: float = 60) -> float:
    """largura/altura da imagem. 1.33 = paisagem 4:3, 0.75 = retrato 3:4."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x",
            str(path),
        ],
        shell=False,
        capture_output=True,
        timeout=timeout,
    )
    try:
        largura, altura = result.stdout.decode("utf-8", errors="replace").strip().split("x")
        return int(largura) / int(altura)
    except (ValueError, ZeroDivisionError):
        return 1.33


def ken_burns_motion(index: int, frames: int, ceiling: float = 1.22) -> str:
    """Alterna o movimento para o vídeo não parecer um slideshow automático.

    `ceiling` menor em retrato: a obra já perdeu 14% no overscan, e um zoom de
    1.22 em cima disso fecha no meio do rosto.
    """
    modos = [
        # zoom in lento, centro
        f"z='min(zoom+0.0005,{ceiling})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
        # zoom out a partir do teto
        f"z='if(lte(zoom,1.0),{ceiling},max(1.001,zoom-0.0005))'"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
        # pan lateral com zoom leve
        f"z='min(zoom+0.0003,{min(ceiling, 1.15)})'"
        f":x='iw/2-(iw/zoom/2)+(on/{frames})*180'"
        f":y='ih/2-(ih/zoom/2)'",
        # pan vertical descendo
        f"z='min(zoom+0.0003,{min(ceiling, 1.15)})':x='iw/2-(iw/zoom/2)'"
        f":y='ih/2-(ih/zoom/2)+(on/{frames})*140'",
    ]
    return modos[index % len(modos)]


def build_ken_burns_filter(
    seconds: float, index: int, portrait: bool = False, *, fade: float = FADE_PADRAO
) -> str:
    """Cadeia completa de um clipe: overscan, escala, zoompan, fades, yuv420p."""
    frames = max(1, int(round(seconds * FPS)))
    over = OVERSCAN_RETRATO if portrait else OVERSCAN
    movimento = ken_burns_motion(index, frames, ceiling=1.10 if portrait else 1.22)
    return (
        f"crop=in_w*{over}:in_h*{over},"
        f"scale={FONTE_LARGA}:{FONTE_LARGA * 9 // 16}"
        f":force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={FONTE_LARGA}:{FONTE_LARGA * 9 // 16},"
        f"zoompan={movimento}:d={frames}:s={LARGURA}x{ALTURA}:fps={FPS},"
        f"fade=t=in:st=0:d={fade},"
        f"fade=t=out:st={max(0.0, seconds - fade):.2f}:d={fade},"
        f"format=yuv420p"
    )


def clip_from_image(
    imagem: Path,
    saida: Path,
    *,
    seconds: float,
    index: int,
    portrait: bool,
    runner=run_ffmpeg,
) -> None:
    """Um clipe Ken Burns de `seconds`, 16:9, sem bordas."""
    saida.parent.mkdir(parents=True, exist_ok=True)
    code, stderr, _ = runner(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-loop", "1", "-i", str(imagem),
            "-vf", build_ken_burns_filter(seconds, index, portrait),
            "-t", f"{seconds:.3f}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-r", str(FPS),
            str(saida),
        ],
        timeout=1800,
    )
    if code != 0:
        raise RuntimeError(f"ffmpeg falhou ao gerar clipe ({code}): {stderr[-600:]}")


def concat_videos(clipes: list[Path], saida: Path, lista: Path, *, runner=run_ffmpeg) -> None:
    concat_files(clipes, lista)
    saida.parent.mkdir(parents=True, exist_ok=True)
    code, stderr, _ = runner(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(lista),
            "-c", "copy", str(saida),
        ],
        timeout=1800,
    )
    if code != 0:
        raise RuntimeError(f"ffmpeg falhou ao concatenar vídeo ({code}): {stderr[-600:]}")


def concat_wavs(wavs: list[Path], saida: Path, lista: Path, *, runner=run_ffmpeg) -> None:
    """Concatena a narração por bloco; todos vêm do mesmo TTS, mesmos parâmetros."""
    concat_files(wavs, lista)
    saida.parent.mkdir(parents=True, exist_ok=True)
    code, stderr, _ = runner(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(lista),
            "-c", "copy", str(saida),
        ],
        timeout=1800,
    )
    if code != 0:
        raise RuntimeError(f"ffmpeg falhou ao concatenar áudio ({code}): {stderr[-600:]}")


def mux_audio(video: Path, audio: Path, saida: Path, *, runner=run_ffmpeg) -> None:
    """Anexa a narração ao vídeo mudo, em AAC, cortando no mais curto."""
    saida.parent.mkdir(parents=True, exist_ok=True)
    code, stderr, _ = runner(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(video), "-i", str(audio),
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-map", "0:v:0", "-map", "1:a:0",
            "-shortest", str(saida),
        ],
        timeout=1800,
    )
    if code != 0:
        raise RuntimeError(f"ffmpeg falhou ao anexar áudio ({code}): {stderr[-600:]}")


__all__ = [
    "FPS",
    "LARGURA",
    "ALTURA",
    "MediaProbe",
    "build_ken_burns_filter",
    "clip_from_image",
    "concat_files",
    "concat_videos",
    "concat_wavs",
    "image_aspect",
    "ken_burns_motion",
    "mux_audio",
    "probe_duration",
    "probe_media",
    "run_ffmpeg",
]
