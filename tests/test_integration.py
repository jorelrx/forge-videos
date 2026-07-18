import os

import pytest

from forge.config import Settings
from forge.llm.model import build_chat_model
from forge.orchestrator.graph import build_graph

pytestmark = pytest.mark.skipif(
    not (os.getenv("FORGE_ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY")),
    reason="sem API key — pula integração",
)


def test_pipeline_real(tmp_path):
    settings = Settings(_env_file=None, output_dir=tmp_path, max_review_rounds=2)
    graph = build_graph(build_chat_model(settings), settings)
    final = graph.invoke({"tema": "O papel do tédio na vida moderna", "rounds": 0})
    roteiro = final["roteiro"]
    assert len(roteiro.secoes) == 9
    assert final["review"] is not None
