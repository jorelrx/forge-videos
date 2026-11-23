from pathlib import Path

from forge.domain.execucao import RunSnapshot
from forge.domain.fluxo_geracao import FLUXOS_INICIAIS
from forge.domain.operacao import StageName
from forge.executors.preparacao import PreparationExecutor, PreparationInput
from forge.repositories.connection import Database
from forge.repositories.eventos import EventosRepository
from forge.repositories.operacao import OperacaoRepository
from forge.repositories.schema import init_db
from forge.services.persistencia import carregar_modelo
from forge.services.worker import StageContext, StudioWorker


def _snapshot(tmp_path: Path, **changes) -> RunSnapshot:
    output_root = tmp_path / "runs"
    values = {
        "run_id": "run-1",
        "video_id": "video-1",
        "tema": "A consciência",
        "tese": "A consciência organiza a experiência.",
        "stage": StageName.PREPARACAO,
        "attempt": 1,
        "output_root": output_root,
        "run_dir": output_root / "run-1",
        "config_snapshot": {},
        "artifacts": [],
        "work_items": [],
    }
    values.update(changes)
    return RunSnapshot(**values)


def _events():
    seen = []

    def emit(**event):
        seen.append(event)

    return seen, emit


def test_preparation_creates_only_canonical_run_tree(tmp_path):
    snapshot = _snapshot(tmp_path)
    events, emit = _events()

    result = PreparationExecutor().run(snapshot, emit)

    assert (snapshot.run_dir / "video" / "input.json").is_file()
    assert result.gate.approved
    assert [event["payload"]["relative_path"] for event in events if event["kind"] == "artifact.created"] == [
        "video/input.json"
    ]
    assert sorted(path.relative_to(snapshot.run_dir).as_posix() for path in snapshot.run_dir.rglob("*")) == [
        "video",
        "video/input.json",
    ]


def test_preparation_rejects_unknown_snapshot_fields_before_writing(tmp_path):
    snapshot = _snapshot(tmp_path, config_snapshot={"api_key": "secret"})

    result = PreparationExecutor().run(snapshot, lambda **event: None)

    assert not result.gate.approved
    assert result.gate.code == "preparation_snapshot_invalid"
    assert not snapshot.run_dir.exists()


def test_preparation_freezes_flow_separately_from_studio_preset(tmp_path):
    fluxo = FLUXOS_INICIAIS[1]
    snapshot = _snapshot(tmp_path, config_snapshot={"fluxo_geracao": fluxo.model_dump()})
    assert PreparationExecutor().run(snapshot, lambda **event: None).gate.approved
    persisted = carregar_modelo(snapshot.run_dir / "video/input.json", PreparationInput)
    assert persisted.fluxo_geracao == fluxo
    assert persisted.preset.preset == "local-recomendado-v1"


def test_preparation_gate_rejects_missing_persisted_snapshot(tmp_path):
    snapshot = _snapshot(tmp_path)
    executor = PreparationExecutor()
    plan = executor.prepare(snapshot)
    result = executor.execute(snapshot, plan, lambda **event: None)
    (snapshot.run_dir / "video" / "input.json").unlink()

    gate = executor.validate(snapshot, plan, result)

    assert not gate.approved
    assert gate.code == "preparation_snapshot_invalid"


def test_preparation_event_registers_input_in_catalog_without_work_item(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)
    with db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        _, run = repo.create_video_and_run(
            tema="A consciência", tese="A consciência organiza a experiência.",
            priority=50, config_snapshot={"preset": "local-recomendado-v1"},
            workflow_version=1, git_commit="abc123",
        )
        stage = next(item for item in repo.current_stages(run.id) if item.stage is StageName.PREPARACAO)
        video = repo.get_video(run.video_id)

    run_dir = tmp_path / "runs" / run.id
    snapshot = _snapshot(
        tmp_path,
        run_id=run.id,
        video_id=run.video_id,
        tema=video.tema,
        tese=video.tese,
        output_root=run_dir.parent,
        run_dir=run_dir,
        config_snapshot=run.config_snapshot,
    )
    worker = StudioWorker(db, worker_id="worker-test", lease_seconds=60, executors={})
    event_sink = worker._event_sink(
        StageContext(run=run, stage_run=stage, video=video, run_dir=run_dir)
    )

    result = PreparationExecutor().run(snapshot, event_sink)

    with db.connection() as conn:
        artifacts = OperacaoRepository(conn).list_artifacts(run.id)
        events = EventosRepository(conn).after(0, run_id=run.id)
    assert result.gate.approved
    assert (run_dir / "video" / "input.json").is_file()
    assert len(artifacts) == 1
    assert artifacts[0].stage_run_id == stage.id
    assert artifacts[0].work_item_id is None
    assert artifacts[0].relative_path == "video/input.json"
    assert [event.kind for event in events] == ["artifact.created"]


def test_preparation_accepts_board_brief_and_records_it(tmp_path):
    aprovada = {"aprovacao_id": "a1", "revisao": 7, "tema": "Encerrar o expediente", "promessa": "Um ritual curto",
                "recorte": "A entrega incompleta", "blocos": ["A cena"], "perguntas_pesquisa": ["O que diz Sêneca?"]}
    sem_pauta = PreparationExecutor().prepare(_snapshot(tmp_path))
    for extra in ({}, {"pauta_decidida": {**aprovada, "recorte": "Outro recorte"},
                       "decisao_pauta": {"acao": "aceitar"}}):
        snapshot = _snapshot(tmp_path, config_snapshot={"preset": "local-recomendado-v1",
                                                          "pauta_aprovada": aprovada, **extra})
        result = PreparationExecutor().run(snapshot, _events()[1])
        assert result.gate.approved
        gravado = carregar_modelo(snapshot.run_dir / "video" / "input.json", PreparationInput)
        assert gravado.pauta_episodio.perguntas_pesquisa == ["O que diz Sêneca?"]
        assert gravado.pauta_episodio.recorte == ("Outro recorte" if extra else "A entrega incompleta")
    assert PreparationExecutor().prepare(_snapshot(tmp_path)).input_hash == sem_pauta.input_hash
