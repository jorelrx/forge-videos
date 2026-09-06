from pathlib import Path

import pytest

import forge.cli as cli
from forge.infrastructure.config import Settings
from forge.domain.models import Roteiro, Secao


def test_main_roteiro(monkeypatch, tmp_path, capsys):
    settings = Settings(_env_file=None, output_dir=tmp_path, anthropic_api_key="sk-test")
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "build_chat_model", lambda s: object())

    roteiro = Roteiro(tema="tema", tese="tese",
                      secoes=[Secao(nome="Hook", conteudo="c")])

    class FakeGraph:
        def stream(self, state):
            assert state["tema"] == "meu tema"
            yield {"write": {"roteiro": roteiro}}
            yield {"review": {"rounds": 1, "review": None}}

    monkeypatch.setattr(cli, "build_graph", lambda model, s, inicio="tema": FakeGraph())

    rc = cli.main(["roteiro", "--tema", "meu tema"])
    assert rc == 0
    # structlog escreve no stdout junto; o path é a última linha impressa
    out = capsys.readouterr().out.strip().splitlines()[-1].strip()
    assert Path(out).exists()
    assert out.endswith(".md")


def test_ingest_nao_e_mais_um_subcomando():
    """A ingestão de livros é do acervo (POST /books/{id}/ingest), não do forge."""
    with pytest.raises(SystemExit) as exc:
        cli.main(["ingest", "--status"])
    assert exc.value.code == 2  # argparse: subcomando inválido


def test_ingest_nao_tem_mais_flag_sobrescrever():
    """Write-once: uma obra já na base nunca é reingerida, então o flag que
    forçava isso deixou de existir."""
    from forge import cli

    with pytest.raises(SystemExit) as exc:
        cli.main(["ingest", "--source", "sep", "--query", "x", "--sobrescrever"])
    assert exc.value.code == 2  # argparse: argumento desconhecido


def test_comando_buscar_nao_existe_mais():
    """Retriever dormente até K5."""
    from forge.cli import main

    with pytest.raises(SystemExit):
        main(["buscar", "--query", "virtude"])
