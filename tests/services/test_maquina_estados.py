import pytest

from forge.domain.operacao import RunStatus, StageStatus
from forge.services.maquina_estados import (
    _RUN_TRANSITIONS,
    _STAGE_TRANSITIONS,
    TransicaoInvalida,
    mudar_etapa,
    mudar_run,
)

RUN_DESTINOS_PERMITIDOS = {
    RunStatus.QUEUED: frozenset({RunStatus.PREPARING, RunStatus.CANCELLED}),
    RunStatus.PREPARING: frozenset(
        {RunStatus.RUNNING, RunStatus.PAUSING, RunStatus.FAILED, RunStatus.INTERRUPTED}
    ),
    RunStatus.RUNNING: frozenset(
        {RunStatus.PAUSING, RunStatus.VALIDATING, RunStatus.FAILED, RunStatus.INTERRUPTED}
    ),
    RunStatus.PAUSING: frozenset(
        {RunStatus.PAUSED, RunStatus.FAILED, RunStatus.INTERRUPTED}
    ),
    RunStatus.PAUSED: frozenset({RunStatus.QUEUED, RunStatus.CANCELLED}),
    RunStatus.VALIDATING: frozenset(
        {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.INTERRUPTED}
    ),
    RunStatus.FAILED: frozenset({RunStatus.QUEUED, RunStatus.CANCELLED}),
    RunStatus.INTERRUPTED: frozenset({RunStatus.QUEUED, RunStatus.CANCELLED}),
    RunStatus.COMPLETED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
}

STAGE_DESTINOS_PERMITIDOS = {
    StageStatus.PENDING: frozenset({StageStatus.RUNNING, StageStatus.INVALIDATED}),
    StageStatus.RUNNING: frozenset(
        {
            StageStatus.SUCCEEDED,
            StageStatus.FAILED,
            StageStatus.PAUSING,
            StageStatus.INTERRUPTED,
        }
    ),
    StageStatus.PAUSING: frozenset(
        {StageStatus.PAUSED, StageStatus.FAILED, StageStatus.INTERRUPTED}
    ),
    StageStatus.PAUSED: frozenset({StageStatus.PENDING, StageStatus.INVALIDATED}),
    StageStatus.FAILED: frozenset({StageStatus.PENDING, StageStatus.INVALIDATED}),
    StageStatus.INTERRUPTED: frozenset({StageStatus.PENDING, StageStatus.INVALIDATED}),
    StageStatus.SUCCEEDED: frozenset({StageStatus.INVALIDATED}),
    StageStatus.INVALIDATED: frozenset({StageStatus.PENDING}),
}


@pytest.mark.parametrize(
    ("atual", "destinos_permitidos"), RUN_DESTINOS_PERMITIDOS.items()
)
def test_mudar_run_cobre_matriz_completa(atual, destinos_permitidos):
    for destino in RunStatus:
        if destino in destinos_permitidos:
            assert mudar_run(atual, destino) is destino
        else:
            with pytest.raises(
                TransicaoInvalida,
                match=rf"^run: {atual.value} -> {destino.value}$",
            ):
                mudar_run(atual, destino)


def test_mudar_run_completed_para_queued_exige_retry_stage():
    with pytest.raises(TransicaoInvalida, match=r"^run: completed -> queued$"):
        mudar_run(RunStatus.COMPLETED, RunStatus.QUEUED)

    assert (
        mudar_run(
            RunStatus.COMPLETED,
            RunStatus.QUEUED,
            motivo="retry_stage",
        )
        is RunStatus.QUEUED
    )


@pytest.mark.parametrize(
    ("atual", "destinos_permitidos"), STAGE_DESTINOS_PERMITIDOS.items()
)
def test_mudar_etapa_cobre_matriz_completa(atual, destinos_permitidos):
    for destino in StageStatus:
        if destino in destinos_permitidos:
            assert mudar_etapa(atual, destino) is destino
        else:
            with pytest.raises(
                TransicaoInvalida,
                match=rf"^etapa: {atual.value} -> {destino.value}$",
            ):
                mudar_etapa(atual, destino)


@pytest.mark.parametrize(
    ("atual", "destino"),
    [
        ("queued", RunStatus.PREPARING),
        (RunStatus.QUEUED, "preparing"),
    ],
)
def test_mudar_run_rejeita_strings_cruas(atual, destino):
    with pytest.raises(TransicaoInvalida, match=r"^run: transicao invalida$"):
        mudar_run(atual, destino)


@pytest.mark.parametrize(
    ("atual", "destino"),
    [
        ("pending", StageStatus.RUNNING),
        (StageStatus.PENDING, "running"),
    ],
)
def test_mudar_etapa_rejeita_strings_cruas(atual, destino):
    with pytest.raises(TransicaoInvalida, match=r"^etapa: transicao invalida$"):
        mudar_etapa(atual, destino)


@pytest.mark.parametrize(
    "transicoes, origem",
    [
        (_RUN_TRANSITIONS, RunStatus.QUEUED),
        (_STAGE_TRANSITIONS, StageStatus.PENDING),
    ],
)
def test_mapas_de_transicao_sao_imutaveis(transicoes, origem):
    with pytest.raises(TypeError):
        transicoes[origem] = frozenset()
