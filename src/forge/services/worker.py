from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from forge.domain.operacao import (
    JSON_OBJECT,
    Run,
    RunStatus,
    StageName,
    StageResult,
    StageRun,
    StageStatus,
)
from forge.repositories.connection import Database
from forge.repositories.eventos import EventosRepository
from forge.repositories.operacao import OperacaoRepository
from forge.services.control_plane import ControlPlaneService
from forge.services.maquina_estados import mudar_etapa, mudar_run


@dataclass(frozen=True, slots=True)
class StageContext:
    run: Run
    stage_run: StageRun


class EventSink(Protocol):
    def __call__(
        self,
        *,
        kind: str,
        level: str,
        message: str,
        payload: JSON_OBJECT,
    ) -> None: ...


class StageExecutor(Protocol):
    def execute(self, context: StageContext, emit: EventSink) -> StageResult: ...


class StudioWorker:
    def __init__(
        self,
        db: Database,
        *,
        worker_id: str,
        lease_seconds: int,
        executors: Mapping[StageName, StageExecutor],
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.db = db
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.executors = executors
        self.now = now or (lambda: datetime.now(UTC))
        self.control_plane = ControlPlaneService(db, now=self.now)

    def run_once(self) -> Run | None:
        self.control_plane.interrupt_expired()
        run = self.control_plane.claim_next(
            self.worker_id, lease_seconds=self.lease_seconds
        )
        if run is None:
            return None

        stage = self._current_pending_stage(run.id)
        if stage is None:
            return run
        executor = self.executors.get(stage.stage)
        if executor is None:
            self._append_event(
                run_id=run.id,
                stage_run_id=stage.id,
                kind="executor_missing",
                level="error",
                message="Executor ausente para etapa",
                payload={"stage": stage.stage.value},
            )
            return run

        context = self._start_stage(run, stage)
        try:
            result = executor.execute(context, self._event_sink(context))
        except Exception as error:  # noqa: BLE001 - executor boundary persists failures
            result = StageResult(
                failure_code="executor_error",
                failure_message=str(error) or type(error).__name__,
            )
        return self._finish_stage(context, result)

    def _current_pending_stage(self, run_id: str) -> StageRun | None:
        with self.db.connection() as conn:
            return next(
                (
                    stage
                    for stage in OperacaoRepository(conn).current_stages(run_id)
                    if stage.status is StageStatus.PENDING
                ),
                None,
            )

    def _start_stage(self, run: Run, stage: StageRun) -> StageContext:
        now = self.now()
        with self.db.transaction(immediate=True) as conn:
            operacao = OperacaoRepository(conn)
            started_run = operacao.save_run(
                run.model_copy(update={"status": mudar_run(run.status, RunStatus.RUNNING)})
            )
            started_stage = operacao.save_stage(
                stage.model_copy(
                    update={
                        "status": mudar_etapa(stage.status, StageStatus.RUNNING),
                        "started_at": now,
                    }
                )
            )
            EventosRepository(conn).append(
                kind="stage.started",
                level="info",
                message="Etapa iniciada",
                payload={"stage": stage.stage.value, "attempt": stage.attempt},
                run_id=run.id,
                stage_run_id=stage.id,
            )
        return StageContext(run=started_run, stage_run=started_stage)

    def _finish_stage(self, context: StageContext, result: StageResult) -> Run:
        now = self.now()
        progress = (
            result.current_items / result.total_items if result.total_items else 1.0
        )
        with self.db.transaction(immediate=True) as conn:
            operacao = OperacaoRepository(conn)
            run = operacao.get_run(context.run.id)
            stage = next(
                item
                for item in operacao.current_stages(context.run.id)
                if item.id == context.stage_run.id
            )
            if result.failed:
                assert result.failure_code is not None
                assert result.failure_message is not None
                finished_run = operacao.save_run(
                    run.model_copy(
                        update={
                            "status": mudar_run(run.status, RunStatus.FAILED),
                            "failure_code": result.failure_code,
                            "failure_message": result.failure_message,
                            "finished_at": now,
                        }
                    )
                )
                finished_stage = stage.model_copy(
                    update={
                        "status": mudar_etapa(stage.status, StageStatus.FAILED),
                        "current_items": result.current_items,
                        "total_items": result.total_items,
                        "progress": progress,
                        "gate_status": result.gate_status,
                        "finished_at": now,
                        "failure_code": result.failure_code,
                        "failure_message": result.failure_message,
                    }
                )
                event_kind = "stage.failed"
                event_level = "error"
                event_message = "Etapa falhou"
                event_payload: JSON_OBJECT = {"failure_code": result.failure_code}
            else:
                finished_run = run
                finished_stage = stage.model_copy(
                    update={
                        "status": mudar_etapa(stage.status, StageStatus.SUCCEEDED),
                        "current_items": result.current_items,
                        "total_items": result.total_items,
                        "progress": progress,
                        "gate_status": result.gate_status,
                        "finished_at": now,
                    }
                )
                event_kind = "stage.succeeded"
                event_level = "info"
                event_message = "Etapa concluída"
                event_payload = {"gate_status": result.gate_status}
            operacao.save_stage(finished_stage)
            EventosRepository(conn).append(
                kind=event_kind,
                level=event_level,
                message=event_message,
                payload=event_payload,
                run_id=context.run.id,
                stage_run_id=context.stage_run.id,
            )
            return finished_run

    def _event_sink(self, context: StageContext) -> EventSink:
        def emit(
            *, kind: str, level: str, message: str, payload: JSON_OBJECT
        ) -> None:
            self._append_event(
                run_id=context.run.id,
                stage_run_id=context.stage_run.id,
                kind=kind,
                level=level,
                message=message,
                payload=payload,
            )

        return emit

    def _append_event(
        self,
        *,
        run_id: str,
        stage_run_id: str,
        kind: str,
        level: str,
        message: str,
        payload: JSON_OBJECT,
    ) -> None:
        with self.db.transaction(immediate=True) as conn:
            EventosRepository(conn).append(
                kind=kind,
                level=level,
                message=message,
                payload=payload,
                run_id=run_id,
                stage_run_id=stage_run_id,
            )


__all__ = [
    "EventSink",
    "StageContext",
    "StageExecutor",
    "StageResult",
    "StudioWorker",
]
