from __future__ import annotations


def test_pitch_tracks_fundamental_when_upper_harmonics_dominate(tmp_path):
    import numpy as np
    import soundfile as sf
    from forge.executors.audio import AudioExecutor

    rate = 24000
    time = np.arange(rate, dtype=np.float64) / rate
    fundamental = 150.0
    plain = 0.5 * np.sin(2 * np.pi * fundamental * time)
    bright = 0.1 * np.sin(2 * np.pi * fundamental * time)
    bright += 0.5 * np.sin(2 * np.pi * fundamental * 5 * time)
    for name, samples in (("plain", plain), ("bright", bright)):
        path = tmp_path / f"{name}.wav"
        sf.write(path, samples, rate)
        measured = AudioExecutor._f0(path, rate)
        assert abs(measured - fundamental) < 3, (name, measured)


def test_pitch_reports_zero_for_silence(tmp_path):
    import numpy as np
    import soundfile as sf
    from forge.executors.audio import AudioExecutor

    path = tmp_path / "silence.wav"
    sf.write(path, np.zeros(24000), 24000)
    assert AudioExecutor._f0(path, 24000) == 0.0


def test_voice_gate_accepts_small_pitch_variation_but_flags_octave_change():
    from types import SimpleNamespace
    from forge.executors.audio import AudioExecutor

    executor = AudioExecutor(settings=Settings(_env_file=None))
    samples = {str(index): SimpleNamespace(metadata={"F0": pitch})
               for index, pitch in enumerate([130, 132, 134, 136, 145])}
    assert executor._voice_outlier_keys(samples) == []
    samples["other_voice"] = SimpleNamespace(metadata={"F0": 268})
    assert executor._voice_outlier_keys(samples) == ["other_voice"]

from contextlib import contextmanager
from pathlib import Path
import wave

import pytest

from forge.domain.execucao import RunSnapshot
from forge.domain.midia import BlocoNarracao, PlanoMidia
from forge.domain.operacao import ItemStatus, StageName, WorkItem
from forge.executors.audio import AudioExecutor
from forge.executors.audio_generate import SERVIDOR_INDISPONIVEL, AudioOutcome, classify_audio_failure
from forge.infrastructure.config import Settings
from forge.services.persistencia import gravar_modelo


def _wav(path: Path, *, sample_rate: int = 24000, channels: int = 1, frames: int = 2400):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(b"\0\0" * channels * frames)


def _snapshot(tmp_path: Path, *, work_items=(), stage=StageName.AUDIO) -> RunSnapshot:
    root = tmp_path / "runs"
    snapshot = RunSnapshot(
        run_id="run-1", video_id="video-1", tema="Tema", tese="Tese", stage=stage,
        attempt=1, output_root=root, run_dir=root / "run-1", config_snapshot={},
        artifacts=[], work_items=list(work_items),
    )
    gravar_modelo(snapshot.run_dir / "video" / "midia.json", PlanoMidia(blocos=[
        BlocoNarracao(id="b001", secao="A", texto="Primeiro texto."),
        BlocoNarracao(id="b002", secao="A", texto="Segundo texto."),
        BlocoNarracao(id="b003", secao="B", texto="Terceiro texto."),
    ]))
    return snapshot


class Broker:
    def __init__(self, eventos=None):
        self.calls = []
        self.eventos = eventos if eventos is not None else []

    @contextmanager
    def exclusivo(self, resource):
        self.calls.append(resource)
        self.eventos.append("broker.entra")
        yield
        self.eventos.append("broker.sai")


class ServidorFalso:
    def __init__(self, backend, eventos):
        self.backend = backend
        self.url = f"falso://{backend}"
        self.reinicios = 0
        self.saiu = False
        self.eventos = eventos

    def __enter__(self):
        self.eventos.append(f"servidor.{self.backend}.entra")
        return self

    def __exit__(self, *exc):
        self.saiu = True
        self.eventos.append(f"servidor.{self.backend}.sai")

    def reiniciar(self):
        self.reinicios += 1


class Fabrica:
    """`servidor_factory` falso; `falha[backend]` é a exceção da subida."""

    def __init__(self, falha=None, eventos=None):
        self.falha = falha or {}
        self.servidores = []
        self.eventos = eventos if eventos is not None else []

    def __call__(self, backend, pasta):
        if backend in self.falha:
            raise self.falha[backend]
        servidor = ServidorFalso(backend, self.eventos)
        self.servidores.append(servidor)
        return servidor

    @property
    def backends(self):
        return [s.backend for s in self.servidores]


_MENSAGENS = {
    "max_tokens": "Higgs TTS generation reached max_tokens before EOC",
    "oom": "ggml_vulkan: Device memory allocation of size 1 failed",
    "500": "could not open WAV input: C:/x.wav",
}


class Cliente:
    """`roteiro(item_key, seed, backend)` devolve "ok", "silencio", "caiu",
    "max_tokens", "oom" ou "500"; o padrão é "ok"."""

    def __init__(self, roteiro=None, eventos=None):
        self.roteiro = roteiro or (lambda key, seed, backend: "ok")
        self.calls = []
        self.eventos = eventos

    def synthesize(self, request, servidor, destino):
        self.calls.append((request.item_key, request.seed, servidor.backend))
        if self.eventos is not None:
            self.eventos.append(f"pedido.{request.item_key}.{servidor.backend}")
        acao = self.roteiro(request.item_key, request.seed, servidor.backend)
        if acao == "caiu":
            return AudioOutcome.failed(request.item_key, SERVIDOR_INDISPONIVEL, "conexão recusada")
        if acao in _MENSAGENS:
            return AudioOutcome(
                item_key=request.item_key,
                failure=classify_audio_failure(_MENSAGENS[acao], status=500, item_key=request.item_key),
            )
        path = Path(destino) / f"{request.item_key}.wav"
        _fala(path, silencio=5.0 if acao == "silencio" else 0.3)
        return AudioOutcome.succeeded(request.item_key, path)


def _fala(path: Path, *, silencio: float = 0.0, rate: int = 24000, frequencia: int = 200) -> None:
    """Tom de 0,5 s, `silencio` segundos mudos, tom de 0,5 s."""
    import math
    import struct

    path.parent.mkdir(parents=True, exist_ok=True)
    meio = rate // 2
    tom = [int(9000 * math.sin(2 * math.pi * frequencia * i / rate)) for i in range(meio)]
    amostras = tom + [0] * int(silencio * rate) + tom
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(struct.pack(f"<{len(amostras)}h", *amostras))


def _settings(tmp_path: Path, **kwargs) -> Settings:
    return Settings(_env_file=None, audio_generate_dir=tmp_path / "audio-generate", **kwargs)


def _executor(tmp_path, cliente=None, fabrica=None, broker=None, **settings_kwargs):
    return AudioExecutor(
        settings=_settings(tmp_path, **settings_kwargs),
        client=cliente or Cliente(),
        broker=broker or Broker(),
        servidor_factory=fabrica or Fabrica(),
    )


def _de(eventos, kind):
    return [e for e in eventos if e["kind"] == kind]


def test_prepare_reads_blocks_and_uses_canonical_hash(tmp_path):
    snapshot = _snapshot(tmp_path)
    plan = AudioExecutor(settings=_settings(tmp_path)).prepare(snapshot)

    assert plan.stage is StageName.AUDIO
    assert [item.item_key for item in plan.items] == ["b001", "b002", "b003"]
    assert plan.items[0].input_hash == "3b1ef995af6583446a3d99eff4d91b0f04bde41df1bb4bef4fd06224ffe49e0b"


def test_prepare_rejects_non_audio_context(tmp_path):
    with pytest.raises(ValueError, match="audio"):
        AudioExecutor(settings=_settings(tmp_path)).prepare(_snapshot(tmp_path, stage=StageName.IMAGENS))


def test_tts_request_receives_only_spoken_text(tmp_path):
    from forge.domain.execucao import WorkItemPlan

    item = WorkItemPlan(
        item_key="b001",
        input={"texto": "fala", "referencias": ["12/ch1/p2"], "prompt_visual": "imagem"},
        input_hash="a" * 64,
    )
    request = AudioExecutor._request(item)
    assert request.text == "fala"
    assert not hasattr(request, "referencias")
    assert not hasattr(request, "prompt_visual")


def test_validate_rejects_incomplete_current_outputs(tmp_path):
    snapshot = _snapshot(tmp_path)
    executor = AudioExecutor(settings=_settings(tmp_path))
    plan = executor.prepare(snapshot)
    _wav(snapshot.run_dir / "video" / "audio" / "b001.wav")
    result = executor._result_for_paths(snapshot, plan, {"b001": snapshot.run_dir / "video" / "audio" / "b001.wav"})

    gate = executor.validate(snapshot, plan, result)

    assert not gate.approved
    assert gate.code == "audio_incomplete"
    assert gate.metrics["current_items"] == 1
    assert gate.metrics["total_items"] == 3


def test_validate_rejects_non_mono_or_wrong_sample_rate(tmp_path):
    snapshot = _snapshot(tmp_path)
    executor = AudioExecutor(settings=_settings(tmp_path))
    plan = executor.prepare(snapshot)
    paths = {}
    for key in ("b001", "b002", "b003"):
        path = snapshot.run_dir / "video" / "audio" / f"{key}.wav"
        _wav(path, sample_rate=22050 if key == "b001" else 24000, channels=2 if key == "b002" else 1)
        paths[key] = path

    gate = executor.validate(snapshot, plan, executor._result_for_paths(snapshot, plan, paths))

    assert {finding.code for finding in gate.findings} >= {"audio_sample_rate", "audio_channels"}


def test_previous_attempt_output_is_reused_from_parent_verified_snapshot(tmp_path):
    snapshot = _snapshot(tmp_path)
    reusable = snapshot.run_dir / "video" / "audio" / "b001.wav"
    _wav(reusable)
    from forge.domain.operacao import Artifact
    from forge.domain.execucao import ReusableOutput
    from forge.executors.plano_midia import hash_json

    artifact = Artifact(
        id="prior-audio", run_id=snapshot.run_id, stage_run_id="previous-stage",
        work_item_id="previous-item", kind="audio.wav",
        relative_path="video/audio/b001.wav",
        sha256=__import__("hashlib").sha256(reusable.read_bytes()).hexdigest(),
        size_bytes=reusable.stat().st_size, mime_type="audio/wav", metadata={"seed": 42},
        is_current=True, created_at="2026-09-13T00:00:00Z",
    )
    client, events = Cliente(), []
    result = _executor(tmp_path, client).run(
        snapshot.model_copy(update={"reusable_outputs": [ReusableOutput(
            artifact=artifact,
            input_hash=hash_json({"id": "b001", "secao": "A", "texto": "Primeiro texto."}),
        )]}),
        lambda **event: events.append(event),
    )

    assert client.calls == [("b002", 42, "vulkan"), ("b003", 42, "vulkan")]
    assert [event["kind"] for event in events if event["payload"].get("item_key") == "b001"] == [
        "item.planned", "item.started", "artifact.created", "item.succeeded"
    ]
    assert result.current_items == 3


def test_cada_trecho_e_um_pedido_e_um_servidor_por_etapa(tmp_path):
    cliente, fabrica, broker, eventos = Cliente(), Fabrica(), Broker(), []
    result = _executor(tmp_path, cliente, fabrica, broker).run(
        _snapshot(tmp_path), lambda **e: eventos.append(e)
    )

    assert cliente.calls == [("b001", 42, "vulkan"), ("b002", 42, "vulkan"), ("b003", 42, "vulkan")]
    assert fabrica.backends == ["vulkan"]
    assert fabrica.servidores[0].saiu
    assert broker.calls == ["tts"]
    assert result.gate.approved and result.current_items == 3
    assert [e["payload"]["item_key"] for e in _de(eventos, "artifact.created")] == ["b001", "b002", "b003"]
    assert all(e["payload"]["backend"] == "vulkan" for e in _de(eventos, "item.succeeded"))


def test_max_tokens_troca_de_seed_na_gpu_antes_da_cpu(tmp_path):
    cliente = Cliente(lambda k, s, b: "max_tokens" if (k, s) == ("b002", 42) else "ok")
    fabrica = Fabrica()
    result = _executor(tmp_path, cliente, fabrica).run(_snapshot(tmp_path), lambda **e: None)

    assert ("b002", 1042, "vulkan") in cliente.calls
    assert fabrica.backends == ["vulkan"]
    assert result.gate.approved
    assert next(a for a in result.artifacts if a.item_key == "b002").metadata["seed"] == 1042


def test_trecho_esgotado_na_gpu_vai_para_cpu(tmp_path):
    cliente = Cliente(lambda k, s, b: "max_tokens" if k == "b002" and b == "vulkan" else "ok")
    fabrica, eventos = Fabrica(), []
    result = _executor(tmp_path, cliente, fabrica).run(_snapshot(tmp_path), lambda **e: eventos.append(e))

    assert [c for c in cliente.calls if c[0] == "b002"] == [
        ("b002", 42, "vulkan"), ("b002", 1042, "vulkan"), ("b002", 2042, "vulkan"), ("b002", 42, "cpu"),
    ]
    assert fabrica.backends == ["vulkan", "cpu"]
    assert all(s.saiu for s in fabrica.servidores)
    iniciado = _de(eventos, "audio.recovery.started")[0]["payload"]
    assert iniciado["item_key"] == "b002" and iniciado["queued"] is True
    assert iniciado["original_failure_code"] == "tts_max_tokens_before_eoc"
    concluido = _de(eventos, "audio.recovery.completed")[0]["payload"]
    assert concluido["status"] == "succeeded" and concluido["backend"] == "cpu"
    sucesso = next(e for e in _de(eventos, "item.succeeded") if e["payload"]["item_key"] == "b002")
    assert sucesso["payload"]["backend"] == "cpu"
    assert result.gate.approved


def test_trecho_que_falha_tambem_na_cpu_falha_sem_artefato(tmp_path):
    cliente = Cliente(lambda k, s, b: "max_tokens" if k == "b002" else "ok")
    eventos = []
    result = _executor(tmp_path, cliente).run(_snapshot(tmp_path), lambda **e: eventos.append(e))

    falha = _de(eventos, "item.failed")[0]["payload"]
    assert falha["item_key"] == "b002" and falha["failure_code"] == "tts_max_tokens_before_eoc"
    assert falha["backend"] == "cpu" and falha["original_backend"] == "vulkan"
    assert _de(eventos, "audio.recovery.completed")[0]["payload"]["status"] == "failed"
    assert not result.gate.approved and result.gate.code == "audio_incomplete"


def test_silencio_longo_conta_como_seed_ruim(tmp_path):
    cliente = Cliente(lambda k, s, b: "silencio" if (k, s) == ("b002", 42) else "ok")
    fabrica = Fabrica()
    result = _executor(tmp_path, cliente, fabrica).run(_snapshot(tmp_path), lambda **e: None)

    final = next(a for a in result.artifacts if a.item_key == "b002")
    assert final.metadata["seed"] == 1042 and final.metadata["silencio_max"] < 1.0
    assert fabrica.backends == ["vulkan"]
    assert result.gate.approved


def test_silencio_que_nenhuma_seed_cura_mantem_artefato_e_gate_reprova(tmp_path):
    cliente = Cliente(lambda k, s, b: "silencio" if k == "b002" else "ok")
    result = _executor(tmp_path, cliente).run(_snapshot(tmp_path), lambda **e: None)

    assert [(s, b) for k, s, b in cliente.calls if k == "b002"] == [
        (42, "vulkan"), (1042, "vulkan"), (2042, "vulkan"), (42, "cpu"), (1042, "cpu"), (2042, "cpu"),
    ]
    assert not result.gate.approved
    achado = next(f for f in result.gate.findings if f.code == "audio_silence")
    assert achado.item_key == "b002" and achado.details["silencio_max"] > 4.5


def test_erro_500_generico_falha_na_hora_sem_trocar_seed_nem_cpu(tmp_path):
    cliente = Cliente(lambda k, s, b: "500" if k == "b002" else "ok")
    fabrica, eventos = Fabrica(), []
    _executor(tmp_path, cliente, fabrica).run(_snapshot(tmp_path), lambda **e: eventos.append(e))

    assert [c for c in cliente.calls if c[0] == "b002"] == [("b002", 42, "vulkan")]
    assert fabrica.backends == ["vulkan"]
    assert _de(eventos, "item.failed")[0]["payload"]["failure_code"] == "tts_process_failed"
    assert _de(eventos, "audio.recovery.started") == []


def test_servidor_cai_reinicia_uma_vez_e_repete_o_trecho(tmp_path):
    quedas = iter([True])
    cliente = Cliente(lambda k, s, b: "caiu" if k == "b002" and next(quedas, False) else "ok")
    fabrica = Fabrica()
    result = _executor(tmp_path, cliente, fabrica).run(_snapshot(tmp_path), lambda **e: None)

    assert fabrica.servidores[0].reinicios == 1
    assert [c for c in cliente.calls if c[0] == "b002"] == [("b002", 42, "vulkan")] * 2
    assert result.gate.approved


def test_oom_tambem_reinicia_o_servidor(tmp_path):
    quedas = iter([True])
    cliente = Cliente(lambda k, s, b: "oom" if k == "b001" and next(quedas, False) else "ok")
    fabrica = Fabrica()
    result = _executor(tmp_path, cliente, fabrica).run(_snapshot(tmp_path), lambda **e: None)

    assert fabrica.servidores[0].reinicios == 1
    assert result.gate.approved


def test_servidor_cai_duas_vezes_restantes_falham_sem_ir_para_cpu(tmp_path):
    cliente = Cliente(lambda k, s, b: "ok" if k == "b001" else "caiu")
    fabrica, eventos = Fabrica(), []
    _executor(tmp_path, cliente, fabrica).run(_snapshot(tmp_path), lambda **e: eventos.append(e))

    falhas = {e["payload"]["item_key"]: e["payload"]["failure_code"] for e in _de(eventos, "item.failed")}
    assert falhas == {"b002": "tts_servidor_indisponivel", "b003": "tts_servidor_indisponivel"}
    assert fabrica.backends == ["vulkan"]
    assert fabrica.servidores[0].reinicios == 1
    assert [c for c in cliente.calls if c[0] == "b003"] == []


def test_servidor_principal_que_nao_sobe_falha_todos_os_trechos(tmp_path):
    from forge.executors.audiocpp_server import ServidorIndisponivel

    fabrica, eventos = Fabrica(falha={"vulkan": ServidorIndisponivel("porta ocupada")}), []
    result = _executor(tmp_path, fabrica=fabrica).run(_snapshot(tmp_path), lambda **e: eventos.append(e))

    assert {e["payload"]["failure_code"] for e in _de(eventos, "item.failed")} == {"tts_servidor_indisponivel"}
    assert len(_de(eventos, "item.failed")) == 3
    assert not result.gate.approved


def test_contrato_quebrado_na_gpu_falha_a_etapa(tmp_path):
    from forge.executors.audiocpp_server import ContratoServidorQuebrado

    cliente = Cliente()
    fabrica = Fabrica(falha={"vulkan": ContratoServidorQuebrado("sonda 200")})
    executor = _executor(tmp_path, cliente, fabrica)
    snapshot = _snapshot(tmp_path)

    result = executor.execute(snapshot, executor.prepare(snapshot), lambda **e: None)

    assert result.failure is not None and result.failure.code == "tts_contrato_servidor"
    assert cliente.calls == []


def test_seed_sobrescrita_da_abertura_e_a_primeira(tmp_path):
    cliente, fabrica = Cliente(), Fabrica()
    _executor(tmp_path, cliente, fabrica, tts_seed=43).run(_snapshot(tmp_path), lambda **e: None)

    assert {s for _, s, _ in cliente.calls} == {43}
    assert fabrica.backends == ["vulkan"]


def test_seed_sobrescrita_igual_a_alternativa_nao_repete(tmp_path):
    cliente = Cliente(lambda k, s, b: "max_tokens" if k == "b001" and b == "vulkan" else "ok")
    _executor(tmp_path, cliente, tts_seed=1042).run(_snapshot(tmp_path), lambda **e: None)

    assert [s for k, s, b in cliente.calls if k == "b001" and b == "vulkan"] == [1042, 2042]


def _snapshot_cinco(tmp_path):
    snapshot = _snapshot(tmp_path)
    media = PlanoMidia.model_validate_json((snapshot.run_dir / "video" / "midia.json").read_text())
    media.blocos.extend([
        BlocoNarracao(id="b004", secao="B", texto="Quarto texto."),
        BlocoNarracao(id="b005", secao="B", texto="Quinto texto."),
    ])
    gravar_modelo(snapshot.run_dir / "video" / "midia.json", media)
    return snapshot


class _ClienteVoz(Cliente):
    """b003 sai uma oitava acima na seed padrão (outra voz)."""

    def synthesize(self, request, servidor, destino):
        self.calls.append((request.item_key, request.seed, servidor.backend))
        if self.eventos is not None:
            self.eventos.append(f"pedido.{request.item_key}.{servidor.backend}")
        path = Path(destino) / f"{request.item_key}.wav"
        aguda = request.item_key == "b003" and request.seed == 42
        _fala(path, silencio=0.3, frequencia=440 if aguda else 200)
        return AudioOutcome.succeeded(request.item_key, path)


def test_outliers_de_voz_rodam_dentro_do_slot_tts(tmp_path):
    ordem = []
    cliente = _ClienteVoz(eventos=ordem)
    fabrica, broker = Fabrica(eventos=ordem), Broker(eventos=ordem)
    result = _executor(tmp_path, cliente, fabrica, broker).run(_snapshot_cinco(tmp_path), lambda **e: None)

    assert ("b003", 1042, "vulkan") in cliente.calls
    assert result.gate.approved
    regerado = len(ordem) - 1 - ordem[::-1].index("pedido.b003.vulkan")
    assert ordem.index("broker.entra") < regerado < ordem.index("servidor.vulkan.sai") < ordem.index("broker.sai")


def test_outlier_com_servidor_indisponivel_e_pulado(tmp_path):
    cliente = _ClienteVoz()
    executor = _executor(tmp_path, cliente)
    original = cliente.synthesize

    def synthesize(request, servidor, destino):
        if request.seed != 42:
            return AudioOutcome.failed(request.item_key, SERVIDOR_INDISPONIVEL, "caiu")
        return original(request, servidor, destino)

    cliente.synthesize = synthesize
    result = executor.run(_snapshot_cinco(tmp_path), lambda **e: None)

    assert any(f.code == "audio_voice_divergence" for f in result.gate.findings)


def test_backend_cpu_usa_so_servidor_cpu(tmp_path):
    cliente = Cliente(lambda k, s, b: "max_tokens" if k == "b002" else "ok")
    fabrica, eventos = Fabrica(), []
    _executor(tmp_path, cliente, fabrica, tts_backend="cpu").run(
        _snapshot(tmp_path), lambda **e: eventos.append(e)
    )

    assert fabrica.backends == ["cpu"]
    assert {b for _, _, b in cliente.calls} == {"cpu"}
    assert _de(eventos, "audio.recovery.started") == []
    assert _de(eventos, "item.failed")[0]["payload"]["item_key"] == "b002"
