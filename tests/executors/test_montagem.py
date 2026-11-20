"""Montagem real: Ken Burns por beat, concat e mux com a narração.

`ffmpeg`/`ffprobe` entram por injeção: a unidade prova a sequência de comandos,
a divisão de duração e o gate sem gastar minutos de encode.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from forge.domain.execucao import ArtifactOutput, RunSnapshot
from forge.domain.midia import Beat, BlocoNarracao, PlanoMidia
from forge.domain.operacao import Artifact, StageName
from forge.executors.ffmpeg import MediaProbe
from forge.executors.montagem import ComposeExecutor
from forge.infrastructure.config import Settings
from forge.repositories.connection import Database
from forge.repositories.operacao import OperacaoRepository
from forge.repositories.schema import init_db
from forge.services.catalogo import ChildEventProjector, ChildProtocolError
from forge.services.persistencia import gravar_modelo


class RecordingRunner:
    """Registra os argv e cria os arquivos de saída que cada passo declara."""

    def __init__(self, *, fail_on: str | None = None) -> None:
        self.calls: list[list[str]] = []
        self.fail_on = fail_on

    def __call__(self, argv, *, cwd=None, timeout=300, capture_stderr_limit=4096):
        self.calls.append(list(argv))
        if self.fail_on and self.fail_on in " ".join(argv):
            return 1, f"ffmpeg recusou: {self.fail_on}", b""
        destino = Path(argv[-1])
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(b"\x00" * 512)
        return 0, "", b""

    def filters(self) -> list[str]:
        return [
            call[call.index("-vf") + 1]
            for call in self.calls
            if "-vf" in call
        ]


def _prober(duration: float = 12.0):
    def probe(path) -> MediaProbe:
        return MediaProbe(
            codec="h264",
            audio_codec="aac",
            width=1920,
            height=1080,
            duration=duration,
            has_video_stream=True,
            has_audio_stream=True,
        )

    return probe


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        studio_runs_dir=tmp_path / "runs",
        output_dir=tmp_path / "roteiros",
        midia_alvo_segundos=15,
        # Pasta do teste, não a do operador: uma faixa real em library/trilhas
        # mudaria os comandos esperados.
        trilhas_dir=tmp_path / "trilhas",
    )


def _artifact(run_id: str, stage_id: str, *, key: str, kind: str, path: str) -> Artifact:
    from datetime import UTC, datetime

    return Artifact(
        id=f"art-{key}",
        run_id=run_id,
        stage_run_id=stage_id,
        kind=kind,
        relative_path=path,
        sha256=hashlib.sha256(path.encode()).hexdigest(),
        size_bytes=2048,
        mime_type="image/png" if kind.startswith("image") else "audio/wav",
        metadata={},
        is_current=True,
        created_at=datetime.now(UTC),
    )


def _snapshot(tmp_path: Path, *, blocos: int = 2, beats_por_bloco: int = 1) -> RunSnapshot:
    """Dois blocos de narração, cada um com N beats (imagem)."""
    root = tmp_path / "runs"
    run_dir = root / "run-1"
    (run_dir / "video" / "images").mkdir(parents=True, exist_ok=True)
    (run_dir / "video" / "audio").mkdir(parents=True, exist_ok=True)

    lista_blocos: list[BlocoNarracao] = []
    lista_beats: list[Beat] = []
    artifacts: list[Artifact] = []
    numero_beat = 0

    for indice in range(1, blocos + 1):
        bloco_id = f"b{indice:03d}"
        lista_blocos.append(BlocoNarracao(id=bloco_id, secao="Gancho", texto="texto"))
        audio_rel = f"video/audio/{bloco_id}.wav"
        (run_dir / audio_rel).write_bytes(b"RIFF")
        artifacts.append(
            _artifact("run-1", "stage-audio", key=bloco_id, kind="audio.wav", path=audio_rel)
        )
        for _ in range(beats_por_bloco):
            numero_beat += 1
            beat_id = f"i{numero_beat:03d}"
            lista_beats.append(Beat(id=beat_id, bloco_id=bloco_id, prompt="cena"))
            imagem_rel = f"video/images/{beat_id}.png"
            (run_dir / imagem_rel).write_bytes(b"\x89PNG")
            artifacts.append(
                _artifact(
                    "run-1", "stage-img", key=beat_id, kind="image.png", path=imagem_rel
                )
            )

    gravar_modelo(
        run_dir / "video" / "midia.json",
        PlanoMidia(blocos=lista_blocos, beats=lista_beats),
    )
    return RunSnapshot(
        run_id="run-1",
        video_id="v1",
        tema="T",
        tese="Teste",
        stage=StageName.MONTAGEM,
        attempt=1,
        output_root=root,
        run_dir=run_dir,
        config_snapshot={},
        artifacts=artifacts,
        work_items=[],
    )


def _executor(tmp_path: Path, runner, *, durations: dict[str, float] | None = None):
    duracoes = durations or {}

    def prober(path) -> MediaProbe:
        nome = Path(path).name
        return MediaProbe(
            codec="h264",
            audio_codec="aac",
            width=1920,
            height=1080,
            duration=duracoes.get(nome, 12.0),
            has_video_stream=True,
            has_audio_stream=True,
        )

    return ComposeExecutor(settings=_settings(tmp_path), runner=runner, prober=prober)


class TestPlan:
    def test_plan_has_one_item_per_beat_in_order(self, tmp_path):
        snapshot = _snapshot(tmp_path, blocos=2, beats_por_bloco=1)

        plan = _executor(tmp_path, RecordingRunner()).prepare(snapshot)

        assert [item.item_key for item in plan.items] == ["i001", "i002"]

    def test_item_carries_both_image_and_audio_paths(self, tmp_path):
        snapshot = _snapshot(tmp_path)

        plan = _executor(tmp_path, RecordingRunner()).prepare(snapshot)

        item = plan.items[0]
        assert item.input["image"] == "video/images/i001.png"
        assert item.input["audio"] == "video/audio/b001.wav"

    def test_beats_sharing_a_block_split_that_block_audio(self, tmp_path):
        """Dois beats sobre o mesmo bloco dividem a narração: sem isso o vídeo
        teria o dobro da duração do áudio."""
        snapshot = _snapshot(tmp_path, blocos=1, beats_por_bloco=2)

        plan = _executor(tmp_path, RecordingRunner()).prepare(snapshot)

        assert [item.input["divisor"] for item in plan.items] == [2, 2]

    def test_plan_deduplicates_blocks_used_by_several_beats(self, tmp_path):
        snapshot = _snapshot(tmp_path, blocos=1, beats_por_bloco=3)

        plan = _executor(tmp_path, RecordingRunner()).prepare(snapshot)

        assert plan.items[0].input["audio"] == plan.items[2].input["audio"]

    def test_one_image_beat_carries_through_following_audio_blocks(self, tmp_path):
        snapshot = _snapshot(tmp_path, blocos=2, beats_por_bloco=1)
        gravar_modelo(snapshot.run_dir / "video" / "midia.json", PlanoMidia(
            blocos=[
                BlocoNarracao(id="b001", secao="Gancho", texto="fala 1"),
                BlocoNarracao(id="b002", secao="Gancho", texto="fala 2"),
            ],
            beats=[Beat(id="i001", bloco_id="b001", prompt="cena")],
        ))

        plan = _executor(tmp_path, RecordingRunner()).prepare(snapshot)

        assert plan.items[0].input["audios"] == [
            "video/audio/b001.wav", "video/audio/b002.wav",
        ]


class TestExecute:
    def test_builds_one_clip_per_beat_then_concats_and_muxes(self, tmp_path):
        runner = RecordingRunner()
        snapshot = _snapshot(tmp_path, blocos=2)
        executor = _executor(tmp_path, runner)
        plan = executor.prepare(snapshot)

        result = executor.execute(snapshot, plan, lambda **event: None)

        # 2 clipes + concat da narração + mixagem + crossfade + mux
        assert len(runner.calls) == 6
        assert (snapshot.run_dir / "video" / "final.mp4").is_file()
        assert [a.kind for a in result.artifacts] == ["video/final.mp4", "legendas.srt"]

    def test_catalogs_montage_artifact_without_individual_item(self, tmp_path):
        db = Database(tmp_path / "forge.db")
        init_db(db)
        with db.transaction(immediate=True) as conn:
            repo = OperacaoRepository(conn)
            _, run = repo.create_video_and_run(
                tema="Tema", tese="Tese", priority=50, config_snapshot={},
                workflow_version=2, git_commit="abc123",
            )
            stage = next(item for item in repo.current_stages(run.id) if item.stage is StageName.MONTAGEM)

        snapshot = _snapshot(tmp_path).model_copy(update={"run_id": run.id, "video_id": run.video_id})
        events = []
        executor = _executor(tmp_path, RecordingRunner())
        plan = executor.prepare(snapshot)
        executor.execute(snapshot, plan, lambda **event: events.append(event))
        artifact_event = next(event for event in events if event["kind"] == "artifact.created")

        projector = ChildEventProjector(db, snapshot.run_dir, stage.id)
        invalid_item_event = {**artifact_event["payload"], "item_key": "unknown-item"}
        with pytest.raises(ChildProtocolError, match="unknown item_key"):
            projector.project("artifact.created", invalid_item_event)
        projector.project("artifact.created", artifact_event["payload"])

        with db.connection() as conn:
            artifacts = OperacaoRepository(conn).list_artifacts(run.id)
        assert len(artifacts) == 1
        assert artifacts[0].stage_run_id == stage.id
        assert artifacts[0].work_item_id is None

    def test_every_clip_uses_the_ken_burns_chain_at_1080p(self, tmp_path):
        runner = RecordingRunner()
        snapshot = _snapshot(tmp_path, blocos=2)
        executor = _executor(tmp_path, runner)
        plan = executor.prepare(snapshot)

        executor.execute(snapshot, plan, lambda **event: None)

        clipes = runner.filters()[:2]
        assert len(clipes) == 2
        for filtro in clipes:
            assert "zoompan=" in filtro
            assert "s=1920x1080" in filtro
            assert "format=yuv420p" in filtro

    def test_alternates_motion_between_consecutive_clips(self, tmp_path):
        """Movimento repetido denuncia vídeo automático."""
        runner = RecordingRunner()
        snapshot = _snapshot(tmp_path, blocos=3)
        executor = _executor(tmp_path, runner)
        plan = executor.prepare(snapshot)

        executor.execute(snapshot, plan, lambda **event: None)

        clipes = runner.filters()[:3]
        assert clipes[0] != clipes[1]
        assert clipes[1] != clipes[2]

    def test_clip_duration_follows_the_narration_of_its_block(self, tmp_path):
        runner = RecordingRunner()
        snapshot = _snapshot(tmp_path, blocos=1, beats_por_bloco=2)
        executor = _executor(
            tmp_path, runner, durations={"b001.wav": 10.0}
        )
        plan = executor.prepare(snapshot)

        executor.execute(snapshot, plan, lambda **event: None)

        # 10 s de narração divididos entre 2 beats; o primeiro arquivo leva o
        # crossfade (0,6 s) a mais, que a transição consome.
        primeiro, segundo = runner.calls[:2]
        assert primeiro[primeiro.index("-t") + 1].startswith("5.6")
        assert segundo[segundo.index("-t") + 1].startswith("5.0")

    def test_mux_uses_aac_and_shortest(self, tmp_path):
        runner = RecordingRunner()
        snapshot = _snapshot(tmp_path)
        executor = _executor(tmp_path, runner)
        plan = executor.prepare(snapshot)

        executor.execute(snapshot, plan, lambda **event: None)

        mux = runner.calls[-1]
        assert "aac" in mux
        assert "-shortest" in mux
        assert mux[-1].endswith("final.mp4")

    def test_a_failed_clip_is_a_stage_failure_without_a_final_video(self, tmp_path):
        runner = RecordingRunner(fail_on="-vf")
        snapshot = _snapshot(tmp_path)
        executor = _executor(tmp_path, runner)
        plan = executor.prepare(snapshot)

        result = executor.execute(snapshot, plan, lambda **event: None)

        assert result.failure is not None
        assert result.failure.code == "compose_failed"
        assert result.artifacts == []

    def test_refuses_to_compose_when_a_beat_has_no_image(self, tmp_path):
        snapshot = _snapshot(tmp_path, blocos=2)
        sem_imagem = snapshot.model_copy(
            update={
                "artifacts": [
                    a for a in snapshot.artifacts if a.relative_path != "video/images/i002.png"
                ]
            }
        )
        runner = RecordingRunner()
        executor = _executor(tmp_path, runner)

        result = executor.execute(
            sem_imagem, executor.prepare(sem_imagem), lambda **event: None
        )

        assert result.failure is not None
        assert result.failure.code == "compose_inputs_incomplete"
        assert runner.calls == [], "não pode chamar ffmpeg com entrada incompleta"


class TestValidate:
    def test_approves_a_real_1080p_h264_aac_output(self, tmp_path):
        snapshot = _snapshot(tmp_path)
        executor = _executor(tmp_path, RecordingRunner())
        plan = executor.prepare(snapshot)
        result = executor.execute(snapshot, plan, lambda **event: None)

        gate = executor.validate(snapshot, plan, result)

        assert gate.approved is True
        # Sem trilha na pasta e sem citações: aprova, com os dois avisos.
        assert [f.code for f in gate.findings] == ["trilha_ausente", "cartoes_ausentes"]

    @pytest.mark.parametrize(
        ("field", "value", "code"),
        [
            ("codec", "vp9", "video_codec_invalid"),
            ("audio_codec", "mp3", "audio_codec_invalid"),
            ("width", 1280, "video_resolution_invalid"),
            ("duration", 0.0, "video_duration_invalid"),
        ],
    )
    def test_rejects_a_wrong_probe(self, tmp_path, field, value, code):
        snapshot = _snapshot(tmp_path)
        base = MediaProbe(
            codec="h264",
            audio_codec="aac",
            width=1920,
            height=1080,
            duration=12.0,
            has_video_stream=True,
            has_audio_stream=True,
        )
        executor = ComposeExecutor(
            settings=_settings(tmp_path),
            runner=RecordingRunner(),
            prober=lambda path: replace(base, **{field: value}),
        )
        plan = executor.prepare(snapshot)
        result = executor.execute(snapshot, plan, lambda **event: None)

        gate = executor.validate(snapshot, plan, result)

        assert gate.approved is False
        assert code in {finding.code for finding in gate.findings}

    def test_rejects_when_the_final_file_disappears(self, tmp_path):
        snapshot = _snapshot(tmp_path)
        executor = _executor(tmp_path, RecordingRunner())
        plan = executor.prepare(snapshot)
        result = executor.execute(snapshot, plan, lambda **event: None)
        (snapshot.run_dir / "video" / "final.mp4").unlink()

        gate = executor.validate(snapshot, plan, result)

        assert gate.approved is False
        assert "video_output_missing" in {finding.code for finding in gate.findings}

    def test_rejects_when_no_final_artifact_was_emitted(self, tmp_path):
        snapshot = _snapshot(tmp_path)
        executor = _executor(tmp_path, RecordingRunner())
        plan = executor.prepare(snapshot)
        result = executor.execute(snapshot, plan, lambda **event: None)
        sem_final = result.model_copy(update={"artifacts": []})

        gate = executor.validate(snapshot, plan, sem_final)

        assert gate.approved is False
        assert "compose_output_missing" in {finding.code for finding in gate.findings}


# --- acabamento: crossfade, trilha, cartões, legenda, capítulos reais ---

def _rodar(tmp_path, snapshot, *, durations=None, runner=None):
    runner = runner or RecordingRunner()
    executor = _executor(tmp_path, runner, durations=durations)
    plan = executor.prepare(snapshot)
    result = executor.execute(snapshot, plan, lambda **event: None)
    return executor, plan, result, runner


def _com_citacoes(snapshot: RunSnapshot) -> None:
    """Põe uma referência em cada bloco e o `citacoes.json` que a resolve."""
    from forge.services.citacoes import Citacao, gravar_citacoes

    caminho = snapshot.run_dir / "video" / "midia.json"
    from forge.services.persistencia import carregar_modelo

    plano = carregar_modelo(caminho, PlanoMidia)
    for bloco in plano.blocos:
        bloco.referencias = ["4363/ch2/p7"]
    gravar_modelo(caminho, plano)
    gravar_citacoes(snapshot.run_dir, [
        Citacao(
            secao="Gancho", bloco=0, tipo="parafrase", texto="texto",
            autor="Nietzsche", obra="Beyond Good and Evil", path="4363/ch2/p7",
        )
    ])


def test_preto_so_na_abertura_e_no_fim(tmp_path):
    """Fade para preto a cada imagem é o que denunciava vídeo automático."""
    _, _, _, runner = _rodar(tmp_path, _snapshot(tmp_path, blocos=3))

    primeiro, meio, ultimo = runner.filters()[:3]
    assert "fade=t=in" in primeiro and "fade=t=out" not in primeiro
    assert "fade=t=" not in meio
    assert "fade=t=out" in ultimo and "fade=t=in" not in ultimo


def test_video_mudo_sai_do_crossfade_e_o_audio_da_mixagem(tmp_path):
    _, _, _, runner = _rodar(tmp_path, _snapshot(tmp_path, blocos=2))

    saidas = [Path(call[-1]).name for call in runner.calls]
    assert saidas == [
        "0000-i001.mp4", "0001-i002.mp4", "narration.wav", "mix.wav", "silent.mp4", "final.mp4",
    ]
    mux = runner.calls[-1]
    assert any(arg.endswith("mix.wav") for arg in mux)
    assert not any(arg.endswith("narration.wav") for arg in mux)


def test_legenda_usa_os_tempos_reais_dos_blocos(tmp_path):
    snapshot = _snapshot(tmp_path, blocos=2)

    _, _, result, _ = _rodar(
        tmp_path, snapshot, durations={"b001.wav": 4.0, "b002.wav": 6.0}
    )

    srt = (snapshot.run_dir / "video" / "legendas.srt").read_text(encoding="utf-8")
    assert "00:00:00,000 --> 00:00:04,000" in srt
    assert "00:00:04,000 --> 00:00:10,000" in srt
    legenda = next(a for a in result.artifacts if a.kind == "legendas.srt")
    assert legenda.mime_type == "application/x-subrip"
    assert legenda.relative_path == "video/legendas.srt"


def test_projetor_aceita_a_legenda(tmp_path):
    from forge.services.catalogo import ALLOWED_MIME

    assert "application/x-subrip" in ALLOWED_MIME


def test_cartoes_de_fonte_sao_queimados_no_passe_de_crossfade(tmp_path):
    snapshot = _snapshot(tmp_path, blocos=2)
    _com_citacoes(snapshot)

    executor, plan, result, runner = _rodar(tmp_path, snapshot)

    ass = (snapshot.run_dir / "video" / "cartoes.ass").read_text(encoding="utf-8")
    assert "Nietzsche — Beyond Good and Evil" in ass
    # O grafo vai em arquivo ao lado da saída (limite de linha de comando no
    # Windows); é nele que o filtro `ass` aparece.
    grafo = (snapshot.run_dir / "video" / "silent.filtergraph.txt").read_text(encoding="utf-8")
    assert "ass=filename=cartoes.ass" in grafo
    codigos = [f.code for f in executor.validate(snapshot, plan, result).findings]
    assert "cartoes_ausentes" not in codigos


def test_sem_citacoes_nao_ha_cartao_nem_filtro(tmp_path):
    snapshot = _snapshot(tmp_path, blocos=2)

    _, _, _, runner = _rodar(tmp_path, snapshot)

    assert not (snapshot.run_dir / "video" / "cartoes.ass").exists()
    grafo = (snapshot.run_dir / "video" / "silent.filtergraph.txt").read_text(encoding="utf-8")
    assert "ass=" not in grafo


def test_trilha_da_pasta_entra_na_mixagem(tmp_path):
    (tmp_path / "trilhas").mkdir()
    (tmp_path / "trilhas" / "calma.mp3").write_bytes(b"ID3")
    snapshot = _snapshot(tmp_path, blocos=2)

    executor, plan, result, runner = _rodar(tmp_path, snapshot)

    mix = next(call for call in runner.calls if call[-1].endswith("mix.wav"))
    assert any(arg.endswith("calma.mp3") for arg in mix)
    assert result.artifacts[0].metadata["trilha"] == "calma.mp3"
    codigos = [f.code for f in executor.validate(snapshot, plan, result).findings]
    assert "trilha_ausente" not in codigos


def test_sem_trilha_o_video_sai_so_com_a_narracao(tmp_path):
    snapshot = _snapshot(tmp_path, blocos=2)

    _, _, result, runner = _rodar(tmp_path, snapshot)

    assert result.failure is None
    assert result.artifacts[0].metadata["trilha"] is None
    mix = next(call for call in runner.calls if call[-1].endswith("mix.wav"))
    assert "-stream_loop" not in mix


def _com_embalagem(snapshot: RunSnapshot, *, abertura: str = "Abertura.") -> None:
    from forge.domain.embalagem import Capitulo, Embalagem, ThumbnailProposta

    gravar_modelo(
        snapshot.run_dir / "video" / "embalagem.json",
        Embalagem(
            thumbnail=ThumbnailProposta(texto="Texto", prompt="p"),
            descricao="velha",
            capitulos=[Capitulo(secao="Gancho", titulo="O começo", inicio_segundos=0)],
            abertura=abertura,
            fontes=["Nietzsche — Beyond Good and Evil"],
        ),
    )


def test_embalagem_e_regravada_com_o_tempo_real_e_o_credito_da_musica(tmp_path):
    from forge.domain.embalagem import Embalagem
    from forge.services.persistencia import carregar_modelo

    (tmp_path / "trilhas").mkdir()
    (tmp_path / "trilhas" / "calma.mp3").write_bytes(b"ID3")
    (tmp_path / "trilhas" / "calma.txt").write_text("Calma — Fulano (CC BY 4.0)", encoding="utf-8")
    snapshot = _snapshot(tmp_path, blocos=2)
    _com_embalagem(snapshot)

    executor, plan, result, _ = _rodar(tmp_path, snapshot)

    real = carregar_modelo(snapshot.run_dir / "video" / "embalagem.json", Embalagem)
    assert real.capitulos_estimados is False
    assert "Música: Calma — Fulano (CC BY 4.0)" in real.descricao
    assert "00:00 O começo" in (snapshot.run_dir / "embalagem.md").read_text(encoding="utf-8")
    assert [a.kind for a in result.artifacts] == [
        "video/final.mp4", "legendas.srt", "embalagem", "embalagem_markdown",
    ]
    codigos = [f.code for f in executor.validate(snapshot, plan, result).findings]
    assert "capitulos_estimados" not in codigos


def test_embalagem_antiga_fica_estimada_com_aviso(tmp_path):
    snapshot = _snapshot(tmp_path, blocos=2)
    _com_embalagem(snapshot, abertura="")

    executor, plan, result, _ = _rodar(tmp_path, snapshot)

    gate = executor.validate(snapshot, plan, result)
    assert gate.approved
    assert "capitulos_estimados" in [f.code for f in gate.findings]
    assert all(not a.kind.startswith("embalagem") for a in result.artifacts)


def test_legenda_ausente_reprova(tmp_path):
    snapshot = _snapshot(tmp_path, blocos=2)
    executor, plan, result, _ = _rodar(tmp_path, snapshot)
    final = result.artifacts[0]
    sem_legenda = result.model_copy(update={"artifacts": [
        final.model_copy(update={"metadata": {**final.metadata, "legendas": 0}})
    ]})

    gate = executor.validate(snapshot, plan, sem_legenda)

    assert not gate.approved
    assert "subtitles_missing" in [f.code for f in gate.findings]


def test_trocar_a_trilha_ou_o_crossfade_muda_o_hash_da_etapa(tmp_path):
    snapshot = _snapshot(tmp_path, blocos=2)
    executor = _executor(tmp_path, RecordingRunner())
    antes = executor.prepare(snapshot).input_hash

    (tmp_path / "trilhas").mkdir()
    (tmp_path / "trilhas" / "calma.mp3").write_bytes(b"ID3")
    com_trilha = executor.prepare(snapshot).input_hash
    outro_crossfade = executor.prepare(
        snapshot.model_copy(update={"config_snapshot": {"crossfade_segundos": 1.0}})
    ).input_hash

    assert len({antes, com_trilha, outro_crossfade}) == 3


# --- achados da revisão independente ---

def test_piso_de_duracao_nao_deixa_o_video_maior_que_a_narracao(tmp_path):
    """Bloco de 1,2 s com dois beats: cada um sobe para o piso de 0,8 s. Os 0,4 s
    a mais saem do clipe seguinte, senão toda imagem depois dali atrasa em
    relação à voz e o fade final é cortado pelo `-shortest`."""
    snapshot = _snapshot(tmp_path, blocos=2, beats_por_bloco=2)

    _, _, _, runner = _rodar(
        tmp_path, snapshot, durations={"b001.wav": 1.2, "b002.wav": 10.0}
    )

    tempos = [float(call[call.index("-t") + 1]) for call in runner.calls[:4]]
    # Nominais 0,8 + 0,8 + 4,6 + 5,0 = 11,2 s, a duração da narração; os três
    # primeiros arquivos levam o crossfade de 0,6 s a mais.
    assert tempos == pytest.approx([1.4, 1.4, 5.2, 5.0])


def test_trilha_ilegivel_nao_derruba_a_montagem(tmp_path):
    (tmp_path / "trilhas").mkdir()
    (tmp_path / "trilhas" / "ruim.mp3").write_bytes(b"nao e audio")
    snapshot = _snapshot(tmp_path, blocos=2)

    executor, plan, result, runner = _rodar(
        tmp_path, snapshot, runner=RecordingRunner(fail_on="ruim.mp3")
    )

    assert result.failure is None
    assert result.artifacts[0].metadata["trilha"] is None
    mixes = [call for call in runner.calls if call[-1].endswith("mix.wav")]
    assert len(mixes) == 2 and "-stream_loop" not in mixes[-1]
    gate = executor.validate(snapshot, plan, result)
    assert gate.approved and "trilha_ausente" in [f.code for f in gate.findings]


def test_bloco_que_nenhum_beat_cobre_vira_aviso(tmp_path):
    """Bloco antes do primeiro beat da seção não é narrado: palavras do roteiro
    somem do vídeo, e isso não pode passar calado."""
    from forge.services.persistencia import carregar_modelo

    snapshot = _snapshot(tmp_path, blocos=2)
    caminho = snapshot.run_dir / "video" / "midia.json"
    plano = carregar_modelo(caminho, PlanoMidia)
    plano.beats = [beat for beat in plano.beats if beat.bloco_id != "b001"]
    gravar_modelo(caminho, plano)
    sem_beat = snapshot.model_copy(update={"artifacts": [
        a for a in snapshot.artifacts if a.relative_path != "video/images/i001.png"
    ]})

    executor, plan, result, _ = _rodar(tmp_path, sem_beat)

    assert result.artifacts[0].metadata["blocos_sem_narracao"] == ["b001"]
    gate = executor.validate(sem_beat, plan, result)
    assert gate.approved and "blocos_sem_narracao" in [f.code for f in gate.findings]


def test_hash_da_etapa_e_estavel_depois_de_montar(tmp_path):
    """A montagem regrava a embalagem; o hash não pode depender do que ela escreve."""
    snapshot = _snapshot(tmp_path, blocos=2)
    _com_embalagem(snapshot)
    executor = _executor(tmp_path, RecordingRunner())
    plan = executor.prepare(snapshot)

    executor.execute(snapshot, plan, lambda **event: None)

    assert executor.prepare(snapshot).input_hash == plan.input_hash
