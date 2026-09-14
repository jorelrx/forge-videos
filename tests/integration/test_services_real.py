"""Provas reais contra as dependências da máquina.

Cada teste faz uma chamada de verdade e verifica um efeito observável. Se a
dependência não estiver disponível, o teste SKIPa dizendo o endpoint ou path
exato e a ação para corrigir — nunca passa sem chamar nada.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import wave
from pathlib import Path

import httpx
import pytest

from forge.executors.audio_generate import AudioGenerateClient, AudioRequest
from forge.executors.ffmpeg import probe_media, run_ffmpeg
from forge.gpu.broker import Broker, GPUOcupada
from forge.llms.model import build_chat_model, extract_thinking
from forge.services.acervo import Acervo

from .conftest import require_binary, require_file, require_http

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# 1. research (acervo)
# ---------------------------------------------------------------------------


def test_research_returns_citable_passages(real_settings) -> None:
    require_http(
        f"{real_settings.acervo_url}/health",
        action="Inicie research em C:\\dev\\research",
    )

    acervo = Acervo(real_settings.acervo_url, timeout=30.0)
    passagens = acervo.buscar("livre-arbítrio e determinismo", top=3)

    assert passagens, "acervo no ar mas sem passagens; confira se há livros ingeridos"

    for passagem in passagens:
        assert passagem.path, f"passagem sem path canônico: {passagem}"
        assert passagem.book_title, f"passagem sem book_title: {passagem}"
        assert isinstance(passagem.book_id, int) and passagem.book_id > 0


# ---------------------------------------------------------------------------
# 2. LM Studio
# ---------------------------------------------------------------------------


def test_lm_studio_returns_content(real_settings) -> None:
    require_http(
        f"{real_settings.lm_studio_base_url}/models",
        action="Inicie o servidor LM Studio com um modelo carregado",
    )

    resposta = build_chat_model(real_settings).invoke("Responda somente: FORGE_OK")
    conteudo = getattr(resposta, "content", "")

    assert conteudo and conteudo.strip(), "LM Studio respondeu sem conteúdo"
    # reasoning_content é canal separado: nunca pode virar content.
    pensamento = extract_thinking(resposta)
    if pensamento:
        assert pensamento not in str(conteudo)


# ---------------------------------------------------------------------------
# 3. TTS
# ---------------------------------------------------------------------------


def test_tts_synthesizes_a_real_wav(real_settings, tmp_path: Path) -> None:
    require_file(
        real_settings.resolved_tts_binary, env_var="FORGE_TTS_BINARY"
    )
    require_file(real_settings.resolved_tts_model, env_var="FORGE_TTS_MODEL")
    require_file(
        real_settings.resolved_tts_voice_reference, env_var="FORGE_TTS_VOICE_REFERENCE"
    )
    require_binary("ffprobe", action="Instale FFmpeg e deixe ffprobe no PATH")

    out_dir = tmp_path / "tts"
    client = AudioGenerateClient(real_settings)
    resultados = client.synthesize_batch(
        [AudioRequest(item_key="prova-tts", text="O Forge verifica uma frase curta.")],
        out_dir,
    )

    assert len(resultados) == 1
    resultado = resultados[0]

    if not resultado.ok and resultado.failure is not None:
        if resultado.failure.code == "tts_vulkan_oom":
            pytest.skip(
                "VRAM ocupada: na RX 580 o TTS exige o LLM descarregado "
                "(ordem LLM→TTS). Feche o modelo no LM Studio, rode o pipeline "
                "pelo broker, ou use FORGE_TTS_BACKEND=cpu para esta prova."
            )
    assert resultado.ok, f"TTS falhou: {resultado.failure}"

    # O binário nomeia a saída `line_<N>.wav`; o caminho vem do manifesto.
    caminho = resultado.path
    assert caminho is not None and caminho.is_file(), f"WAV ausente: {caminho}"

    with wave.open(str(caminho), "rb") as wav:
        assert wav.getnchannels() == 1, f"esperado mono, veio {wav.getnchannels()}"
        assert wav.getframerate() == real_settings.tts_sample_rate
        assert wav.getnframes() > 0, "WAV vazio"


# ---------------------------------------------------------------------------
# 5. FFmpeg — sempre executa os binários, nunca uma fixture textual
# ---------------------------------------------------------------------------


def test_ffmpeg_produces_1080p_h264_aac(real_settings, tmp_path: Path) -> None:
    require_binary("ffmpeg", action="Instale FFmpeg e deixe ffmpeg no PATH")
    require_binary("ffprobe", action="Instale FFmpeg e deixe ffprobe no PATH")

    wav = tmp_path / "tom.wav"
    code, stderr, _ = run_ffmpeg(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-ac", "1", "-ar", "24000", str(wav),
        ],
        timeout=120,
    )
    assert code == 0, f"ffmpeg não gerou o WAV: {stderr}"

    png = tmp_path / "quadro.png"
    code, stderr, _ = run_ffmpeg(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=1024x576:d=1",
            "-frames:v", "1", str(png),
        ],
        timeout=120,
    )
    assert code == 0, f"ffmpeg não gerou o PNG: {stderr}"

    mp4 = tmp_path / "final.mp4"
    code, stderr, _ = run_ffmpeg(
        [
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(png),
            "-i", str(wav),
            "-vf", "scale=1920:1080,format=yuv420p",
            "-c:v", "libx264", "-c:a", "aac", "-shortest",
            "-pix_fmt", "yuv420p",
            str(mp4),
        ],
        timeout=300,
    )
    assert code == 0, f"ffmpeg não compôs o MP4: {stderr}"
    assert mp4.is_file() and mp4.stat().st_size > 0

    probe = probe_media(mp4)
    assert probe.has_video_stream and probe.has_audio_stream
    assert probe.codec == "h264", f"codec de vídeo: {probe.codec}"
    assert probe.audio_codec == "aac", f"codec de áudio: {probe.audio_codec}"
    assert (probe.width, probe.height) == (1920, 1080), f"{probe.width}x{probe.height}"
    assert probe.duration and probe.duration > 0, f"duração: {probe.duration}"


# ---------------------------------------------------------------------------
# 6. broker — um residente por vez, com liberadores no-op locais
# ---------------------------------------------------------------------------

_CHILD_PROGRAM = """
import sys, time
from pathlib import Path
from forge.gpu.broker import Broker

base = Path(sys.argv[1])
broker = Broker(
    lock_path=base / "gpu.lock",
    estado_path=base / "residente.json",
    liberadores={"llm": lambda: None, "tts": lambda: None, "imagem": lambda: None},
    timeout_lock=30.0,
)
with broker.exclusivo("tts"):
    (base / "ready").write_text("1", encoding="utf-8")
    time.sleep(2.0)
"""


def _local_broker(base: Path, *, timeout_lock: float) -> Broker:
    """Broker sobre tmp_path com liberadores no-op.

    Nunca usa `output/.gpu.lock` nem os liberadores reais: o teste não pode
    encerrar um LM Studio, ComfyUI ou TTS que o operador subiu à mão.
    """
    return Broker(
        lock_path=base / "gpu.lock",
        estado_path=base / "residente.json",
        liberadores={
            "llm": lambda: None,
            "tts": lambda: None,
            "imagem": lambda: None,
        },
        timeout_lock=timeout_lock,
    )


def test_broker_holds_one_resident_at_a_time(real_settings, tmp_path: Path) -> None:
    base = tmp_path / "broker"
    base.mkdir()

    filho = subprocess.Popen(
        [sys.executable, "-c", _CHILD_PROGRAM, str(base)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        prazo = time.monotonic() + 30
        while not (base / "ready").exists():
            if time.monotonic() > prazo:
                _, erro = filho.communicate(timeout=10)
                pytest.fail(f"filho não reivindicou a GPU: {erro}")
            if filho.poll() is not None:
                _, erro = filho.communicate()
                pytest.fail(f"filho morreu antes de reivindicar: {erro}")
            time.sleep(0.05)

        concorrente = _local_broker(base, timeout_lock=0.2)
        inicio = time.monotonic()
        with pytest.raises(GPUOcupada):
            with concorrente.exclusivo("imagem"):
                pass
        assert time.monotonic() - inicio >= 0.15, "não esperou o timeout do lock"
    finally:
        filho.wait(timeout=30)

    assert filho.returncode == 0

    apos = _local_broker(base, timeout_lock=5.0)
    with apos.exclusivo("imagem"):
        pass
    assert json.loads((base / "residente.json").read_text(encoding="utf-8"))["recurso"] == "imagem"
