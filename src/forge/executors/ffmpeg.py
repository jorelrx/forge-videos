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
    seconds: float,
    index: int,
    portrait: bool = False,
    *,
    fade: float = FADE_PADRAO,
    fade_in: float | None = None,
    fade_out: float | None = None,
) -> str:
    """Cadeia completa de um clipe: overscan, escala, zoompan, fades, yuv420p.

    `fade_in`/`fade_out` em None mantêm o comportamento antigo (os dois valem
    `fade`). Com crossfade, só o primeiro clipe abre do preto e só o último
    fecha nele; os do meio passam 0, senão cada transição atravessaria o preto.
    """
    entrada = fade if fade_in is None else fade_in
    saida = fade if fade_out is None else fade_out
    frames = max(1, int(round(seconds * FPS)))
    over = OVERSCAN_RETRATO if portrait else OVERSCAN
    movimento = ken_burns_motion(index, frames, ceiling=1.10 if portrait else 1.22)
    fades = ""
    if entrada > 0:
        fades += f"fade=t=in:st=0:d={entrada},"
    if saida > 0:
        fades += f"fade=t=out:st={max(0.0, seconds - saida):.2f}:d={saida},"
    return (
        f"crop=in_w*{over}:in_h*{over},"
        f"scale={FONTE_LARGA}:{FONTE_LARGA * 9 // 16}"
        f":force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={FONTE_LARGA}:{FONTE_LARGA * 9 // 16},"
        f"zoompan={movimento}:d={frames}:s={LARGURA}x{ALTURA}:fps={FPS},"
        f"{fades}"
        f"format=yuv420p"
    )


def clip_from_image(
    imagem: Path,
    saida: Path,
    *,
    seconds: float,
    index: int,
    portrait: bool,
    fade_in: float | None = None,
    fade_out: float | None = None,
    runner=run_ffmpeg,
) -> None:
    """Um clipe Ken Burns de `seconds`, 16:9, sem bordas."""
    saida.parent.mkdir(parents=True, exist_ok=True)
    code, stderr, _ = runner(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-loop", "1", "-i", str(imagem),
            "-vf", build_ken_burns_filter(
                seconds, index, portrait, fade_in=fade_in, fade_out=fade_out
            ),
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


# Passe final codifica ~15 min de 1080p em libx264 medium numa máquina modesta.
TIMEOUT_PASSE_FINAL = 4 * 3600


def _escapar_valor_filtro(valor: str) -> str:
    """Escapa um valor de opção para dentro de um filtergraph.

    São dois níveis: o parser de opções do filtro (`\\`, `'`, `:`) e, por fora,
    o do grafo (`\\`, `'`, `[`, `]`, `,`, `;`). Nome comum como `cartoes.ass`
    passa intacto; o escape existe para nome com espaço/apóstrofo não quebrar.
    """
    opcao = "".join("\\" + c if c in "\\':" else c for c in valor)
    return "".join("\\" + c if c in "\\'[],;" else c for c in opcao)


def _juncoes_com_transicao(duracoes: list[float], crossfade: float) -> list[bool]:
    """Para cada junção i (entre clipe i e i+1): True = xfade, False = corte seco.

    Clipe nominal menor que 2*crossfade não comporta a transição de entrada e a
    de saída sem que elas se encostem; ali o corte seco é mais limpo.
    """
    if crossfade <= 0:
        return [False] * (len(duracoes) - 1)
    minimo = 2 * crossfade
    return [
        duracoes[i] >= minimo and duracoes[i + 1] >= minimo
        for i in range(len(duracoes) - 1)
    ]


def _grafo_crossfade(
    duracoes: list[float], crossfade: float, legendas_nome: str | None
) -> str:
    """Monta o filtergraph de N entradas com xfade/concat encadeados.

    Cada entrada é normalizada (escala, SAR, fps, pixel e base de tempo) porque
    xfade e concat recusam entradas que difiram em qualquer um desses. Depois é
    cortada no comprimento que a junção seguinte consome: nominal + crossfade
    quando há transição, só o nominal quando é corte seco (o acréscimo que o
    clipe trouxe é descartado ali). Assim o acumulado após a junção i mede
    sempre soma(duracoes[:i+1]) (+ crossfade se a próxima junção for xfade), o
    offset da transição i é exatamente soma(duracoes[:i+1]) e a saída termina
    em soma(duracoes) — a duração da narração.
    """
    transicoes = _juncoes_com_transicao(duracoes, crossfade)
    linhas: list[str] = []
    for i, nominal in enumerate(duracoes):
        comprimento = nominal + (crossfade if i < len(transicoes) and transicoes[i] else 0.0)
        linhas.append(
            f"[{i}:v]scale={LARGURA}:{ALTURA},setsar=1,fps={FPS},format=yuv420p,"
            f"trim=duration={comprimento:.3f},setpts=PTS-STARTPTS,settb=AVTB[c{i}];"
        )
    atual = "c0"
    acumulado = duracoes[0]
    for i, transicao in enumerate(transicoes):
        proximo = f"c{i + 1}"
        saida = f"j{i}"
        if transicao:
            linhas.append(
                f"[{atual}][{proximo}]xfade=transition=fade:duration={crossfade:.3f}"
                f":offset={acumulado:.3f}[{saida}];"
            )
        else:
            # `trim=duration` arredonda cada clipe para cima no grid de 24 fps
            # (0,8 s vira 20 quadros); em cortes secos seguidos o erro somaria.
            # O corte absoluto no acumulado nominal mantém o desvio abaixo de
            # um quadro, como o offset absoluto já faz no xfade.
            linhas.append(
                f"[{atual}]trim=end={acumulado:.3f}[t{i}];"
                f"[t{i}][{proximo}]concat=n=2:v=1:a=0,settb=AVTB[{saida}];"
            )
        atual = saida
        acumulado += duracoes[i + 1]
    final = f"[{atual}]format=yuv420p"
    if legendas_nome is not None:
        final += f",ass=filename={_escapar_valor_filtro(legendas_nome)}"
    linhas.append(final + "[vout]")
    return "\n".join(linhas) + "\n"


def crossfade_videos(
    clipes: list[Path],
    duracoes: list[float],
    saida: Path,
    *,
    crossfade: float,
    legendas_ass: Path | None = None,
    runner=run_ffmpeg,
) -> None:
    """Encadeia os clipes com crossfade num único passe, queimando o .ass junto.

    `duracoes` são as durações NOMINAIS; o arquivo de cada clipe, menos o
    último, traz `crossfade` segundos a mais para alimentar a transição. A
    linha do tempo de saída fica igual à soma das nominais, então capítulos e
    legenda calculados pela narração continuam valendo.

    O grafo vai num arquivo ao lado da saída (`-/filter_complex`): com ~60
    clipes ele, somado aos caminhos de entrada, chegaria perto do limite de
    ~32 mil caracteres da linha de comando no Windows. Com legenda, o comando
    roda com cwd na pasta do .ass e o filtro recebe só o nome do arquivo —
    escapar `C:\\...` dentro do filtergraph é frágil; por isso entradas e
    saída vão em caminho absoluto.
    """
    if len(clipes) != len(duracoes):
        raise ValueError("clipes e duracoes precisam ter o mesmo tamanho")
    if not clipes:
        raise ValueError("crossfade_videos precisa de ao menos um clipe")
    saida = Path(saida).resolve()
    saida.parent.mkdir(parents=True, exist_ok=True)
    cwd = None
    legendas_nome = None
    if legendas_ass is not None:
        legendas_ass = Path(legendas_ass).resolve()
        cwd = legendas_ass.parent
        legendas_nome = legendas_ass.name
    script = saida.with_name(saida.stem + ".filtergraph.txt")
    script.write_text(_grafo_crossfade(duracoes, crossfade, legendas_nome), encoding="utf-8")

    argv = ["ffmpeg", "-y", "-loglevel", "error"]
    for clipe in clipes:
        argv += ["-i", str(Path(clipe).resolve())]
    argv += [
        "-/filter_complex", str(script),
        "-map", "[vout]",
        "-an",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-r", str(FPS),
        "-t", f"{sum(duracoes):.3f}",
        str(saida),
    ]
    code, stderr, _ = runner(argv, cwd=cwd, timeout=TIMEOUT_PASSE_FINAL)
    if code != 0:
        raise RuntimeError(f"ffmpeg falhou no crossfade ({code}): {stderr[-600:]}")


# Ducking da trilha. A narração normalizada a -14 LUFS tem fala por volta de
# -20 a -10 dBFS; threshold 0.03 (~-30 dBFS) dispara com qualquer voz e ignora
# o silêncio entre frases. ratio 6 derruba a trilha ~10-15 dB sob a voz sem
# sumir com ela. attack 20 ms pega a primeira sílaba; release 600 ms devolve a
# trilha nas pausas sem o "bombear" audível de um release curto.
DUCK_THRESHOLD = 0.03
DUCK_RATIO = 6
DUCK_ATTACK_MS = 20
DUCK_RELEASE_MS = 600
TRILHA_FADE_IN = 2.0
TRILHA_FADE_OUT = 4.0
LOUDNORM = "loudnorm=I=-14:TP=-1.5:LRA=11"


def mix_audio(
    narracao: Path,
    trilha: Path | None,
    saida: Path,
    *,
    duracao: float,
    volume_db: float,
    runner=run_ffmpeg,
) -> None:
    """Narração normalizada a -14 LUFS, com a trilha em loop abaixada sob a voz.

    A trilha entra com `-stream_loop -1` (mais curta que o vídeo, repete) e é
    cortada em `duracao` com fade de saída terminando ali (mais longa, não
    acaba seca). A narração passa por `apad` até `duracao` para servir de
    chave do sidechain até o fim — sem isso o compressor pararia quando a voz
    acabasse. `amix` com `normalize=0`: o padrão divide cada entrada pelo
    número de entradas e jogaria a narração 6 dB abaixo do loudnorm.
    Sem trilha, sai só a narração normalizada. WAV pcm_s16le 48 kHz estéreo.
    """
    saida = Path(saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    d = f"{duracao:.3f}"
    voz = (
        f"[0:a]aformat=channel_layouts=stereo,{LOUDNORM},"
        f"aresample=48000,apad=whole_dur={d},atrim=duration={d}"
    )
    argv = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(narracao)]
    if trilha is None:
        grafo = f"{voz}[aout]"
    else:
        argv += ["-stream_loop", "-1", "-i", str(trilha)]
        inicio_fade_out = max(0.0, duracao - TRILHA_FADE_OUT)
        grafo = (
            f"{voz},asplit=2[voz][chave];"
            f"[1:a]aresample=48000,aformat=channel_layouts=stereo,"
            f"atrim=duration={d},volume={float(volume_db):.1f}dB,"
            f"afade=t=in:st=0:d={TRILHA_FADE_IN:g},"
            f"afade=t=out:st={inicio_fade_out:.3f}:d={TRILHA_FADE_OUT:g}[musica];"
            f"[musica][chave]sidechaincompress=threshold={DUCK_THRESHOLD}"
            f":ratio={DUCK_RATIO}:attack={DUCK_ATTACK_MS}:release={DUCK_RELEASE_MS}"
            f"[abaixada];"
            f"[voz][abaixada]amix=inputs=2:duration=first:dropout_transition=0"
            f":normalize=0[aout]"
        )
    argv += [
        "-filter_complex", grafo,
        "-map", "[aout]",
        "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2",
        "-t", d,
        str(saida),
    ]
    code, stderr, _ = runner(argv, timeout=1800)
    if code != 0:
        raise RuntimeError(f"ffmpeg falhou ao mixar áudio ({code}): {stderr[-600:]}")


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
    "crossfade_videos",
    "image_aspect",
    "ken_burns_motion",
    "mix_audio",
    "mux_audio",
    "probe_duration",
    "probe_media",
    "run_ffmpeg",
]
