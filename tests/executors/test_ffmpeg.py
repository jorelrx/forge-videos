from __future__ import annotations

import re
from pathlib import Path

import pytest

from forge.executors.ffmpeg import (
    MediaProbe,
    build_ken_burns_filter,
    clip_from_image,
    concat_files,
    crossfade_videos,
    mix_audio,
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


# --- Acabamento: fades configuráveis, crossfade e mixagem -----------------

KEN_BURNS_12S_0 = (
    "crop=in_w*0.94:in_h*0.94,scale=7680:4320:force_original_aspect_ratio=increase"
    ":flags=lanczos,crop=7680:4320,zoompan=z='min(zoom+0.0005,1.22)'"
    ":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=288:s=1920x1080:fps=24,"
    "fade=t=in:st=0:d=0.5,fade=t=out:st=11.50:d=0.5,format=yuv420p"
)
KEN_BURNS_7_3S_2_RETRATO = (
    "crop=in_w*0.86:in_h*0.86,scale=7680:4320:force_original_aspect_ratio=increase"
    ":flags=lanczos,crop=7680:4320,zoompan=z='min(zoom+0.0003,1.1)'"
    ":x='iw/2-(iw/zoom/2)+(on/175)*180':y='ih/2-(ih/zoom/2)':d=175:s=1920x1080:fps=24,"
    "fade=t=in:st=0:d=0.5,fade=t=out:st=6.80:d=0.5,format=yuv420p"
)


class RunnerFalso:
    """Captura argv/cwd/timeout e o grafo de filtro no momento da chamada."""

    def __init__(self, code: int = 0, stderr: str = ""):
        self.code = code
        self.stderr = stderr
        self.chamadas: list[dict] = []

    def __call__(self, argv, *, cwd=None, timeout=300, **_):
        chamada = {"argv": list(argv), "cwd": cwd, "timeout": timeout, "grafo": None}
        if "-/filter_complex" in argv:
            script = Path(argv[argv.index("-/filter_complex") + 1])
            chamada["grafo"] = script.read_text(encoding="utf-8")
        elif "-filter_complex" in argv:
            chamada["grafo"] = argv[argv.index("-filter_complex") + 1]
        self.chamadas.append(chamada)
        return self.code, self.stderr, self.stderr.encode()


def test_ken_burns_sem_fades_novos_mantem_string_antiga():
    assert build_ken_burns_filter(12.0, 0, False) == KEN_BURNS_12S_0
    assert build_ken_burns_filter(7.3, 2, True) == KEN_BURNS_7_3S_2_RETRATO
    assert build_ken_burns_filter(12.0, 0, False, fade_in=None, fade_out=None) == KEN_BURNS_12S_0


def test_ken_burns_fade_zero_remove_o_fade():
    sem_in = build_ken_burns_filter(12.0, 0, fade_in=0)
    assert "fade=t=in" not in sem_in
    assert "fade=t=out:st=11.50:d=0.5" in sem_in
    sem_out = build_ken_burns_filter(12.0, 0, fade_out=0)
    assert "fade=t=out" not in sem_out
    assert "fade=t=in:st=0:d=0.5" in sem_out
    nenhum = build_ken_burns_filter(12.0, 0, fade_in=0, fade_out=0)
    assert "fade=" not in nenhum
    assert nenhum.endswith("format=yuv420p")


def test_ken_burns_fade_explicito_usa_a_duracao_pedida():
    valor = build_ken_burns_filter(10.0, 0, fade_in=1.0, fade_out=2.0)
    assert "fade=t=in:st=0:d=1.0" in valor
    assert "fade=t=out:st=8.00:d=2.0" in valor


def _vf(chamada) -> str:
    return chamada["argv"][chamada["argv"].index("-vf") + 1]


def test_clip_from_image_repassa_fades(tmp_path):
    runner = RunnerFalso()
    clip_from_image(
        tmp_path / "a.png", tmp_path / "a.mp4",
        seconds=5.0, index=0, portrait=False, fade_in=0, fade_out=0, runner=runner,
    )
    clip_from_image(
        tmp_path / "a.png", tmp_path / "b.mp4",
        seconds=12.0, index=0, portrait=False, runner=runner,
    )
    assert "fade=" not in _vf(runner.chamadas[0])
    assert _vf(runner.chamadas[1]) == KEN_BURNS_12S_0


def _clipes(tmp_path, n):
    caminhos = []
    for i in range(n):
        caminho = tmp_path / f"{i:04d}.mp4"
        caminho.write_bytes(b"x")
        caminhos.append(caminho)
    return caminhos


def test_crossfade_offsets_e_duracao_total(tmp_path):
    runner = RunnerFalso()
    clipes = _clipes(tmp_path, 3)
    crossfade_videos(clipes, [4.0, 5.0, 3.0], tmp_path / "out.mp4", crossfade=0.6, runner=runner)

    assert len(runner.chamadas) == 1
    chamada = runner.chamadas[0]
    grafo = chamada["grafo"]
    offsets = [
        float(x)
        for x in re.findall(r"xfade=transition=fade:duration=0\.600:offset=([\d.]+)", grafo)
    ]
    assert offsets == [4.0, 9.0]
    assert "concat" not in grafo
    # cada entrada é cortada no comprimento esperado: nominal + crossfade; o último sem
    assert "trim=duration=4.600" in grafo
    assert "trim=duration=5.600" in grafo
    assert "trim=duration=3.000" in grafo
    argv = chamada["argv"]
    assert argv[argv.index("-t") + 1] == "12.000"
    for clipe in clipes:
        assert str(clipe.resolve()) in argv
    assert argv[-1] == str((tmp_path / "out.mp4").resolve())
    assert "-an" in argv
    assert argv[argv.index("-c:v") + 1] == "libx264"
    assert argv[argv.index("-crf") + 1] == "18"
    assert argv[argv.index("-preset") + 1] == "medium"
    assert argv[argv.index("-pix_fmt") + 1] == "yuv420p"
    assert argv[argv.index("-r") + 1] == "24"
    assert "scale=1920:1080" in grafo
    assert chamada["timeout"] >= 3 * 3600


def test_crossfade_corte_seco_quando_clipe_e_curto(tmp_path):
    runner = RunnerFalso()
    # clipe do meio (1.0 s) < 2*0.6: as duas junções dele viram corte seco
    crossfade_videos(
        _clipes(tmp_path, 4), [4.0, 1.0, 5.0, 3.0], tmp_path / "out.mp4",
        crossfade=0.6, runner=runner,
    )
    grafo = runner.chamadas[0]["grafo"]
    offsets = [float(x) for x in re.findall(r"offset=([\d.]+)", grafo)]
    assert offsets == [10.0]  # só a junção 5.0 -> 3.0 tem transição
    assert grafo.count("concat=n=2:v=1:a=0") == 2
    # o corte seco é absoluto no acumulado nominal, para o arredondamento de
    # quadro não somar de um corte para o outro
    assert "trim=end=4.000" in grafo
    assert "trim=end=5.000" in grafo
    # clipe que termina em corte seco perde o acréscimo
    assert "trim=duration=4.000" in grafo
    assert "trim=duration=1.000" in grafo
    assert "trim=duration=5.600" in grafo
    assert "trim=duration=3.000" in grafo
    argv = runner.chamadas[0]["argv"]
    assert argv[argv.index("-t") + 1] == "13.000"


def test_crossfade_um_clipe_so_nao_tem_xfade(tmp_path):
    runner = RunnerFalso()
    crossfade_videos(_clipes(tmp_path, 1), [7.0], tmp_path / "out.mp4", crossfade=0.6, runner=runner)
    grafo = runner.chamadas[0]["grafo"]
    assert "xfade" not in grafo
    assert "concat" not in grafo
    assert "trim=duration=7.000" in grafo


def test_crossfade_zero_e_tudo_corte_seco(tmp_path):
    runner = RunnerFalso()
    crossfade_videos(
        _clipes(tmp_path, 3), [4.0, 5.0, 3.0], tmp_path / "out.mp4", crossfade=0, runner=runner,
    )
    grafo = runner.chamadas[0]["grafo"]
    assert "xfade" not in grafo
    assert grafo.count("concat=n=2:v=1:a=0") == 2


def test_crossfade_queima_ass_com_nome_relativo_e_cwd(tmp_path):
    runner = RunnerFalso()
    pasta_ass = tmp_path / "legenda dir"
    pasta_ass.mkdir()
    ass = pasta_ass / "cartoes.ass"
    ass.write_text("[Script Info]\n", encoding="utf-8")
    crossfade_videos(
        _clipes(tmp_path, 2), [4.0, 5.0], tmp_path / "out.mp4",
        crossfade=0.6, legendas_ass=ass, runner=runner,
    )
    chamada = runner.chamadas[0]
    assert Path(chamada["cwd"]) == pasta_ass.resolve()
    grafo = chamada["grafo"]
    assert "ass=filename=cartoes.ass" in grafo
    assert str(pasta_ass) not in grafo
    assert "C:" not in grafo
    # o ass é o último filtro antes da saída
    assert grafo.rstrip().endswith("[vout]")
    assert grafo.rindex("ass=") > grafo.rindex("xfade")


def test_crossfade_sem_ass_nao_queima_nada(tmp_path):
    runner = RunnerFalso()
    crossfade_videos(_clipes(tmp_path, 2), [4.0, 5.0], tmp_path / "out.mp4", crossfade=0.6, runner=runner)
    assert "ass=" not in runner.chamadas[0]["grafo"]


def test_crossfade_erro_do_runner_vira_runtime_error(tmp_path):
    runner = RunnerFalso(code=1, stderr="boom xfade")
    with pytest.raises(RuntimeError, match="boom xfade"):
        crossfade_videos(
            _clipes(tmp_path, 2), [4.0, 5.0], tmp_path / "out.mp4", crossfade=0.6, runner=runner,
        )


def test_crossfade_rejeita_listas_de_tamanho_diferente(tmp_path):
    with pytest.raises(ValueError):
        crossfade_videos(
            _clipes(tmp_path, 2), [4.0], tmp_path / "out.mp4", crossfade=0.6, runner=RunnerFalso(),
        )


def test_crossfade_grafo_vai_em_arquivo_para_nao_estourar_a_linha_de_comando(tmp_path):
    runner = RunnerFalso()
    n = 80
    crossfade_videos(_clipes(tmp_path, n), [5.0] * n, tmp_path / "out.mp4", crossfade=0.6, runner=runner)
    argv = runner.chamadas[0]["argv"]
    assert "-/filter_complex" in argv
    assert len(re.findall(r"xfade=", runner.chamadas[0]["grafo"])) == n - 1
    assert not any("xfade" in arg for arg in argv)


def test_mix_sem_trilha_so_normaliza(tmp_path):
    runner = RunnerFalso()
    mix_audio(
        tmp_path / "narracao.wav", None, tmp_path / "mix.wav",
        duracao=6.0, volume_db=-20, runner=runner,
    )
    argv = runner.chamadas[0]["argv"]
    grafo = runner.chamadas[0]["grafo"]
    assert "loudnorm=I=-14:TP=-1.5:LRA=11" in grafo
    assert "sidechaincompress" not in grafo
    assert "-stream_loop" not in argv
    assert argv[argv.index("-t") + 1] == "6.000"
    assert argv[argv.index("-c:a") + 1] == "pcm_s16le"
    assert argv[argv.index("-ar") + 1] == "48000"
    assert argv[argv.index("-ac") + 1] == "2"


def test_mix_com_trilha_abaixa_sob_a_voz(tmp_path):
    runner = RunnerFalso()
    trilha = tmp_path / "trilha.mp3"
    mix_audio(
        tmp_path / "narracao.wav", trilha, tmp_path / "mix.wav",
        duracao=600.0, volume_db=-20, runner=runner,
    )
    argv = runner.chamadas[0]["argv"]
    grafo = runner.chamadas[0]["grafo"]
    # o loop vale para a trilha, que é a segunda entrada
    i_loop = argv.index("-stream_loop")
    assert argv[i_loop + 1] == "-1"
    assert argv[i_loop + 2] == "-i"
    assert argv[i_loop + 3] == str(trilha)
    assert "loudnorm=I=-14:TP=-1.5:LRA=11" in grafo
    assert "volume=-20.0dB" in grafo
    assert "afade=t=in:st=0:d=2" in grafo
    assert "afade=t=out:st=596.000:d=4" in grafo
    assert "sidechaincompress" in grafo
    assert "normalize=0" in grafo
    assert argv[argv.index("-t") + 1] == "600.000"


def test_mix_erro_do_runner_vira_runtime_error(tmp_path):
    with pytest.raises(RuntimeError, match="mix ruim"):
        mix_audio(
            tmp_path / "n.wav", None, tmp_path / "m.wav", duracao=6.0, volume_db=-20,
            runner=RunnerFalso(code=1, stderr="mix ruim"),
        )
