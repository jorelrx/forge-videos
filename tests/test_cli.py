from pathlib import Path

import pytest

import forge.cli as cli
from forge.infrastructure.config import Settings
from forge.domain.models import ReviewResult, Roteiro, Secao


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


def test_roteiro_grava_o_plano_de_midia(monkeypatch, tmp_path, capsys):
    from forge.agents import midia as midia_mod
    from forge.agents.midia import carregar_plano
    from forge.domain.midia import Beat, BlocoNarracao, PlanoMidia

    settings = Settings(_env_file=None, output_dir=tmp_path / "roteiros",
                        anthropic_api_key="sk-test")
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "build_chat_model", lambda s: object())

    roteiro = Roteiro(tema="tema", tese="tese",
                      secoes=[Secao(nome="Hook", conteudo="c")])

    class FakeGraph:
        def stream(self, state):
            yield {"write": {"roteiro": roteiro}}
            yield {"review": {"rounds": 1, "review": ReviewResult(aprovado=True)}}

    monkeypatch.setattr(cli, "build_graph", lambda model, s, inicio="tema": FakeGraph())

    plano = PlanoMidia(
        blocos=[BlocoNarracao(id="b001", secao="Hook", texto="c")],
        beats=[Beat(id="i001", bloco_id="b001", prompt="uma ampulheta")],
    )
    monkeypatch.setattr(midia_mod, "planejar_midia", lambda *a, **k: plano)

    rc = cli.main(["roteiro", "--tema", "meu tema"])

    assert rc == 0
    # criar_run_dir monta `settings.output_dir.parent / "runs" / <ts>-<slug>`
    # (services/artefatos.py:17), por isso output_dir aponta para um subdiretório
    # de tmp_path: as runs caem em tmp_path/runs e nada escapa do tmp.
    runs = list((tmp_path / "runs").iterdir())
    assert len(runs) == 1
    assert carregar_plano(runs[0]) == plano


def test_falha_no_plano_de_midia_nao_derruba_o_roteiro(monkeypatch, tmp_path, capsys):
    """A garantia que o try/except em torno do plano de mídia existe para dar:
    o roteiro aprovado já está em disco quando o plano é tentado, e uma falha
    ali não pode apagar esse entregável nem mudar o rc de `forge roteiro`."""
    from forge.agents import midia as midia_mod

    settings = Settings(_env_file=None, output_dir=tmp_path / "roteiros",
                        anthropic_api_key="sk-test")
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "build_chat_model", lambda s: object())

    roteiro = Roteiro(tema="tema", tese="tese",
                      secoes=[Secao(nome="Hook", conteudo="c")])

    class FakeGraph:
        def stream(self, state):
            yield {"write": {"roteiro": roteiro}}
            yield {"review": {"rounds": 1, "review": ReviewResult(aprovado=True)}}

    monkeypatch.setattr(cli, "build_graph", lambda model, s, inicio="tema": FakeGraph())

    def _explode(*a, **k):
        raise RuntimeError("modelo indisponível")

    monkeypatch.setattr(midia_mod, "planejar_midia", _explode)

    rc = cli.main(["roteiro", "--tema", "meu tema"])

    assert rc == 0
    out = capsys.readouterr().out.strip().splitlines()[-1].strip()
    assert Path(out).exists()
    assert out.endswith(".md")

    runs = list((tmp_path / "runs").iterdir())
    assert len(runs) == 1
    assert not (runs[0] / "video" / "midia.json").exists()


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


def _monta_run(monkeypatch, tmp_path, *, aprovado):
    """Um `forge roteiro` de mentira que termina com o roteiro em `aprovado`."""
    settings = Settings(_env_file=None, output_dir=tmp_path / "roteiros",
                        anthropic_api_key="sk-test")
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "build_chat_model", lambda s: object())

    roteiro = Roteiro(tema="tema", tese="tese",
                      secoes=[Secao(nome="Hook", conteudo="c")])
    review = None if aprovado is None else ReviewResult(aprovado=aprovado)

    class FakeGraph:
        def stream(self, state):
            yield {"write": {"roteiro": roteiro}}
            yield {"review": {"rounds": 8, "review": review}}

    monkeypatch.setattr(cli, "build_graph", lambda model, s, inicio="tema": FakeGraph())
    return settings


def test_roteiro_toma_o_slot_llm(monkeypatch, tmp_path):
    """Sem isto nada em produção reivindica o slot `llm`: o Qwen fica residente
    ao fim do run, `residente()` devolve None na fase seguinte, nada é liberado
    e o TTS aloca numa placa que ainda tem ~6 GB ocupados.

    O plano de mídia tem que sair DENTRO do slot — ele é emitido de propósito
    com o modelo ainda carregado."""
    from contextlib import contextmanager

    from forge.agents import midia as midia_mod
    from forge.domain.midia import Beat, BlocoNarracao, PlanoMidia

    _monta_run(monkeypatch, tmp_path, aprovado=True)
    eventos = []

    class BrokerFalso:
        @contextmanager
        def exclusivo(self, recurso):
            eventos.append(f"entra:{recurso}")
            yield
            eventos.append(f"sai:{recurso}")

    monkeypatch.setattr(cli, "montar_broker", lambda s: BrokerFalso())

    plano = PlanoMidia(
        blocos=[BlocoNarracao(id="b001", secao="Hook", texto="c")],
        beats=[Beat(id="i001", bloco_id="b001", prompt="uma ampulheta")],
    )

    def _planejar(*a, **k):
        eventos.append("plano")
        return plano

    monkeypatch.setattr(midia_mod, "planejar_midia", _planejar)

    assert cli.main(["roteiro", "--tema", "meu tema"]) == 0
    assert eventos == ["entra:llm", "plano", "sai:llm"]


def test_gpu_ocupada_sai_limpo_sem_traceback(monkeypatch, tmp_path):
    """Outro forge segurando a placa por >900s é o caso NORMAL que o lock
    existe para produzir, não um bug: `forge roteiro` tem que sair com rc=1
    como os demais erros previstos deste comando, não propagar um traceback."""
    from contextlib import contextmanager

    from forge.gpu.broker import GPUOcupada

    _monta_run(monkeypatch, tmp_path, aprovado=True)

    class BrokerFalso:
        @contextmanager
        def exclusivo(self, recurso):
            raise GPUOcupada("placa ocupada por outro processo")
            yield  # pragma: no cover - inatingível, mas mantém o formato de gerador

    monkeypatch.setattr(cli, "montar_broker", lambda s: BrokerFalso())

    with pytest.raises(SystemExit) as exc:
        cli.main(["roteiro", "--tema", "meu tema"])
    assert exc.value.code == 1


def test_plano_de_midia_nao_sai_de_roteiro_reprovado(monkeypatch, tmp_path):
    """O grafo também termina por esgotar max_passos ou max_review_rounds, com
    aprovado False. Planejar mídia aí gasta horas de TTS e de SDXL num roteiro
    que o revisor reprovou."""
    from forge.agents import midia as midia_mod
    from forge.domain.midia import BlocoNarracao, PlanoMidia

    _monta_run(monkeypatch, tmp_path, aprovado=False)
    chamadas = []

    def _planejar(*a, **k):
        # Devolve um plano VÁLIDO de propósito: se este teste apenas levantasse,
        # o try/except do CLI engoliria a exceção e o teste passaria mesmo com a
        # chamada acontecendo.
        chamadas.append(1)
        return PlanoMidia(
            blocos=[BlocoNarracao(id="b001", secao="Hook", texto="c")], beats=[]
        )

    monkeypatch.setattr(midia_mod, "planejar_midia", _planejar)

    assert cli.main(["roteiro", "--tema", "meu tema"]) == 0

    assert chamadas == []
    runs = list((tmp_path / "runs").iterdir())
    assert not (runs[0] / "video" / "midia.json").exists()
