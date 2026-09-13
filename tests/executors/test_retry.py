from __future__ import annotations

from dataclasses import dataclass

import pytest

from forge.domain.execucao import FailureClass
from forge.executors.retry import ExecutionFailure, RetryPolicy


def no_sleep(_seconds: float) -> None:
    return None


@dataclass
class Counter:
    failures: list[Exception]
    count: int = 0

    def __call__(self) -> str:
        self.count += 1
        if self.failures:
            raise self.failures.pop(0)
        return "ok"


def transient(code: str) -> ExecutionFailure:
    return ExecutionFailure(code, FailureClass.TRANSIENT)


def capacity(code: str) -> ExecutionFailure:
    return ExecutionFailure(code, FailureClass.CAPACITY)


def test_retry_policy_retries_only_transient_failures():
    calls = Counter(failures=[transient("service_starting")])

    result = RetryPolicy(
        max_attempts=3, base_delay=1, max_delay=4, sleep=no_sleep
    ).run(calls, classify=lambda error: error.detail)

    assert result == "ok"
    assert calls.count == 2


def test_retry_policy_does_not_repeat_capacity_failure():
    calls = Counter(failures=[capacity("tts_vulkan_oom")])

    with pytest.raises(ExecutionFailure, match="tts_vulkan_oom"):
        RetryPolicy(max_attempts=3, sleep=no_sleep).run(
            calls, classify=lambda error: error.detail
        )

    assert calls.count == 1
