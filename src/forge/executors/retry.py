"""Bounded retries for stage operations."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, TypeVar

from forge.domain.execucao import FailureClass

T = TypeVar("T")


class ExecutionFailure(RuntimeError):
    """An operation failure carrying its stable detail and class."""

    def __init__(
        self,
        detail: Any,
        failure_class: FailureClass = FailureClass.PROCESS,
    ) -> None:
        self.detail = detail
        self.failure_class = failure_class
        super().__init__(str(detail))


class RetryPolicy:
    def __init__(
        self,
        *,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        emit: Callable[..., None] | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if base_delay < 0:
            raise ValueError("base_delay must be non-negative")
        if max_delay < 0:
            raise ValueError("max_delay must be non-negative")
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.sleep = sleep
        self.emit = emit

    def run(
        self,
        operation: Callable[[], T],
        classify: Callable[[Exception], Any],
    ) -> T:
        for attempt in range(1, self.max_attempts + 1):
            try:
                return operation()
            except Exception as error:  # noqa: BLE001 - classification boundary
                classification = classify(error)
                if not self._is_transient(error, classification):
                    raise
                if attempt >= self.max_attempts:
                    raise
                delay = min(
                    self.max_delay,
                    self.base_delay * (2 ** (attempt - 1)),
                )
                self._emit_retry(error, classification, attempt, delay)
                self.sleep(delay)
        raise AssertionError("unreachable")

    @staticmethod
    def _is_transient(error: Exception, classification: Any) -> bool:
        if isinstance(classification, FailureClass):
            return classification is FailureClass.TRANSIENT
        if isinstance(classification, str):
            if classification == FailureClass.TRANSIENT.value:
                return True
        failure_class = getattr(classification, "failure_class", None)
        if failure_class is not None:
            return RetryPolicy._is_transient(error, failure_class)
        failure_class = getattr(error, "failure_class", None)
        if failure_class is not None:
            return RetryPolicy._is_transient(error, failure_class)
        return False

    def _emit_retry(
        self,
        error: Exception,
        classification: Any,
        attempt: int,
        delay: float,
    ) -> None:
        if self.emit is None:
            return
        detail = getattr(error, "detail", classification)
        code = getattr(detail, "code", None) or getattr(error, "code", None)
        if code is None:
            code = str(detail)
        self.emit(
            kind="operation.retrying",
            level="warning",
            message="Operação transitória será repetida",
            payload={
                "attempt": attempt,
                "maximum": self.max_attempts,
                "code": code,
                "next_delay": delay,
            },
        )


__all__ = ["ExecutionFailure", "RetryPolicy"]
