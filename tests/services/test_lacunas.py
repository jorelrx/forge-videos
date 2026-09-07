import json

from forge.infrastructure.config import Settings
from forge.services.acervo import Passagem
from forge.services.lacunas import registrar_lacuna


def _settings(tmp_path):
    return Settings(
        _env_file=None,
        gaps_file=tmp_path / "unanswered_questions.txt",
        respostas_ruins_file=tmp_path / "respostas_ruins.jsonl",
    )


def _passagem(path="4363/ch2/p7"):
    return Passagem(
        path=path, book_id=4363, book_title="Beyond Good and Evil",
        authors=["Nietzsche"], breadcrumb="Cap 2", text="trecho longo " * 40,
        url="http://acervo.test/books/4363", score=0.81,
    )


def test_grava_so_a_pergunta_no_arquivo_do_acervo(tmp_path):
    """O acervo lê esse arquivo de volta e dedupe por linha exata.

    Ver unanswered_log.py do projeto research: 'Holds ONLY the question, no
    duplicates'. Escrever o par pergunta/resposta ali quebraria o dedupe dele.
    """
    s = _settings(tmp_path)

    registrar_lacuna(s, query="vontade em Nietzsche", tema="vontade",
                     motivo="passagens sobre outro assunto", passagens=[_passagem()])

    linhas = s.gaps_file.read_text(encoding="utf-8").splitlines()
    assert linhas == ["vontade em Nietzsche"]


def test_nao_duplica_pergunta_ja_registrada(tmp_path):
    s = _settings(tmp_path)
    s.gaps_file.write_text("vontade em Nietzsche\n", encoding="utf-8")

    registrar_lacuna(s, query="  vontade   em Nietzsche  ", tema="vontade",
                     motivo="", passagens=[])

    assert s.gaps_file.read_text(encoding="utf-8") == "vontade em Nietzsche\n"


def test_evidencia_completa_vai_para_o_arquivo_nosso(tmp_path):
    s = _settings(tmp_path)

    registrar_lacuna(s, query="vontade em Nietzsche", tema="vontade de potência",
                     motivo="fala de moral, não de vontade", passagens=[_passagem()])

    registro = json.loads(s.respostas_ruins_file.read_text(encoding="utf-8").strip())
    assert registro["query"] == "vontade em Nietzsche"
    assert registro["tema"] == "vontade de potência"
    assert registro["motivo"] == "fala de moral, não de vontade"
    assert registro["passagens"][0]["path"] == "4363/ch2/p7"
    assert registro["passagens"][0]["book_title"] == "Beyond Good and Evil"
    assert registro["passagens"][0]["score"] == 0.81
    assert len(registro["passagens"][0]["trecho"]) <= 300
    assert registro["ts"]


def test_duas_lacunas_viram_duas_linhas_jsonl(tmp_path):
    s = _settings(tmp_path)

    registrar_lacuna(s, query="a", tema="t", motivo="", passagens=[])
    registrar_lacuna(s, query="b", tema="t", motivo="", passagens=[])

    linhas = s.respostas_ruins_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(linhas) == 2
    assert json.loads(linhas[1])["query"] == "b"


def test_caminho_impossivel_nao_derruba_o_roteiro(tmp_path, monkeypatch):
    """Caminho de outro projeto pode ficar sem permissão ou indisponível.

    `chmod` no Windows não bloqueia escrita como no POSIX (ver nota do brief),
    então o teste discrimina de verdade patchando `Path.open` do módulo para
    levantar OSError — é isso que simula o caminho impossível nesta
    plataforma. Perder o registro é ruim; perder o roteiro por causa dele é
    pior.
    """
    s = _settings(tmp_path)

    def _open_que_falha(self, *args, **kwargs):
        raise OSError("simulated: sem permissão")

    monkeypatch.setattr("forge.services.lacunas.Path.open", _open_que_falha)

    registrar_lacuna(s, query="q", tema="t", motivo="", passagens=[])  # não levanta


def test_registro_desligado_quando_o_caminho_e_none(tmp_path):
    s = Settings(_env_file=None, gaps_file=None, respostas_ruins_file=None)

    registrar_lacuna(s, query="q", tema="t", motivo="", passagens=[])  # não levanta
