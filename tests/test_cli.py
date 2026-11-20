import re
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


# structlog colore o console (ConsoleRenderer), então `retentar=False` chega ao
# capsys entremeado de escapes ANSI. O teste olha o texto, não as cores.
_ANSI_RE = re.compile(r"\[[0-9;]*m")


def _log_limpo(texto: str) -> str:
    return _ANSI_RE.sub("", texto)


def _cli_com_roteiro_aprovado(monkeypatch, tmp_path):
    """Monta um `forge roteiro` que chega ao plano de mídia com roteiro aprovado."""
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


def test_cobertura_insuficiente_e_marcada_como_nao_retentavel(monkeypatch, tmp_path,
                                                              capsys):
    """O laço não vigiado precisa saber que este erro não muda ao ser repetido.

    `fatiar` é puro e o roteiro está congelado em disco: a segunda tentativa
    falha idêntica à primeira, para sempre. Sem essa marca, o retry-com-teto de
    S9 queima o orçamento inteiro num erro que nunca vai passar.
    """
    from forge.agents import midia as midia_mod
    from forge.agents.midia import CoberturaInsuficiente

    _cli_com_roteiro_aprovado(monkeypatch, tmp_path)

    def _sem_cobertura(*a, **k):
        raise CoberturaInsuficiente("blocos cobrem 85 palavras de 1079")

    monkeypatch.setattr(midia_mod, "planejar_midia", _sem_cobertura)

    rc = cli.main(["roteiro", "--tema", "meu tema"])

    assert rc == 0
    out = _log_limpo(capsys.readouterr().out)
    assert "retentar=False" in out
    caminho = out.strip().splitlines()[-1].strip()
    assert Path(caminho).exists() and caminho.endswith(".md")


def test_plano_ja_existente_nao_e_erro(monkeypatch, tmp_path, capsys):
    """Plano já em disco é o comportamento correto de `gravar_plano`, não falha.

    Em ERROR, cada run retomada acrescentaria um "Plano de mídia falhou" ao log
    do laço, escondendo as falhas de verdade entre ruído previsto.
    """
    from forge.agents import midia as midia_mod
    from forge.agents.midia import PlanoJaExiste
    from forge.domain.midia import Beat, BlocoNarracao, PlanoMidia

    _cli_com_roteiro_aprovado(monkeypatch, tmp_path)

    plano = PlanoMidia(
        blocos=[BlocoNarracao(id="b001", secao="Hook", texto="c")],
        beats=[Beat(id="i001", bloco_id="b001", prompt="uma ampulheta")],
    )
    monkeypatch.setattr(midia_mod, "planejar_midia", lambda *a, **k: plano)

    def _ja_existe(*a, **k):
        raise PlanoJaExiste("plano de mídia já existe")

    monkeypatch.setattr(midia_mod, "gravar_plano", _ja_existe)

    rc = cli.main(["roteiro", "--tema", "meu tema"])

    assert rc == 0
    out = _log_limpo(capsys.readouterr().out)
    assert "Plano de mídia falhou" not in out
    assert "mantido" in out
    caminho = out.strip().splitlines()[-1].strip()
    assert Path(caminho).exists() and caminho.endswith(".md")


def test_falha_transitoria_continua_retentavel(monkeypatch, tmp_path, capsys):
    """Timeout / `Model unloaded by user`: vale retentar, ao contrário da cobertura."""
    from forge.agents import midia as midia_mod

    _cli_com_roteiro_aprovado(monkeypatch, tmp_path)

    def _timeout(*a, **k):
        raise TimeoutError("Model unloaded by user")

    monkeypatch.setattr(midia_mod, "planejar_midia", _timeout)

    rc = cli.main(["roteiro", "--tema", "meu tema"])

    assert rc == 0
    out = _log_limpo(capsys.readouterr().out)
    assert "retentar=True" in out
    caminho = out.strip().splitlines()[-1].strip()
    assert Path(caminho).exists() and caminho.endswith(".md")


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


def _settings_temas(tmp_path):
    return Settings(_env_file=None, output_dir=tmp_path / "roteiros",
                    studio_runs_dir=tmp_path / "runs", anthropic_api_key="sk-test")


def test_cli_temas_imprime_lista_e_eixos_sem_cobertura(monkeypatch, tmp_path, capsys):
    from forge.agents import tema as tema_mod
    from forge.agents.tema import Sugestoes, TemaSugerido

    monkeypatch.setattr(cli, "get_settings", lambda: _settings_temas(tmp_path))
    monkeypatch.setattr(cli, "build_chat_model", lambda s: object())
    pedido = {}

    def _sugerir(model, acervo, settings, *, n):
        pedido["n"] = n
        return Sugestoes(
            temas=[TemaSugerido(
                tema="Por que você teme escolher", eixo="niilismo-absurdo", dor="d",
                promessa="p", livros=["Zarathustra", "Beyond Good and Evil"], apelo=4,
                motivo="m",
            )],
            eixos_sem_cobertura=["estoicismo", "etica-digital-ia"],
        )

    monkeypatch.setattr(tema_mod, "sugerir_temas", _sugerir)

    rc = cli.main(["temas", "--n", "3"])

    saida = capsys.readouterr()
    assert rc == 0 and pedido["n"] == 3
    assert (
        "1. Por que você teme escolher [niilismo-absurdo] apelo 4/5 — "
        "Zarathustra; Beyond Good and Evil"
    ) in saida.out
    assert "Eixos sem cobertura no acervo: estoicismo, etica-digital-ia" in saida.err


def test_cli_temas_sem_sustentacao_sai_1(monkeypatch, tmp_path, capsys):
    from forge.agents import tema as tema_mod
    from forge.agents.tema import Sugestoes

    monkeypatch.setattr(cli, "get_settings", lambda: _settings_temas(tmp_path))
    monkeypatch.setattr(cli, "build_chat_model", lambda s: object())
    monkeypatch.setattr(
        tema_mod, "sugerir_temas",
        lambda *a, **k: Sugestoes(temas=[], eixos_sem_cobertura=["estoicismo"]),
    )

    rc = cli.main(["temas"])

    saida = capsys.readouterr()
    assert rc == 1
    assert "Nenhum tema sustentado pelo acervo" in saida.err


def test_roteiro_entrega_o_revisor_ao_grafo(monkeypatch, tmp_path):
    _monta_run(monkeypatch, tmp_path, aprovado=False)
    revisor = object()
    recebido = {}
    monkeypatch.setattr(cli, "build_review_model", lambda s: revisor)

    class FakeGraph:
        def stream(self, state):
            yield {"write": {"roteiro": Roteiro(tema="t", tese="t", secoes=[Secao(nome="Hook", conteudo="c")])}}

    def build(model, s, inicio="tema", **kwargs):
        recebido.update(kwargs)
        return FakeGraph()

    monkeypatch.setattr(cli, "build_graph", build)
    cli.main(["roteiro", "--tema", "meu tema"])
    assert recebido["revisor"] is revisor


def test_cli_aceita_provider_claude(monkeypatch, tmp_path):
    from forge.agents import tema as tema_mod
    from forge.agents.tema import Sugestoes

    monkeypatch.setattr(cli, "get_settings", lambda: _settings_temas(tmp_path))
    usado = {}
    monkeypatch.setattr(cli, "build_chat_model", lambda s: usado.setdefault("provider", s.provider))
    monkeypatch.setattr(
        tema_mod, "sugerir_temas",
        lambda *a, **k: Sugestoes(temas=[], eixos_sem_cobertura=[]),
    )
    cli.main(["temas", "--provider", "claude"])
    assert usado["provider"] == "claude"


def test_cli_temas_com_acervo_fora_do_ar_sai_1(monkeypatch, tmp_path, capsys):
    from forge.agents import tema as tema_mod
    from forge.services.acervo import AcervoIndisponivel

    monkeypatch.setattr(cli, "get_settings", lambda: _settings_temas(tmp_path))
    monkeypatch.setattr(cli, "build_chat_model", lambda s: object())

    def _fora(*a, **k):
        raise AcervoIndisponivel("acervo não respondeu em /books")

    monkeypatch.setattr(tema_mod, "sugerir_temas", _fora)

    rc = cli.main(["temas"])

    assert rc == 1
    assert "acervo não respondeu" in capsys.readouterr().err


def _embalagem_valida():
    from forge.domain.embalagem import (
        Capitulo, Embalagem, ThumbnailProposta, TituloProposto,
    )

    return Embalagem(
        titulos=[TituloProposto(texto=f"Título {n}") for n in (1, 2, 3)],
        thumbnail=ThumbnailProposta(texto="Texto", prompt="p"),
        descricao="Abertura.",
        capitulos=[
            Capitulo(secao=f"S{n}", titulo=f"Parte {n}", inicio_segundos=n * 30)
            for n in range(3)
        ],
        comentario_fixado="E você?",
        fontes=["Obra"],
    )


def _sem_plano_de_midia(monkeypatch):
    from forge.agents import midia as midia_mod
    from forge.domain.midia import BlocoNarracao, PlanoMidia

    plano = PlanoMidia(blocos=[BlocoNarracao(id="b001", secao="Hook", texto="c")], beats=[])
    monkeypatch.setattr(midia_mod, "planejar_midia", lambda *a, **k: plano)


def test_roteiro_aprovado_grava_citacoes_e_embalagem(monkeypatch, tmp_path):
    from forge.agents import embalagem as embalagem_mod

    settings = _monta_run(monkeypatch, tmp_path, aprovado=True)
    _sem_plano_de_midia(monkeypatch)
    recebido = {}

    def _embalar(model, roteiro, citacoes, *, aviso_ia, run_dir):
        recebido.update(roteiro=roteiro, citacoes=citacoes, aviso_ia=aviso_ia)
        return _embalagem_valida()

    monkeypatch.setattr(embalagem_mod, "embalar", _embalar)

    assert cli.main(["roteiro", "--tema", "meu tema"]) == 0

    run = next((tmp_path / "runs").iterdir())
    assert (run / "video" / "citacoes.json").is_file()
    assert (run / "video" / "embalagem.json").is_file()
    assert "## Títulos" in (run / "embalagem.md").read_text(encoding="utf-8")
    assert recebido["roteiro"].tema == "tema"
    assert recebido["citacoes"] == []
    assert recebido["aviso_ia"] is settings.aviso_ia


def test_embalagem_reprovada_nao_derruba_o_roteiro(monkeypatch, tmp_path, capsys):
    """O roteiro aprovado é o entregável; a embalagem pode ser refeita depois."""
    from forge.agents import embalagem as embalagem_mod
    from forge.agents.embalagem import EmbalagemReprovada
    from forge.services.qualidade_embalagem import conferir_embalagem

    _monta_run(monkeypatch, tmp_path, aprovado=True)
    _sem_plano_de_midia(monkeypatch)
    reprovada = conferir_embalagem(_embalagem_valida().model_copy(update={"fontes": []}))

    def _embalar(*a, **k):
        raise EmbalagemReprovada(reprovada)

    monkeypatch.setattr(embalagem_mod, "embalar", _embalar)

    assert cli.main(["roteiro", "--tema", "meu tema"]) == 0

    run = next((tmp_path / "runs").iterdir())
    assert not (run / "embalagem.md").exists()
    saida = capsys.readouterr().out.strip().splitlines()[-1].strip()
    assert Path(saida).exists()


def test_roteiro_reprovado_nao_gera_embalagem(monkeypatch, tmp_path):
    from forge.agents import embalagem as embalagem_mod

    _monta_run(monkeypatch, tmp_path, aprovado=False)
    chamadas = []
    monkeypatch.setattr(
        embalagem_mod, "embalar",
        lambda *a, **k: chamadas.append(1) or _embalagem_valida(),
    )

    assert cli.main(["roteiro", "--tema", "meu tema"]) == 0

    assert chamadas == []
    run = next((tmp_path / "runs").iterdir())
    assert not (run / "embalagem.md").exists()
