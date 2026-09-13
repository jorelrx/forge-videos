from types import SimpleNamespace

import pytest

from forge.domain.models import Plano
from forge.executors.lm_studio import LMStudioManager
from forge.infrastructure.config import Settings
from forge.llms.model import invoke_structured


class Runner:
    def __init__(self):
        self.argv = None

    def __call__(self, argv, **kwargs):
        self.argv = argv
        return SimpleNamespace(returncode=0)


def test_lm_studio_loads_recommended_model_with_16k_context(settings=None):
    runner = Runner()
    settings = Settings(_env_file=None, provider="lm-studio")
    LMStudioManager(settings, run=runner).ensure_loaded()
    assert runner.argv == [
        settings.lms_bin, "load", "google/gemma-4-e4b", "-c", "16384",
        "--ttl", "3600", "-y",
    ]


def test_lm_studio_rejects_removed_model_before_running_lms():
    runner = Runner()
    settings = Settings(_env_file=None, provider="lm-studio", model="qwen/qwen3.8-27b")
    with pytest.raises(ValueError, match="qwen/qwen3.8-27b"):
        LMStudioManager(settings, run=runner).ensure_loaded()
    assert runner.argv is None


def test_structured_length_retries_once_with_doubled_budget():
    class BudgetModel:
        def __init__(self):
            self.bound_budgets = []
            self.responses = [
                {"parsed": None, "raw": SimpleNamespace(response_metadata={"finish_reason": "length"}), "parsing_error": ValueError("cut")},
                {"parsed": Plano(tese="T", esboco="E"), "raw": SimpleNamespace(response_metadata={"finish_reason": "stop"}), "parsing_error": None},
            ]

        def bind(self, **kwargs):
            self.bound_budgets.append(kwargs["max_tokens"])
            return self

        def with_structured_output(self, schema, include_raw=False):
            parent = self
            class Bound:
                def invoke(self, messages):
                    return parent.responses.pop(0)
            return Bound()

    model = BudgetModel()
    result = invoke_structured(model, Plano, ["mensagem"], initial_max_tokens=4000, ceiling_max_tokens=16000)
    assert result == Plano(tese="T", esboco="E")
    assert model.bound_budgets == [4000, 8000]
