import os

import pytest

from forge.infrastructure.config import Settings
from forge.llms.model import build_chat_model
from forge.orchestration.graph import build_graph

pytestmark = pytest.mark.skipif(
    not (os.getenv("FORGE_ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY")),
    reason="sem API key — pula integração",
)


def test_pipeline_real(tmp_path):
    # `juiz_relevancia=False` + gap files sob `tmp_path`: os defaults reais de
    # `Settings` apontam para `C:\dev\research\dados\...`, e este teste roda
    # de verdade sempre que uma API key está no ambiente — o skip no topo do
    # módulo não é garantia disso. Nada aqui pode escrever no acervo real.
    settings = Settings(
        _env_file=None,
        output_dir=tmp_path,
        max_review_rounds=2,
        juiz_relevancia=False,
        gaps_file=tmp_path / "gaps.txt",
        respostas_ruins_file=tmp_path / "ruins.jsonl",
    )
    graph = build_graph(build_chat_model(settings), settings)
    final = graph.invoke({
        "tema": "O papel do tédio na vida moderna",
        "rounds": 0,
        "passos": 0,
        "run_dir": tmp_path,
    })
    roteiro = final["roteiro"]
    assert len(roteiro.secoes) == 9
    assert final["review"] is not None
