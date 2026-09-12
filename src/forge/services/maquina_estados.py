from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from forge.domain.operacao import RunStatus, StageStatus


class TransicaoInvalida(ValueError):
    """Raised when a run or stage status transition is not permitted."""


_RUN_TRANSITIONS: Mapping[RunStatus, frozenset[RunStatus]] = MappingProxyType(
    {
        RunStatus.QUEUED: frozenset({RunStatus.PREPARING, RunStatus.CANCELLED}),
        RunStatus.PREPARING: frozenset(
            {RunStatus.RUNNING, RunStatus.PAUSING, RunStatus.FAILED, RunStatus.INTERRUPTED}
        ),
        RunStatus.RUNNING: frozenset(
            {
                RunStatus.PAUSING,
                RunStatus.VALIDATING,
                RunStatus.FAILED,
                RunStatus.INTERRUPTED,
            }
        ),
        RunStatus.PAUSING: frozenset(
            {RunStatus.PAUSED, RunStatus.FAILED, RunStatus.INTERRUPTED}
        ),
        RunStatus.PAUSED: frozenset({RunStatus.QUEUED, RunStatus.CANCELLED}),
        RunStatus.VALIDATING: frozenset(
            {
                RunStatus.PAUSING,
                RunStatus.COMPLETED,
                RunStatus.FAILED,
                RunStatus.INTERRUPTED,
            }
        ),
        RunStatus.COMPLETED: frozenset(),
        RunStatus.FAILED: frozenset({RunStatus.QUEUED, RunStatus.CANCELLED}),
        RunStatus.INTERRUPTED: frozenset({RunStatus.QUEUED, RunStatus.CANCELLED}),
        RunStatus.CANCELLED: frozenset(),
    }
)

_STAGE_TRANSITIONS: Mapping[StageStatus, frozenset[StageStatus]] = MappingProxyType(
    {
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
)


def mudar_run(
    atual: RunStatus,
    destino: RunStatus,
    *,
    motivo: str | None = None,
) -> RunStatus:
    if not isinstance(atual, RunStatus) or not isinstance(destino, RunStatus):
        raise TransicaoInvalida("run: transicao invalida")

    if destino in _RUN_TRANSITIONS[atual] or (
        atual is RunStatus.COMPLETED
        and destino is RunStatus.QUEUED
        and motivo == "retry_stage"
    ):
        return destino
    raise TransicaoInvalida(f"run: {atual.value} -> {destino.value}")


def mudar_etapa(atual: StageStatus, destino: StageStatus) -> StageStatus:
    if not isinstance(atual, StageStatus) or not isinstance(destino, StageStatus):
        raise TransicaoInvalida("etapa: transicao invalida")

    if destino in _STAGE_TRANSITIONS[atual]:
        return destino
    raise TransicaoInvalida(f"etapa: {atual.value} -> {destino.value}")
