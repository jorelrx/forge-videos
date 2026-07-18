from pathlib import Path

import forge.cli as cli
from forge.config import Settings
from forge.writer.models import Roteiro, Secao


def test_main_roteiro(monkeypatch, tmp_path, capsys):
    settings = Settings(_env_file=None, output_dir=tmp_path, anthropic_api_key="sk-test")
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "build_chat_model", lambda s: object())

    roteiro = Roteiro(tema="tema", tese="tese",
                      secoes=[Secao(nome="Hook", conteudo="c")])

    class FakeGraph:
        def invoke(self, state):
            assert state["tema"] == "meu tema"
            return {"roteiro": roteiro, "rounds": 1, "review": None}

    monkeypatch.setattr(cli, "build_graph", lambda model, s: FakeGraph())

    rc = cli.main(["roteiro", "--tema", "meu tema"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert Path(out).exists()
    assert out.endswith(".md")
