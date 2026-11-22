from __future__ import annotations

import json
from pydantic import BaseModel, Field
from typing import Any

from forge.domain.operacao import (
    ETAPAS, StageName, StageStatus, StageRun, Artifact, Event, Video,
    Run, WorkItem,
)
from forge.repositories.connection import Database
from forge.repositories.operacao import OperacaoRepository
from forge.repositories.eventos import EventosRepository

JSON_OBJECT = dict[str, Any]


class RunSummary(BaseModel):
    run: Run
    video: Video
    progress: float = Field(ge=0, le=1)
    current_stage: StageName | None


class StageView(BaseModel):
    stage_run: StageRun
    items: list[WorkItem]
    metrics: JSON_OBJECT = Field(default_factory=dict)


class RunView(RunSummary):
    stages: dict[str, StageView]
    artifacts: list[Artifact]


class RunPage(BaseModel):
    items: list[RunSummary]
    total: int
    limit: int
    offset: int


class EventPage(BaseModel):
    items: list[Event]
    next_before_id: int | None


class StudioQueryService:
    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def _summary(repo: OperacaoRepository, run: Run) -> RunSummary:
        stages = repo.current_stages(run.id)
        video = repo.get_video(run.video_id)
        if video is None:
            raise KeyError(run.video_id)
        progress = sum(s.progress for s in stages) / len(ETAPAS)
        current = next(
            (s.stage for s in stages if s.status is not StageStatus.SUCCEEDED),
            StageName.VALIDACAO if run.status.value == "completed" else None,
        )
        return RunSummary(
            run=run, video=video, progress=progress, current_stage=current
        )

    def list_queue(self, *, canal_id: str | None = None) -> list[RunSummary]:
        with self.db.connection() as conn:
            repo = OperacaoRepository(conn)
            return [self._summary(repo, run) for run in repo.list_queue(canal_id=canal_id)]

    def list_runs(self, *, limit: int = 50, offset: int = 0, canal_id: str | None = None) -> RunPage:
        with self.db.connection() as conn:
            repo = OperacaoRepository(conn)
            items = [
                self._summary(repo, run)
                for run in repo.list_runs(limit=limit, offset=offset, canal_id=canal_id)
            ]
            return RunPage(
                items=items, total=repo.count_runs(canal_id=canal_id), limit=limit, offset=offset
            )

    def get_run(self, run_id: str) -> RunView:
        with self.db.transaction() as conn:
            repo = OperacaoRepository(conn)
            run = repo.get_run(run_id)
            if run is None:
                raise KeyError(run_id)
            summary = self._summary(repo, run)
            current_stages = repo.current_stages(run_id)
            items = repo.list_current_work_items(run_id)
            metrics = EventosRepository(conn).latest_stage_metrics(run_id)
            by_stage_run = {
                stage.id: [item for item in items if item.stage_run_id == stage.id]
                for stage in current_stages
            }
            stages_dict = {}
            for stage in current_stages:
                stages_dict[stage.stage.value] = StageView(
                    stage_run=stage,
                    items=by_stage_run.get(stage.id, []),
                    metrics=metrics.get(stage.stage.value, {}),
                )
            return RunView(
                run=summary.run,
                video=summary.video,
                progress=summary.progress,
                current_stage=summary.current_stage,
                stages=stages_dict,
                artifacts=repo.list_artifacts(run_id, current_only=True),
            )

    def list_events(
        self, run_id: str, *, before_id: int | None = None, limit: int = 100
    ) -> EventPage:
        with self.db.connection() as conn:
            repo = OperacaoRepository(conn)
            if repo.get_run(run_id) is None:
                raise KeyError(run_id)
            items = EventosRepository(conn).page(
                run_id, before_id=before_id, limit=limit
            )
            return EventPage(
                items=items,
                next_before_id=items[0].id if len(items) == limit else None,
            )

    def events_after(
        self, cursor: int, *, run_id: str | None = None, limit: int = 200, canal_id: str | None = None
    ) -> list[Event]:
        with self.db.connection() as conn:
            return EventosRepository(conn).after(cursor, run_id=run_id, limit=limit, canal_id=canal_id)

    def list_artifacts(
        self, run_id: str, *, current_only: bool = True
    ) -> list[Artifact]:
        with self.db.connection() as conn:
            repo = OperacaoRepository(conn)
            if repo.get_run(run_id) is None:
                raise KeyError(run_id)
            return repo.list_artifacts(run_id, current_only=current_only)

    def get_artifact(self, artifact_id: str) -> Artifact:
        with self.db.connection() as conn:
            artifact = OperacaoRepository(conn).get_artifact(artifact_id)
            if artifact is None:
                raise KeyError(artifact_id)
            return artifact
