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


def test_ingest_source_sem_query_falha(monkeypatch):
    from forge.cli import main

    rc = main(["ingest", "--source", "gutenberg"])
    assert rc == 1


def test_ingest_source_chama_ingerir_busca_remota(monkeypatch):
    import forge.cli as cli

    capturado = {}

    def fake(nomes, query, settings, *, limite=None):
        capturado["nomes"] = nomes
        capturado["query"] = query
        capturado["limite"] = limite
        return 7

    monkeypatch.setattr("forge.knowledge.ingest.ingerir_busca_remota", fake)
    rc = cli.main(["ingest", "--source", "all", "--query", "estoicismo", "--limite", "2"])
    assert rc == 0
    assert capturado["nomes"] == ["all"]
    assert capturado["query"] == "estoicismo"
    assert capturado["limite"] == 2


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


def test_confirmar_reset_recusa_stdin_fechado(monkeypatch):
    """Guarda de operação destrutiva: sem terminal, aborta em vez de prosseguir."""
    from forge import cli

    def sem_stdin(_prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", sem_stdin)
    assert cli._confirmar_reset() is False


def test_confirmar_reset_so_aceita_a_palavra_exata(monkeypatch):
    from forge import cli

    for resposta, esperado in [
        ("apagar", True), ("  APAGAR  ", True),
        ("", False), ("y", False), ("sim", False), ("apagar tudo", False),
    ]:
        monkeypatch.setattr("builtins.input", lambda _p, r=resposta: r)
        assert cli._confirmar_reset() is esperado, resposta


def test_reset_exige_confirmacao_e_aborta_quando_negada(monkeypatch):
    from forge import cli

    chamou = []
    monkeypatch.setattr(cli, "_confirmar_reset", lambda: False)
    monkeypatch.setattr(
        "forge.knowledge.ingest.resetar_stores", lambda s: chamou.append(s)
    )
    assert cli.main(["ingest", "--reset"]) == 1
    assert chamou == []


def test_reset_confirmado_chama_resetar_stores(monkeypatch):
    from forge import cli

    chamou = []
    monkeypatch.setattr(cli, "_confirmar_reset", lambda: True)
    monkeypatch.setattr(
        "forge.knowledge.ingest.resetar_stores", lambda s: chamou.append(s)
    )
    assert cli.main(["ingest", "--reset", "--sim"]) == 0
    assert len(chamou) == 1


def test_reset_com_status_imprime_contagens(monkeypatch, capsys):
    """Fix 7: `--reset --status` sem --path/--source não pode parar no aviso de
    reset — tem que cair no ramo de status e imprimir as contagens."""
    from forge import cli

    class FakeStores:
        vector = type("V", (), {"contar": lambda self: 1})()
        catalog = type("C", (), {"contar_chunks": lambda self: 2})()
        graph = type("G", (), {"contar_entidades": lambda self: 3})()

    monkeypatch.setattr(cli, "_confirmar_reset", lambda: True)
    monkeypatch.setattr("forge.knowledge.ingest.resetar_stores", lambda s: None)
    monkeypatch.setattr(
        "forge.knowledge.ingest._montar", lambda s: (object(), FakeStores())
    )

    rc = cli.main(["ingest", "--reset", "--sim", "--status"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "qdrant vetores: 1" in out
    assert "postgres chunks: 2" in out
    assert "neo4j entidades: 3" in out
