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


class TestExecute:
    def test_builds_one_clip_per_beat_then_concats_and_muxes(self, tmp_path):
        runner = RecordingRunner()
        snapshot = _snapshot(tmp_path, blocos=2)
        executor = _executor(tmp_path, runner)
        plan = executor.prepare(snapshot)

        result = executor.execute(snapshot, plan, lambda **event: None)

        # 2 clipes + 1 concat de vídeo + 1 concat de áudio + 1 mux
        assert len(runner.calls) == 5
        assert (snapshot.run_dir / "video" / "final.mp4").is_file()
        assert [a.kind for a in result.artifacts] == ["video/final.mp4"]

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

        # 10 s de narração divididos entre 2 beats
        for call in runner.calls[:2]:
            assert call[call.index("-t") + 1].startswith("5.0")

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
        assert gate.findings == []

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
