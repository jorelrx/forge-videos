from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel

from forge.domain.operacao import (
    Artifact,
    Command,
    CommandStatus,
    CommandType,
    Event,
    Run,
    RunStatus,
    StageName,
    StageRun,
    StageStatus,
    Video,
    dependentes_de,
)
from forge.repositories.comandos import ComandosRepository
from forge.repositories.connection import Database
from forge.repositories.eventos import EventosRepository
from forge.repositories.operacao import OperacaoRepository
from forge.services.maquina_estados import TransicaoInvalida, mudar_etapa, mudar_run


class HistoricoSomenteLeitura(Exception):
    pass


class RunDetail(BaseModel):
    run: Run
    stages: list[StageRun]
    artifacts: list[Artifact]


class ControlPlaneService:
    def __init__(
        self, db: Database, *, now: Callable[[], datetime] | None = None
    ) -> None:
        self.db = db
        self.now = now or (lambda: datetime.now(UTC))

    def enqueue_video(
        self,
        *,
        tema: str,
        tese: str | None,
        priority: int,
        config_snapshot: dict,
        workflow_version: int,
        git_commit: str,
    ) -> tuple[Video, Run]:
        with self.db.transaction(immediate=True) as conn:
            operacao = OperacaoRepository(conn)
            eventos = EventosRepository(conn)
            video, run = operacao.create_video_and_run(
                tema=tema,
                tese=tese,
                priority=priority,
                config_snapshot=config_snapshot,
                workflow_version=workflow_version,
                git_commit=git_commit,
            )
            eventos.append(
                kind="run.queued",
                level="info",
                message="Run enfileirada",
                payload={},
                run_id=run.id,
            )
            return video, run

    def get_run(self, run_id: str) -> RunDetail:
        with self.db.transaction() as conn:
            operacao = OperacaoRepository(conn)
            run = operacao.get_run(run_id)
            if run is None:
                raise KeyError(run_id)
            return RunDetail(
                run=run,
                stages=operacao.current_stages(run_id),
                artifacts=operacao.list_artifacts(run_id, current_only=True),
            )

    def list_queue(self) -> list[Run]:
        with self.db.connection() as conn:
            return OperacaoRepository(conn).list_queue()

    def list_runs(self, *, limit: int = 50, offset: int = 0) -> list[Run]:
        with self.db.connection() as conn:
            return OperacaoRepository(conn).list_runs(limit=limit, offset=offset)

    def events_after(
        self, cursor: int, *, run_id: str | None = None, limit: int = 200
    ) -> list[Event]:
        with self.db.connection() as conn:
            return EventosRepository(conn).after(cursor, run_id=run_id, limit=limit)

    def claim_next(self, worker_id: str, *, lease_seconds: int) -> Run | None:
        with self.db.transaction(immediate=True) as conn:
            operacao = OperacaoRepository(conn)
            run = operacao.claim_next(worker_id, lease_seconds=lease_seconds)
            if run is None:
                return None
            EventosRepository(conn).append(
                kind="run.claimed",
                level="info",
                message="Run atribuída a worker",
                payload={"worker_id": worker_id, "lease_seconds": lease_seconds},
                run_id=run.id,
            )
            return run

    def renew_lease(
        self, run_id: str, worker_id: str, *, lease_seconds: int
    ) -> Run | None:
        with self.db.transaction(immediate=True) as conn:
            operacao = OperacaoRepository(conn)
            run = operacao.renew_lease(
                run_id, worker_id, lease_seconds=lease_seconds
            )
            if run is None:
                return None
            EventosRepository(conn).append(
                kind="run.lease_renewed",
                level="info",
                message="Lease da run renovado",
                payload={"worker_id": worker_id, "lease_seconds": lease_seconds},
                run_id=run.id,
            )
            return run

    def interrupt_expired(self) -> list[Run]:
        with self.db.transaction(immediate=True) as conn:
            runs = OperacaoRepository(conn).interrupt_expired(self.now())
            eventos = EventosRepository(conn)
            for run in runs:
                eventos.append(
                    kind="run.interrupted",
                    level="warning",
                    message="Lease da run expirou",
                    payload={"reason": "lease_expired"},
                    run_id=run.id,
                )
            return runs

    def interrupt_orphan_stage(self, run_id: str, stage_id: str) -> Run | None:
        """Interrompe a run cuja etapa corrente ficou RUNNING sem dono.

        O lease ainda é válido (o dono morreu com ele, ou outro processo assumiu
        a run), então `interrupt_expired` não vê nada. Sem esta transição a
        etapa ficaria RUNNING para sempre e o `resume` do painel não a
        resetaria — `request_resume` só reinicia PAUSED/FAILED/INTERRUPTED —, o
        que deixava a run travada.
        """
        with self.db.transaction(immediate=True) as conn:
            operacao = OperacaoRepository(conn)
            run = operacao.get_run(run_id)
            if run is None:
                return None
            stage = next(
                (item for item in operacao.current_stages(run_id) if item.id == stage_id),
                None,
            )
            if stage is None or stage.status is not StageStatus.RUNNING:
                return None
            now = self.now()
            operacao.save_stage(
                stage.model_copy(
                    update={"status": mudar_etapa(stage.status, StageStatus.INTERRUPTED),
                            "finished_at": now}
                )
            )
            interrupted = operacao.save_run(
                run.model_copy(
                    update={
                        "status": mudar_run(run.status, RunStatus.INTERRUPTED),
                        "lease_owner": None,
                        "lease_expires_at": None,
                    }
                )
            )
            EventosRepository(conn).append(
                kind="run.interrupted",
                level="warning",
                message="Etapa corrente sem dono; run interrompida",
                payload={"reason": "owner_lost", "stage": stage.stage.value},
                run_id=run_id,
                stage_run_id=stage.id,
            )
            return interrupted

    def request_pause(self, run_id: str, *, idempotency_key: str) -> Command:
        with self.db.transaction(immediate=True) as conn:
            operacao = OperacaoRepository(conn)
            self._require_mutable_run(operacao, run_id)
            comandos = ComandosRepository(conn)
            command, created = comandos.create_idempotent(
                run_id=run_id,
                type=CommandType.PAUSE,
                stage=None,
                idempotency_key=idempotency_key,
                status=CommandStatus.ACCEPTED,
            )
            if not created:
                return command

            run = operacao.get_run(run_id)
            paused = run.model_copy(
                update={
                    "status": mudar_run(run.status, RunStatus.PAUSING),
                    "pause_requested_at": self.now(),
                }
            )
            operacao.save_run(paused)
            EventosRepository(conn).append(
                kind="command.pause_requested",
                level="info",
                message="Pausa solicitada",
                payload={},
                run_id=run_id,
            )
            return command

    def request_resume(self, run_id: str, *, idempotency_key: str) -> Command:
        with self.db.transaction(immediate=True) as conn:
            operacao = OperacaoRepository(conn)
            self._require_mutable_run(operacao, run_id)
            comandos = ComandosRepository(conn)
            command, created = comandos.create_idempotent(
                run_id=run_id,
                type=CommandType.RESUME,
                stage=None,
                idempotency_key=idempotency_key,
                status=CommandStatus.APPLIED,
            )
            if not created:
                return command

            run = operacao.get_run(run_id)
            resumable_stage = next(
                (
                    stage
                    for stage in operacao.current_stages(run_id)
                    if stage.status
                    in {
                        StageStatus.PAUSED,
                        StageStatus.FAILED,
                        StageStatus.INTERRUPTED,
                    }
                ),
                None,
            )
            queued = run.model_copy(
                update={
                    "status": mudar_run(run.status, RunStatus.QUEUED),
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "pause_requested_at": None,
                    "finished_at": None,
                    "failure_code": None,
                    "failure_message": None,
                }
            )
            if resumable_stage is not None:
                operacao.save_stage(
                    resumable_stage.model_copy(
                        update={
                            "status": mudar_etapa(
                                resumable_stage.status, StageStatus.PENDING
                            ),
                            "current_items": 0,
                            "total_items": 0,
                            "progress": 0,
                            "gate_status": None,
                            "started_at": None,
                            "finished_at": None,
                            "failure_code": None,
                            "failure_message": None,
                        }
                    )
                )
            operacao.save_run(queued)
            EventosRepository(conn).append(
                kind="run.queued",
                level="info",
                message="Run retomada e enfileirada",
                payload={},
                run_id=run_id,
            )
            return command

    def request_retry_stage(
        self, run_id: str, stage: StageName, *, idempotency_key: str
    ) -> Command:
        with self.db.transaction(immediate=True) as conn:
            operacao = OperacaoRepository(conn)
            self._require_mutable_run(operacao, run_id)
            comandos = ComandosRepository(conn)
            command, created = comandos.create_idempotent(
                run_id=run_id,
                type=CommandType.RETRY_STAGE,
                stage=stage,
                idempotency_key=idempotency_key,
                status=CommandStatus.APPLIED,
            )
            if not created:
                return command

            run = operacao.get_run(run_id)
            if run.status not in {
                RunStatus.PAUSED,
                RunStatus.FAILED,
                RunStatus.COMPLETED,
            }:
                raise TransicaoInvalida(f"run: {run.status.value} -> queued")
            queued_status = mudar_run(
                run.status, RunStatus.QUEUED, motivo="retry_stage"
            )
            dependent_stages = dependentes_de(stage)
            operacao.invalidate_from_stage(run_id, stage)
            operacao.invalidate_artifacts(run_id, dependent_stages)
            operacao.save_run(
                run.model_copy(
                    update={
                        "status": queued_status,
                        "lease_owner": None,
                        "lease_expires_at": None,
                        "pause_requested_at": None,
                        "finished_at": None,
                        "failure_code": None,
                        "failure_message": None,
                    }
                )
            )
            eventos = EventosRepository(conn)
            eventos.append(
                kind="stages.invalidated",
                level="info",
                message="Etapas invalidadas para nova tentativa",
                payload={"stages": [item.value for item in dependent_stages]},
                run_id=run_id,
            )
            eventos.append(
                kind="run.queued",
                level="info",
                message="Run reenfileirada para nova tentativa",
                payload={},
                run_id=run_id,
            )
            return command

    @staticmethod
    def _require_run(operacao: OperacaoRepository, run_id: str) -> Run:
        run = operacao.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        return run

    def _require_mutable_run(self, operacao: OperacaoRepository, run_id: str) -> Run:
        run = self._require_run(operacao, run_id)
        if run.is_read_only:
            raise HistoricoSomenteLeitura(
                "run importada é histórico somente-leitura e não aceita comandos"
            )
        return run


__all__ = ["ControlPlaneService", "HistoricoSomenteLeitura", "RunDetail", "TransicaoInvalida"]
