from pathlib import Path

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


def test_ingest_source_sem_query_falha(monkeypatch):
    from forge.cli import main

    rc = main(["ingest", "--source", "gutenberg"])
    assert rc == 1


def test_ingest_source_chama_ingerir_busca_remota(monkeypatch):
    import forge.cli as cli

    capturado = {}

    def fake(nomes, query, settings, *, limite=None, sobrescrever=False):
        capturado["nomes"] = nomes
        capturado["query"] = query
        capturado["limite"] = limite
        capturado["sobrescrever"] = sobrescrever
        return 7

    monkeypatch.setattr("forge.knowledge.ingest.ingerir_busca_remota", fake)
    rc = cli.main(["ingest", "--source", "all", "--query", "estoicismo", "--limite", "2"])
    assert rc == 0
    assert capturado["nomes"] == ["all"]
    assert capturado["query"] == "estoicismo"
    assert capturado["limite"] == 2
    assert capturado["sobrescrever"] is False  # default não sobrescreve


def test_ingest_source_sobrescrever_repassa_flag(monkeypatch):
    import forge.cli as cli

    capturado = {}

    def fake(nomes, query, settings, *, limite=None, sobrescrever=False):
        capturado["sobrescrever"] = sobrescrever
        return 1

    monkeypatch.setattr("forge.knowledge.ingest.ingerir_busca_remota", fake)
    rc = cli.main(["ingest", "--source", "sep", "--query", "stoicism", "--sobrescrever"])
    assert rc == 0
    assert capturado["sobrescrever"] is True
