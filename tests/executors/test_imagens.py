"""Executor de imagens: um beat por item, arquivo dentro da run, 100% gate.

O cliente ComfyUI é injetado. O duplo aqui escreve um PNG de verdade, porque o
gate abre o arquivo com Pillow — um caminho fabricado não prova nada.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest
from PIL import Image

from forge.domain.execucao import RunSnapshot
from forge.domain.midia import Beat, PlanoMidia
from forge.domain.operacao import StageName
from forge.executors.imagens import ImageExecutor
from forge.infrastructure.config import Settings
from forge.services.persistencia import gravar_modelo


class FakeComfy:
    """Escreve um PNG real no destino que o executor indicar."""

    def __init__(self, *, size: tuple[int, int] = (1024, 576), fail_on: set[str] | None = None):
        self.size = size
        self.fail_on = fail_on or set()
        self.calls: list[tuple[str, int, Path]] = []

    def generate(self, prompt: str, seed: int = 42, *, dest: Path) -> Path:
        self.calls.append((prompt, seed, Path(dest)))
        if prompt in self.fail_on:
            raise RuntimeError(f"ComfyUI falhou em {prompt!r}")
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", self.size, (10, 20, 40)).save(dest)
        return Path(dest)

    def cache_key(self, prompt, seed, preset, loras, sampler=None) -> str:
        return "c" * 64


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        studio_runs_dir=tmp_path / "runs",
        output_dir=tmp_path / "roteiros",
        image_width=1024,
        image_height=576,
    )


def _snapshot(tmp_path: Path, *, beats: list[Beat] | None = None) -> RunSnapshot:
    root = tmp_path / "runs"
    run_dir = root / "run-1"
    (run_dir / "video").mkdir(parents=True, exist_ok=True)
    gravar_modelo(
        run_dir / "video" / "midia.json",
        PlanoMidia(
            beats=beats
            or [
                Beat(id="i001", bloco_id="b001", prompt="limiar cosmico"),
                Beat(id="i002", bloco_id="b002", prompt="sala vazia"),
            ]
        ),
    )
    return RunSnapshot(
        run_id="run-1",
        video_id="v1",
        tema="T",
        tese="Teste",
        stage=StageName.IMAGENS,
        attempt=1,
        output_root=root,
        run_dir=run_dir,
        config_snapshot={},
        artifacts=[],
        work_items=[],
    )


class NoopBroker:
    """Slot de GPU sem efeito: o teste não pode mexer nos serviços do operador."""

    def __init__(self) -> None:
        self.claims: list[str] = []

    @contextmanager
    def exclusivo(self, recurso: str):
        self.claims.append(recurso)
        yield


def _executor(tmp_path: Path, client) -> ImageExecutor:
    return ImageExecutor(client=client, settings=_settings(tmp_path), broker=NoopBroker())


class TestPlan:
    def test_plan_has_one_item_per_beat(self, tmp_path):
        plan = _executor(tmp_path, FakeComfy()).prepare(_snapshot(tmp_path))

        assert [item.item_key for item in plan.items] == ["i001", "i002"]

    def test_planned_payload_matches_the_child_projector_contract(self, tmp_path):
        """O projetor só aceita kind='imagem' com stage='imagens'; 'image' é
        recusado como protocolo inválido e derruba a etapa."""
        events: list[dict] = []
        _executor(tmp_path, FakeComfy()).run(
            _snapshot(tmp_path), lambda **event: events.append(event)
        )

        planned = [event for event in events if event["kind"] == "item.planned"]
        assert planned
        for event in planned:
            assert event["payload"]["kind"] == "imagem"
            assert event["payload"]["stage"] == "imagens"


class TestExecute:
    def test_writes_each_image_inside_the_run_and_emits_the_item_sequence(self, tmp_path):
        client = FakeComfy()
        snapshot = _snapshot(tmp_path)
        events: list[dict] = []
        executor = _executor(tmp_path, client)
        plan = executor.prepare(snapshot)

        result = executor.execute(snapshot, plan, lambda **event: events.append(event))

        assert result.current_items == 2
        assert result.total_items == 2
        assert result.failure is None

        for item_key in ("i001", "i002"):
            destino = snapshot.run_dir / "video" / "images" / f"{item_key}.png"
            assert destino.is_file(), f"imagem de {item_key} ausente"

        kinds = [event["kind"] for event in events]
        assert kinds.count("item.started") == 2
        assert kinds.count("artifact.created") == 2
        assert kinds.count("item.succeeded") == 2
        # item.started precede o artifact do mesmo item
        assert kinds.index("item.started") < kinds.index("artifact.created")

        for artifact in result.artifacts:
            assert not Path(artifact.relative_path).is_absolute()
            assert (snapshot.run_dir / artifact.relative_path).is_file()

    def test_artifact_carries_the_prompt_and_seed_in_metadata(self, tmp_path):
        snapshot = _snapshot(tmp_path)
        executor = _executor(tmp_path, FakeComfy())
        plan = executor.prepare(snapshot)

        result = executor.execute(snapshot, plan, lambda **event: None)

        primeiro = next(a for a in result.artifacts if a.item_key == "i001")
        assert primeiro.metadata["prompt"] == "limiar cosmico"
        assert primeiro.metadata["seed"] == 42

    def test_a_failing_beat_emits_item_failed_and_no_artifact(self, tmp_path):
        snapshot = _snapshot(tmp_path)
        executor = _executor(tmp_path, FakeComfy(fail_on={"sala vazia"}))
        events: list[dict] = []
        plan = executor.prepare(snapshot)

        result = executor.execute(snapshot, plan, lambda **event: events.append(event))

        assert [a.item_key for a in result.artifacts] == ["i001"]
        failed = [event for event in events if event["kind"] == "item.failed"]
        assert [event["payload"]["item_key"] for event in failed] == ["i002"]
        assert failed[0]["payload"]["failure_code"]
        assert result.current_items == 1


def test_item_failure_does_not_stop_other_images(tmp_path):
    client = FakeComfy(fail_on={"limiar cosmico"})
    snapshot = _snapshot(tmp_path)
    executor = _executor(tmp_path, client)
    result = executor.run(snapshot, lambda **event: None)
    assert len(client.calls) == 2
    assert [artifact.item_key for artifact in result.artifacts] == ["i002"]
    assert result.failure.code == "image_generation_failed"
    assert result.failure.retriable is True


def test_codex_quota_stops_batch_and_preserves_completed_images(tmp_path):
    from forge.services.codex import CodexUsageLimitError

    class QuotaClient(FakeComfy):
        def generate(self, prompt, seed=42, *, dest):
            if prompt == "sala vazia":
                self.calls.append((prompt, seed, Path(dest)))
                raise CodexUsageLimitError("Cota Codex esgotada; logs: teste")
            return super().generate(prompt, seed, dest=dest)

    client = QuotaClient()
    snapshot = _snapshot(tmp_path, beats=[
        Beat(id="i001", bloco_id="b001", prompt="limiar cosmico"),
        Beat(id="i002", bloco_id="b002", prompt="sala vazia"),
        Beat(id="i003", bloco_id="b003", prompt="nao tentar"),
    ])
    settings = _settings(tmp_path).model_copy(update={"image_provider": "codex"})
    executor = ImageExecutor(client=client, settings=settings)
    events = []
    result = executor.run(snapshot, lambda **event: events.append(event))

    assert len(client.calls) == 2
    assert result.current_items == 1
    assert result.total_items == 3
    assert [artifact.item_key for artifact in result.artifacts] == ["i001"]
    assert (snapshot.run_dir / "video/images/i001.png").is_file()
    assert result.failure.code == "codex_usage_limit"
    assert result.failure.failure_class.value == "capacity"
    assert result.failure.retriable is False
    assert "cota" in result.failure.recommended_action.lower()
    assert not result.gate.approved
    failed = [event for event in events if event["kind"] == "item.failed"]
    assert failed[0]["payload"]["failure_code"] == "codex_usage_limit"
    assert not any(event["kind"] == "item.started" and event["payload"]["item_key"] == "i003" for event in events)


class TestValidate:
    def test_approves_when_every_beat_has_an_image_at_the_expected_size(self, tmp_path):
        snapshot = _snapshot(tmp_path)
        executor = _executor(tmp_path, FakeComfy())
        plan = executor.prepare(snapshot)
        result = executor.execute(snapshot, plan, lambda **event: None)

        gate = executor.validate(snapshot, plan, result)

        assert gate.approved is True
        assert gate.findings == []

    def test_rejects_on_wrong_resolution(self, tmp_path):
        snapshot = _snapshot(tmp_path)
        executor = _executor(tmp_path, FakeComfy(size=(512, 512)))
        plan = executor.prepare(snapshot)
        result = executor.execute(snapshot, plan, lambda **event: None)

        gate = executor.validate(snapshot, plan, result)

        assert gate.approved is False
        assert {finding.code for finding in gate.findings} == {"image_resolution"}

    def test_rejects_when_a_beat_has_no_image(self, tmp_path):
        snapshot = _snapshot(tmp_path)
        executor = _executor(tmp_path, FakeComfy(fail_on={"sala vazia"}))
        plan = executor.prepare(snapshot)
        result = executor.execute(snapshot, plan, lambda **event: None)

        gate = executor.validate(snapshot, plan, result)

        assert gate.approved is False
        assert "images_incomplete" in {finding.code for finding in gate.findings}

    def test_rejects_when_the_file_was_deleted_after_execution(self, tmp_path):
        snapshot = _snapshot(tmp_path)
        executor = _executor(tmp_path, FakeComfy())
        plan = executor.prepare(snapshot)
        result = executor.execute(snapshot, plan, lambda **event: None)
        (snapshot.run_dir / "video" / "images" / "i001.png").unlink()

        gate = executor.validate(snapshot, plan, result)

        assert gate.approved is False
        assert "image_unreadable" in {finding.code for finding in gate.findings}


def test_codex_images_do_not_claim_local_gpu(tmp_path):
    class ForbiddenBroker:
        def exclusivo(self, resource):
            raise AssertionError('Backend remoto não pode tomar GPU')

    settings = _settings(tmp_path).model_copy(update={'image_provider': 'codex'})
    executor = ImageExecutor(client=FakeComfy(), settings=settings, broker=ForbiddenBroker())
    result = executor.run(_snapshot(tmp_path), lambda **event: None)
    assert result.gate.approved
    assert all(a.metadata['image_provider'] == 'codex' for a in result.artifacts)


def test_default_client_follows_selected_backend(tmp_path):
    from forge.executors.codex_images import CodexImageClient
    from forge.executors.comfy import ComfyClient

    assert isinstance(ImageExecutor(settings=_settings(tmp_path)).client, ComfyClient)
    from forge.executors.codex_native_images import NativeCodexImageClient
    assert isinstance(ImageExecutor(settings=_settings(tmp_path).model_copy(update={'image_provider':'codex'})).client, NativeCodexImageClient)
    assert isinstance(ImageExecutor(settings=_settings(tmp_path).model_copy(update={'image_provider':'codex', 'codex_transport':'cli'})).client, CodexImageClient)


# --- thumbnail: acabamento, nunca motivo para a etapa falhar ---

def _com_embalagem(snapshot: RunSnapshot, *, texto: str = "O aplauso mente") -> None:
    from forge.domain.embalagem import Embalagem, ThumbnailProposta

    gravar_modelo(
        snapshot.run_dir / "video" / "embalagem.json",
        Embalagem(
            thumbnail=ThumbnailProposta(texto=texto, prompt="lone figure on a stage"),
            descricao="Abertura.",
        ),
    )


def _rodar(tmp_path, client, snapshot):
    executor = _executor(tmp_path, client)
    plan = executor.prepare(snapshot)
    result = executor.execute(snapshot, plan, lambda **event: None)
    return executor, plan, result


def test_thumbnail_sai_em_1280x720_quando_ha_embalagem(tmp_path):
    snapshot = _snapshot(tmp_path)
    _com_embalagem(snapshot)

    executor, plan, result = _rodar(tmp_path, FakeComfy(), snapshot)

    thumbs = [a for a in result.artifacts if a.kind == "thumbnail.jpg"]
    assert [(a.relative_path, a.mime_type, a.item_key) for a in thumbs] == [
        ("video/thumbnail.jpg", "image/jpeg", None)
    ]
    with Image.open(snapshot.run_dir / "video" / "thumbnail.jpg") as imagem:
        assert imagem.size == (1280, 720)
    # A thumbnail não é um beat: não entra na contagem nem no gate de 1024x576.
    assert result.current_items == 2 and result.total_items == 2
    gate = executor.validate(snapshot, plan, result)
    assert gate.approved and gate.findings == []


def test_sem_embalagem_nao_ha_thumbnail(tmp_path):
    client = FakeComfy()
    snapshot = _snapshot(tmp_path)

    _, _, result = _rodar(tmp_path, client, snapshot)

    assert all(not a.kind.startswith("thumbnail") for a in result.artifacts)
    assert len(client.calls) == 2


def test_falha_na_thumbnail_nao_falha_a_etapa(tmp_path):
    snapshot = _snapshot(tmp_path)
    _com_embalagem(snapshot)
    client = FakeComfy(fail_on={"lone figure on a stage"})

    executor, plan, result = _rodar(tmp_path, client, snapshot)

    assert result.failure is None
    gate = executor.validate(snapshot, plan, result)
    assert gate.approved
    assert [f.code for f in gate.findings] == ["thumbnail_ausente"]


def test_beat_falho_nao_gasta_geracao_com_thumbnail(tmp_path):
    snapshot = _snapshot(tmp_path)
    _com_embalagem(snapshot)
    client = FakeComfy(fail_on={"sala vazia"})

    _, _, result = _rodar(tmp_path, client, snapshot)

    assert result.failure is not None
    assert "lone figure on a stage" not in [prompt for prompt, _, _ in client.calls]


def test_base_da_thumbnail_e_reaproveitada_entre_tentativas(tmp_path):
    snapshot = _snapshot(tmp_path)
    _com_embalagem(snapshot)
    client = FakeComfy()

    _rodar(tmp_path, client, snapshot)
    _rodar(tmp_path, client, snapshot)

    geracoes = [prompt for prompt, _, _ in client.calls if prompt == "lone figure on a stage"]
    assert len(geracoes) == 1


def test_texto_da_thumbnail_entra_no_hash_da_etapa(tmp_path):
    snapshot = _snapshot(tmp_path)
    executor = _executor(tmp_path, FakeComfy())
    sem = executor.prepare(snapshot).input_hash
    _com_embalagem(snapshot, texto="O aplauso mente")
    um = executor.prepare(snapshot).input_hash
    _com_embalagem(snapshot, texto="Outra frase")
    outro = executor.prepare(snapshot).input_hash

    assert len({sem, um, outro}) == 3
    assert [item.item_key for item in executor.prepare(snapshot).items] == ["i001", "i002"]
