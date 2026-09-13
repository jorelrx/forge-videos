from abc import ABC, abstractmethod

from forge.domain.execucao import (
    GateResult, RunSnapshot, StageChildResult, StageExecutionResult, StagePlan,
)
from forge.services.worker import EventSink


class StageImplementation(ABC):
    @abstractmethod
    def prepare(self, context: RunSnapshot) -> StagePlan:
        raise NotImplementedError

    @abstractmethod
    def execute(
        self, context: RunSnapshot, plan: StagePlan, emit: EventSink
    ) -> StageExecutionResult:
        raise NotImplementedError

    @abstractmethod
    def validate(
        self, context: RunSnapshot, plan: StagePlan, result: StageExecutionResult
    ) -> GateResult:
        raise NotImplementedError

    def run(self, context: RunSnapshot, emit: EventSink) -> StageChildResult:
        plan = self.prepare(context)
        for item in plan.items:
            emit(
                kind="item.planned", level="info", message="Item planejado",
                payload=item.model_dump(mode="json"),
            )
        execution = self.execute(context, plan, emit)
        gate = self.validate(context, plan, execution)
        return StageChildResult(**execution.model_dump(), gate=gate)
