"""Testes que codificam de verdade com o ffmpeg do PATH.

Os de unidade só conferem a string do comando; aqui se prova que o grafo roda
(no Windows, com cwd e filtro `ass`) e que a transição é uma mistura das duas
imagens, não um fade para preto — a regressão que motivou o crossfade.
"""
from __future__ import annotations

import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path

import pytest

from forge.executors.ffmpeg import (
    clip_from_image,
    crossfade_videos,
    mix_audio,
    probe_media,
)

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe fora do PATH",
)

CROSSFADE = 0.5
NOMINAIS = [2.0, 2.0, 2.0]
VERMELHO = (200, 30, 30)
AZUL = (30, 30, 200)
VERDE = (30, 200, 30)


def _imagem(caminho: Path, cor: tuple[int, int, int]) -> Path:
    from PIL import Image

    # pequena: o clip_from_image escala para 7680 de qualquer jeito
    Image.new("RGB", (320, 180), cor).save(caminho)
    return caminho


def _wav(caminho: Path, segundos: float, *, silencios: list[tuple[float, float]] = ()) -> Path:
    """Tom de 440 Hz em 48 kHz mono, zerado nos intervalos de `silencios`."""
    taxa = 48000
    quadros = bytearray()
    for n in range(int(segundos * taxa)):
        t = n / taxa
        mudo = any(inicio <= t < fim for inicio, fim in silencios)
        valor = 0 if mudo else int(12000 * math.sin(2 * math.pi * 440 * t))
        quadros += struct.pack("<h", valor)
    with wave.open(str(caminho), "wb") as arquivo:
        arquivo.setnchannels(1)
        arquivo.setsampwidth(2)
        arquivo.setframerate(taxa)
        arquivo.writeframes(bytes(quadros))
    return caminho


def _clipes(tmp_path: Path) -> list[Path]:
    clipes = []
    cores = [VERMELHO, AZUL, VERDE]
    for i, (cor, nominal) in enumerate(zip(cores, NOMINAIS)):
        imagem = _imagem(tmp_path / f"img{i}.png", cor)
        ultimo = i == len(NOMINAIS) - 1
        clipe = tmp_path / "clipes" / f"{i:04d}.mp4"
        clip_from_image(
            imagem, clipe,
            seconds=nominal + (0 if ultimo else CROSSFADE),
            index=i, portrait=False,
            fade_in=0.3 if i == 0 else 0,
            fade_out=0.3 if ultimo else 0,
        )
        clipes.append(clipe)
    return clipes


def _media_do_quadro(video: Path, segundo: float, destino: Path) -> tuple[float, float, float]:
    from PIL import Image, ImageStat

    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-ss", f"{segundo:.3f}",
            "-i", str(video), "-frames:v", "1", str(destino),
        ],
        check=True, capture_output=True, timeout=120,
    )
    with Image.open(destino) as quadro:
        r, g, b = ImageStat.Stat(quadro.convert("RGB")).mean
    return r, g, b


def test_crossfade_real_mistura_as_imagens_e_mantem_a_duracao(tmp_path):
    clipes = _clipes(tmp_path)
    saida = tmp_path / "video.mp4"

    crossfade_videos(clipes, NOMINAIS, saida, crossfade=CROSSFADE)

    probe = probe_media(saida)
    assert probe.has_video_stream
    assert not probe.has_audio_stream
    assert (probe.width, probe.height) == (1920, 1080)
    assert probe.duration == pytest.approx(sum(NOMINAIS), abs=0.1)

    # meio da primeira transição: vermelho e azul misturados, nada de preto
    r, g, b = _media_do_quadro(saida, NOMINAIS[0] + CROSSFADE / 2, tmp_path / "meio.png")
    assert r + g + b > 150
    assert r > 60 and b > 60
    # e longe da transição a cor é pura
    r, g, b = _media_do_quadro(saida, 1.0, tmp_path / "puro.png")
    assert r > 150 and b < 70


def test_crossfade_real_queima_ass_com_cwd(tmp_path):
    clipes = _clipes(tmp_path)
    pasta = tmp_path / "legenda com espaço"
    pasta.mkdir()
    ass = pasta / "cartoes.ass"
    ass.write_text(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Rodape,Arial,48,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,"
        "100,100,0,0,1,2,0,1,60,60,60,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:00.50,0:00:03.00,Rodape,,0,0,0,,Sêneca — Cartas a Lucílio\n",
        encoding="utf-8",
    )
    saida = tmp_path / "video_ass.mp4"

    crossfade_videos(clipes, NOMINAIS, saida, crossfade=CROSSFADE, legendas_ass=ass)

    probe = probe_media(saida)
    assert probe.duration == pytest.approx(sum(NOMINAIS), abs=0.1)


@pytest.mark.parametrize("com_trilha", [True, False])
def test_mix_audio_real_produz_a_duracao_pedida(tmp_path, com_trilha):
    narracao = _wav(tmp_path / "narracao.wav", 6.0, silencios=[(2.0, 3.0), (4.5, 5.0)])
    trilha = _wav(tmp_path / "trilha.wav", 2.0) if com_trilha else None
    saida = tmp_path / "mix.wav"

    mix_audio(narracao, trilha, saida, duracao=6.0, volume_db=-20.0)

    with wave.open(str(saida), "rb") as arquivo:
        assert arquivo.getframerate() == 48000
        assert arquivo.getnchannels() == 2
        assert arquivo.getsampwidth() == 2
        segundos = arquivo.getnframes() / arquivo.getframerate()
    assert segundos == pytest.approx(6.0, abs=0.1)
