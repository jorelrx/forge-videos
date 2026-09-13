from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread
from typing import Protocol

from pydantic import Field

from forge.domain.operacao import (
    JSON_OBJECT,
    Artifact,
    Command,
    CommandStatus,
    CommandType,
    Run,
    RunStatus,
    StageName,
    StageResult,
    StageRun,
    StageStatus,
    Video,
    WorkItem,
)
from forge.repositories.comandos import ComandosRepository
from forge.repositories.connection import Database
from forge.repositories.eventos import EventosRepository
from forge.repositories.operacao import OperacaoRepository
from forge.services.control_plane import ControlPlaneService
from forge.services.maquina_estados import mudar_etapa, mudar_run


@dataclass(frozen=True, slots=True)
class StageContext:
    run: Run
    stage_run: StageRun
    cancel_event: Event | None = None
    video: Video | None = None
    run_dir: Path | None = None
    artifacts: list[Artifact] = Field(default_factory=list)
    work_items: list[WorkItem] = Field(default_factory=list)


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


class LeaseHeartbeat:
    def __init__(
        self,
        db: Database,
        *,
        run_id: str,
        worker_id: str,
        lease_seconds: int,
    ) -> None:
        self.db = db
        self.run_id = run_id
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.ownership_lost = Event()

    def tick(self) -> bool:
        with self.db.transaction(immediate=True) as conn:
            renewed = OperacaoRepository(conn).renew_lease(
                self.run_id,
                self.worker_id,
                lease_seconds=self.lease_seconds,
            )
        if renewed is None:
            self.ownership_lost.set()
            return False
        return True

    @contextmanager
    def daemon(self, *, interval_seconds: float) -> Iterator[LeaseHeartbeat]:
        daemon = LeaseHeartbeatDaemon(self, interval_seconds=interval_seconds)
        daemon.start()
        try:
            yield self
        finally:
            daemon.stop()


class LeaseHeartbeatDaemon:
    def __init__(self, heartbeat: LeaseHeartbeat, *, interval_seconds: float) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.heartbeat = heartbeat
        self.interval_seconds = interval_seconds
        self._stopped = Event()
        self._thread = Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        self._thread.join()

    def _run(self) -> None:
        while not self._stopped.wait(self.interval_seconds):
            if not self.heartbeat.tick():
                return


class StudioWorker:
    def __init__(
        self,
        db: Database,
        *,
        worker_id: str,
        lease_seconds: int,
        executors: Mapping[StageName, StageExecutor],
        now: Callable[[], datetime] | None = None,
        heartbeat_seconds: float = 5,
    ) -> None:
        self.db = db
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.executors = executors
        self.now = now or (lambda: datetime.now(UTC))
        self.heartbeat_seconds = heartbeat_seconds
        self.control_plane = ControlPlaneService(db, now=self.now)

    def run_once(self) -> Run | None:
        self.control_plane.interrupt_expired()
        run = self._active_run_owned_by_worker()
        if run is None:
            run = self.control_plane.claim_next(
                self.worker_id, lease_seconds=self.lease_seconds
            )
        if run is None:
            return None

        stage = self._current_pending_stage(run.id)
        if stage is None:
            return run
        paused_run = self._pause_before_stage(run, stage)
        if paused_run is not None:
            return paused_run
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

        started = self._start_stage(run, stage)
        if isinstance(started, Run):
            return started
        context = started
        heartbeat = LeaseHeartbeat(
            self.db,
            run_id=context.run.id,
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
        )
        context = replace(context, cancel_event=heartbeat.ownership_lost)
        if not heartbeat.tick():
            return self._run_after_ownership_loss(context.run.id)
        try:
            with heartbeat.daemon(interval_seconds=self.heartbeat_seconds):
                result = executor.execute(context, self._event_sink(context))
        except Exception as error:  # noqa: BLE001 - executor boundary persists failures
            result = StageResult(
                failure_code="executor_error",
                failure_message=str(error) or type(error).__name__,
            )
        if heartbeat.ownership_lost.is_set() or not heartbeat.tick():
            return self._run_after_ownership_loss(context.run.id)
        return self._finish_stage(context, result)

    def _active_run_owned_by_worker(self) -> Run | None:
        with self.db.connection() as conn:
            return OperacaoRepository(conn).active_owned_by(self.worker_id)

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

    def _start_stage(self, run: Run, stage: StageRun) -> StageContext | Run:
        now = self.now()
        with self.db.transaction(immediate=True) as conn:
            operacao = OperacaoRepository(conn)
            current_run = operacao.get_run(run.id)
            current_stage = next(
                item
                for item in operacao.current_stages(run.id)
                if item.id == stage.id
            )
            if (
                current_run is not None
                and current_run.lease_owner == self.worker_id
                and current_run.status is RunStatus.PAUSING
            ):
                paused_run = self._apply_accepted_pause(
                    operacao, conn, current_run, current_stage
                )
                if paused_run is not None:
                    return paused_run
            assert current_run is not None
            started_run = operacao.save_run(
                current_run.model_copy(
                    update={
                        "status": (
                            RunStatus.RUNNING
                            if current_run.status is RunStatus.RUNNING
                            else mudar_run(current_run.status, RunStatus.RUNNING)
                        )
                    }
                )
            )
            started_stage = operacao.save_stage(
                current_stage.model_copy(
                    update={
                        "status": mudar_etapa(
                            current_stage.status, StageStatus.RUNNING
                        ),
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

    def _pause_before_stage(self, run: Run, stage: StageRun) -> Run | None:
        with self.db.transaction(immediate=True) as conn:
            operacao = OperacaoRepository(conn)
            current_run = operacao.get_run(run.id)
            if (
                current_run is None
                or current_run.lease_owner != self.worker_id
                or current_run.status is not RunStatus.PAUSING
            ):
                return None
            return self._apply_accepted_pause(operacao, conn, current_run, stage)

    def _apply_accepted_pause(
        self,
        operacao: OperacaoRepository,
        conn,
        run: Run,
        stage: StageRun,
    ) -> Run | None:
        pause_command = self._accepted_pause(ComandosRepository(conn), run.id)
        if pause_command is None:
            return None
        paused_run = operacao.save_run(
            run.model_copy(
                update={
                    "status": mudar_run(run.status, RunStatus.PAUSED),
                    "lease_owner": None,
                    "lease_expires_at": None,
                }
            )
        )
        ComandosRepository(conn).set_status(
            pause_command.id, CommandStatus.APPLIED, result=pause_command.result
        )
        EventosRepository(conn).append(
            kind="run.paused",
            level="info",
            message="Run pausada entre etapas",
            payload={"stage": stage.stage.value},
            run_id=run.id,
            stage_run_id=stage.id,
        )
        return paused_run

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
            if run.lease_owner != self.worker_id:
                return run
            pause_command = self._accepted_pause(ComandosRepository(conn), run.id)
            if pause_command is not None:
                paused_run = operacao.save_run(
                    run.model_copy(
                        update={
                            "status": mudar_run(run.status, RunStatus.PAUSED),
                            "lease_owner": None,
                            "lease_expires_at": None,
                        }
                    )
                )
                operacao.save_stage(
                    stage.model_copy(
                        update={
                            "status": mudar_etapa(
                                mudar_etapa(stage.status, StageStatus.PAUSING),
                                StageStatus.PAUSED,
                            ),
                            "current_items": result.current_items,
                            "total_items": result.total_items,
                            "progress": progress,
                            "gate_status": result.gate_status,
                        }
                    )
                )
                ComandosRepository(conn).set_status(
                    pause_command.id, CommandStatus.APPLIED, result=pause_command.result
                )
                EventosRepository(conn).append(
                    kind="run.paused",
                    level="info",
                    message="Run pausada no limite seguro da etapa",
                    payload={"stage": stage.stage.value},
                    run_id=context.run.id,
                    stage_run_id=context.stage_run.id,
                )
                return paused_run
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
                            "lease_owner": None,
                            "lease_expires_at": None,
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
            if not result.failed and stage.stage is StageName.VALIDACAO:
                validating_run = operacao.save_run(
                    run.model_copy(
                        update={
                            "status": mudar_run(run.status, RunStatus.VALIDATING),
                        }
                    )
                )
                EventosRepository(conn).append(
                    kind="run.validating",
                    level="info",
                    message="Run em validação final",
                    payload={},
                    run_id=context.run.id,
                    stage_run_id=context.stage_run.id,
                )
                finished_run = operacao.save_run(
                    validating_run.model_copy(
                        update={
                            "status": mudar_run(
                                validating_run.status, RunStatus.COMPLETED
                            ),
                            "finished_at": now,
                            "lease_owner": None,
                            "lease_expires_at": None,
                        }
                    )
                )
                EventosRepository(conn).append(
                    kind="run.completed",
                    level="info",
                    message="Run concluída",
                    payload={},
                    run_id=context.run.id,
                    stage_run_id=context.stage_run.id,
                )
            return finished_run

    def _run_after_ownership_loss(self, run_id: str) -> Run | None:
        self.control_plane.interrupt_expired()
        with self.db.connection() as conn:
            return OperacaoRepository(conn).get_run(run_id)

    @staticmethod
    def _accepted_pause(
        comandos: ComandosRepository, run_id: str
    ) -> Command | None:
        row = comandos.conn.execute(
            """
            SELECT id FROM commands
            WHERE run_id = ? AND type = ? AND status = ?
            ORDER BY created_at ASC, id ASC
            LIMIT 1
            """,
            (run_id, CommandType.PAUSE.value, CommandStatus.ACCEPTED.value),
        ).fetchone()
        return comandos.get(row["id"]) if row is not None else None

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
    "LeaseHeartbeat",
    "LeaseHeartbeatDaemon",
    "StageContext",
    "StageExecutor",
    "StageResult",
    "StudioWorker",
]
