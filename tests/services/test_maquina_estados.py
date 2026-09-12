import pytest

from forge.domain.operacao import RunStatus, StageStatus
from forge.services.maquina_estados import TransicaoInvalida, mudar_etapa, mudar_run


def test_mudar_run_permite_running_para_pausing():
    assert mudar_run(RunStatus.RUNNING, RunStatus.PAUSING) is RunStatus.PAUSING


def test_mudar_run_completed_para_queued_exige_retry_stage():
    with pytest.raises(TransicaoInvalida):
        mudar_run(RunStatus.COMPLETED, RunStatus.QUEUED)

    assert (
        mudar_run(
            RunStatus.COMPLETED,
            RunStatus.QUEUED,
            motivo="retry_stage",
        )
        is RunStatus.QUEUED
    )


def test_mudar_etapa_permite_succeeded_para_invalidated():
    assert mudar_etapa(StageStatus.SUCCEEDED, StageStatus.INVALIDATED) is StageStatus.INVALIDATED


def test_mudar_etapa_rejeita_pending_para_succeeded():
    with pytest.raises(TransicaoInvalida, match="pending -> succeeded"):
        mudar_etapa(StageStatus.PENDING, StageStatus.SUCCEEDED)
