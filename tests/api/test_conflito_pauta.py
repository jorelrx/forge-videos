from datetime import UTC, datetime

import pytest

from forge.domain.execucao import ArtifactOutput
from forge.domain.operacao import StageName
from forge.domain.pauta import DecisaoConflitoPauta
from forge.services.control_plane import TransicaoInvalida
from forge.services.worker import StudioWorker

from .test_editorial import Etapa

APROVADA = {"aprovacao_id": "a1", "revisao": 7, "tema": "Adiar", "promessa": "Adiar é preguiça",
            "recorte": "A pia cheia", "abertura": "Abre na pia", "blocos": ["Cena"], "perguntas_pesquisa": ["Quem?"]}
CONFLITO = {"promessa": "Adiar é preguiça", "recorte": "A pia cheia", "explicacao": "A fonte liga adiar ao medo.",
            "evidencias": [{"path": "1/c1/p1", "titulo": "Livro", "trecho": "Adiar protege."}],
            "recorte_proposto": "O medo de ser avaliado", "promessa_proposta": "Adiar como proteção"}


def _preparar(services, settings):
    roteiro = Etapa()
    pesquisa = Etapa(ArtifactOutput(kind="conflito_pauta", relative_path="video/conflito-pauta.json",
                                    mime_type="application/json", metadata=CONFLITO))
    worker = StudioWorker(
        services.commands.db, worker_id="teste", lease_seconds=45,
        executors={StageName.PREPARACAO: Etapa(), StageName.PESQUISA: pesquisa, StageName.ROTEIRO: roteiro},
        now=lambda: datetime.now(UTC), runs_root=settings.studio_runs_dir,
    )
    _, run = services.commands.enqueue_video(
        tema="Adiar", tese="Adiar é preguiça", priority=50, workflow_version=1, git_commit="t",
        config_snapshot={"preset": "local-recomendado-v1", "pauta_aprovada": APROVADA},
    )
    worker.run_once()
    assert worker.run_once().status == "paused"
    artefato = next(a for a in services.queries.get_run(run.id).artifacts if a.kind == "conflito_pauta")
    return worker, roteiro, run.id, artefato.id


def test_aceitar_usa_recorte_proposto_e_preserva_aprovada(services, settings):
    worker, roteiro, run_id, artefato = _preparar(services, settings)
    assert services.commands.get_run(run_id).run.config_snapshot["aguardando_editorial"] == "conflito_pauta"
    run = services.commands.decidir_conflito_pauta(run_id, DecisaoConflitoPauta(artefato_id=artefato, acao="aceitar"))
    assert run.status == "queued"
    assert run.config_snapshot["pauta_decidida"]["recorte"] == "O medo de ser avaliado"
    assert run.config_snapshot["pauta_aprovada"] == APROVADA
    assert run.config_snapshot["decisao_pauta"]["acao"] == "aceitar"
    worker.run_once()
    assert roteiro.snapshots[0]["pauta_decidida"]["promessa"] == "Adiar como proteção"


def test_editar_usa_texto_do_criador(services, settings):
    _, _, run_id, artefato = _preparar(services, settings)
    run = services.commands.decidir_conflito_pauta(run_id, DecisaoConflitoPauta(
        artefato_id=artefato, acao="editar", promessa="Adiar também protege"))
    assert run.config_snapshot["pauta_decidida"]["promessa"] == "Adiar também protege"
    assert run.config_snapshot["pauta_decidida"]["recorte"] == "A pia cheia"


def test_cancelar_encerra_e_preserva_pauta(services, settings):
    _, _, run_id, artefato = _preparar(services, settings)
    run = services.commands.decidir_conflito_pauta(run_id, DecisaoConflitoPauta(artefato_id=artefato, acao="cancelar"))
    assert run.status == "cancelled"
    assert run.config_snapshot["pauta_aprovada"] == APROVADA
    assert "pauta_decidida" not in run.config_snapshot
    with pytest.raises(TransicaoInvalida):
        services.commands.decidir_conflito_pauta(run_id, DecisaoConflitoPauta(artefato_id=artefato, acao="aceitar"))


def test_editar_sem_texto_e_invalido():
    with pytest.raises(ValueError):
        DecisaoConflitoPauta(artefato_id="x", acao="editar")


def test_cancelar_registra_fim(services, settings):
    _, _, run_id, artefato = _preparar(services, settings)
    run = services.commands.decidir_conflito_pauta(run_id, DecisaoConflitoPauta(artefato_id=artefato, acao="cancelar"))
    assert run.finished_at is not None


def test_repetir_etapa_posterior_nao_pula_o_conflito(services, settings):
    _, _, run_id, _ = _preparar(services, settings)
    with pytest.raises(TransicaoInvalida):
        services.commands.request_retry_stage(run_id, StageName.ROTEIRO, idempotency_key="pular")
    run = services.commands.request_retry_stage(run_id, StageName.PESQUISA, idempotency_key="refazer")
    snapshot = services.commands.get_run(run_id).run.config_snapshot
    assert "aguardando_editorial" not in snapshot and snapshot["pauta_aprovada"] == APROVADA
