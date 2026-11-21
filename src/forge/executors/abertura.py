"""Renderiza só os blocos necessários para revisar a abertura."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from forge.agents.midia import gravar_plano
from forge.domain.embalagem import Embalagem
from forge.domain.execucao import ArtifactOutput, RunSnapshot
from forge.domain.midia import PlanoMidia
from forge.domain.operacao import StageName
from forge.executors.ffmpeg import clip_from_image, concat_videos, concat_wavs, run_ffmpeg
from forge.services.legendas import formatar_srt, gerar_deixas
from forge.services.linha_tempo import linha_do_tempo
from forge.services.persistencia import carregar_modelo, gravar_modelo


SEGUNDOS = 30


def aplicar_direcao_visual(plano: PlanoMidia, ajustes: dict) -> PlanoMidia:
    imagens = ajustes.get("imagem", {})
    beats = []
    for beat in plano.beats:
        orientacao = imagens.get(beat.id, {}).get("orientacao")
        prompt = f"{beat.prompt}\nDireção revisada: {orientacao}" if orientacao else beat.prompt
        beats.append(beat.model_copy(update={"prompt": prompt}))
    return plano.model_copy(update={"beats": beats})


def copiar_arquivo(origem: Path, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_suffix(destino.suffix + ".tmp")
    shutil.copyfile(origem, temporario)
    temporario.replace(destino)


def _cache_item(cache: Path, chave: str, nome: str) -> tuple[Path, ArtifactOutput] | None:
    caminho = cache / chave / nome
    registro = caminho.with_suffix(".json")
    if not caminho.is_file() or not registro.is_file():
        return None
    return caminho, carregar_modelo(registro, ArtifactOutput)


def _guardar(contexto: RunSnapshot, output: ArtifactOutput, cache: Path, chave: str):
    origem = contexto.run_dir / output.relative_path
    caminho = cache / chave / origem.name
    copiar_arquivo(origem, caminho)
    gravar_modelo(caminho.with_suffix(".json"), output)
    return caminho, output


def artefato_aprovado(context: RunSnapshot, kind: str, **metadata):
    if not context.config_snapshot.get("previa_aprovada"):
        return None
    for artifact in context.artifacts:
        if not artifact.is_current or artifact.kind != kind:
            continue
        if not all(artifact.metadata.get(chave) == valor for chave, valor in metadata.items()):
            continue
        try:
            path = (context.run_dir / artifact.relative_path).resolve(strict=True)
            path.relative_to(context.run_dir.resolve())
        except (OSError, ValueError):
            continue
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == artifact.sha256:
            return path, artifact.metadata
    return None


def _audio(contexto, plano, settings, ajustes, cache, emit):
    # Imports locais porque AudioExecutor também usa as funções de hash do plano.
    from forge.executors.audio import AudioExecutor
    from forge.executors.plano_midia import hash_json

    contexto = contexto.model_copy(update={"stage": StageName.AUDIO})
    plano_audio = AudioExecutor(settings=settings).prepare(contexto)
    encontrados = {}
    tempos = {}
    for inicio in range(0, len(plano.blocos), 2):
        grupos = {}
        for item in plano_audio.items[inicio:inicio + 2]:
            revisao = ajustes.get(item.item_key, {}).get("revisao", 0)
            seed = settings.tts_seed + revisao
            chave = hash_json([
                "audio", item.input_hash, seed, settings.tts_sample_rate, settings.tts_backend,
                str(settings.resolved_tts_model), str(settings.resolved_tts_voice_reference),
                settings.tts_reference_text,
            ])
            encontrado = _cache_item(cache, chave, f"{item.item_key}.wav")
            if encontrado is not None:
                encontrados[item.item_key] = encontrado
            else:
                grupos.setdefault(seed, []).append((item, chave))
        for seed, grupo in grupos.items():
            executor = AudioExecutor(settings=settings.model_copy(update={"tts_seed": seed}))
            parcial = plano_audio.model_copy(update={"items": [item for item, _ in grupo]})
            resultado = executor.execute(contexto, parcial, emit)
            gate = executor.validate(contexto, parcial, resultado)
            if resultado.failure or not gate.approved:
                raise RuntimeError(resultado.failure.message if resultado.failure else gate.findings[0].message)
            chaves = {item.item_key: chave for item, chave in grupo}
            for output in resultado.artifacts:
                encontrados[output.item_key] = _guardar(contexto, output, cache, chaves[output.item_key])
        for item in plano_audio.items[inicio:inicio + 2]:
            tempos[item.item_key] = float(encontrados[item.item_key][1].metadata["duration"])
            if sum(tempos.values()) >= SEGUNDOS:
                return encontrados, tempos, plano_audio
    return encontrados, tempos, plano_audio


def renderizar_abertura(
    context: RunSnapshot, plano: PlanoMidia, embalagem: Embalagem, settings, emit,
) -> list[ArtifactOutput]:
    from forge.executors.imagens import ImageExecutor
    from forge.executors.plano_midia import hash_json

    cache = context.run_dir / "video" / "abertura-cache"
    cache.mkdir(parents=True, exist_ok=True)
    pasta = context.run_dir / "video" / f"abertura-r{context.attempt}"
    ajustes = context.config_snapshot.get("ajustes_abertura") or {}
    outputs = []
    with TemporaryDirectory(prefix="abertura-", dir=cache) as temporario:
        tmp = Path(temporario)
        local = RunSnapshot(
            run_id=tmp.name, video_id=context.video_id, tema=context.tema, tese=context.tese,
            stage=StageName.AUDIO, attempt=context.attempt, run_dir=tmp, output_root=cache,
            config_snapshot={}, artifacts=[], work_items=[],
        )
        gravar_plano(tmp, plano)

        def progresso(*, kind, level, message, payload):
            if kind != "artifact.created":
                emit(kind="stage.progress", level=level, message=message, payload=payload)

        audios, duracoes, plano_audio = _audio(
            local, plano, settings, ajustes.get("audio", {}), cache, progresso,
        )
        blocos = [bloco for bloco in plano.blocos if bloco.id in duracoes]
        tempos = linha_do_tempo(blocos, duracoes)
        if not tempos:
            raise RuntimeError("A abertura não possui fala")
        fim = min(SEGUNDOS, tempos[-1].fim)
        inicios = {trecho.bloco_id: trecho.inicio for trecho in tempos}
        beats = sorted(
            (beat for beat in plano.beats if inicios.get(beat.bloco_id, fim) < fim - 0.04),
            key=lambda beat: inicios[beat.bloco_id],
        )
        if not beats:
            if not plano.beats:
                raise RuntimeError("O plano de mídia não possui imagens para a abertura")
            beats = [plano.beats[0]]

        imagens = ImageExecutor(settings=settings)
        local = local.model_copy(update={"stage": StageName.IMAGENS})
        plano_imagens = imagens.prepare(local)
        itens_imagem = {item.item_key: item for item in plano_imagens.items}
        geradas = []
        for beat in beats:
            item = itens_imagem[beat.id]
            revisao = ajustes.get("imagem", {}).get(beat.id, {}).get("revisao", 0)
            seed = settings.image_seed + revisao
            chave = hash_json(["imagem", item.input_hash, seed, settings.image_provider])
            encontrado = _cache_item(cache, chave, f"{beat.id}.png")
            if encontrado is None:
                tentativa = local.model_copy(update={"config_snapshot": {"image_seed": seed}})
                parcial = plano_imagens.model_copy(update={"items": [item]})
                resultado = imagens.execute(tentativa, parcial, progresso)
                gate = imagens.validate(tentativa, parcial, resultado)
                if resultado.failure or not gate.approved:
                    raise RuntimeError(resultado.failure.message if resultado.failure else gate.findings[0].message)
                encontrado = _guardar(local, resultado.artifacts[0], cache, chave)
            geradas.append(encontrado[0])
            outputs.append(ArtifactOutput(
                kind="abertura.imagem", relative_path=encontrado[0].relative_to(context.run_dir).as_posix(),
                mime_type="image/png", metadata={
                    **encontrado[1].metadata, "item": beat.id, "input_hash": item.input_hash,
                },
            ))

        clipes = []
        inicio = 0.0
        for indice, imagem in enumerate(geradas):
            proximo = inicios[beats[indice + 1].bloco_id] if indice + 1 < len(beats) else fim
            clipe = tmp / f"cena-{indice}.mp4"
            clip_from_image(imagem, clipe, seconds=max(0.04, proximo - inicio),
                            index=indice, portrait=False, fade_in=0, fade_out=0)
            clipes.append(clipe)
            inicio = proximo
        concat_videos(clipes, tmp / "imagens.mp4", tmp / "imagens.txt")
        concat_wavs([audios[bloco.id][0] for bloco in blocos], tmp / "voz.wav", tmp / "voz.txt")
        (tmp / "abertura.srt").write_text(formatar_srt(gerar_deixas(blocos, tempos)), encoding="utf-8")
        mp4 = tmp / "previa.mp4"
        code, stderr, _ = run_ffmpeg([
            "ffmpeg", "-y", "-loglevel", "error", "-i", "imagens.mp4", "-i", "voz.wav",
            "-vf", "subtitles=abertura.srt", "-t", str(fim), "-c:v", "libx264",
            "-preset", "veryfast", "-c:a", "aac", "-movflags", "+faststart", str(mp4),
        ], cwd=tmp)
        if code:
            raise RuntimeError(f"FFmpeg falhou ao montar a prévia: {stderr}")
        copiar_arquivo(mp4, pasta / "previa.mp4")

        thumb_key = hash_json([
            "thumbnail", embalagem.thumbnail.model_dump(mode="json"), settings.image_seed,
            settings.image_provider, str(settings.fonte_thumbnail),
        ])
        thumb = _cache_item(cache, thumb_key, "thumbnail.jpg")
        if thumb is None:
            gravar_modelo(tmp / "video" / "embalagem.json", embalagem)
            output = imagens._thumbnail(local, settings.image_seed, progresso)
            if output is not None:
                thumb = _guardar(local, output, cache, thumb_key)
        if thumb is not None:
            outputs.append(ArtifactOutput(
                kind="abertura.thumbnail", relative_path=thumb[0].relative_to(context.run_dir).as_posix(),
                mime_type="image/jpeg", metadata=thumb[1].metadata,
            ))

        for item in plano_audio.items:
            if item.item_key in duracoes:
                path, artifact = audios[item.item_key]
                outputs.append(ArtifactOutput(
                    kind="abertura.audio", relative_path=path.relative_to(context.run_dir).as_posix(),
                    mime_type="audio/wav", metadata={
                        **artifact.metadata, "item": item.item_key, "input_hash": item.input_hash,
                    },
                ))
    outputs.append(ArtifactOutput(
        kind="previa_abertura", relative_path=(pasta / "previa.mp4").relative_to(context.run_dir).as_posix(),
        mime_type="video/mp4", metadata={
            "segundos": fim,
            "titulos": [titulo.texto for titulo in embalagem.titulos],
            "itens_audio": [{"id": bloco.id, "texto": bloco.texto} for bloco in blocos],
            "itens_imagem": [{"id": beat.id, "prompt": beat.prompt} for beat in beats],
        },
    ))
    return outputs
