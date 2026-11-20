from pathlib import Path

from forge.services.trilha import EXTENSOES, escolher_trilha


def _faixas(pasta: Path, *nomes: str) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    for nome in nomes:
        (pasta / nome).write_bytes(b"")


def test_pasta_ausente_devolve_none(tmp_path):
    assert escolher_trilha(tmp_path / "nao-existe", semente="x") is None


def test_pasta_vazia_devolve_none(tmp_path):
    assert escolher_trilha(tmp_path, semente="x") is None


def test_ignora_arquivos_que_nao_sao_audio(tmp_path):
    _faixas(tmp_path, "calma.txt", "capa.jpg", "leia-me.md")
    assert escolher_trilha(tmp_path, semente="x") is None


def test_mesma_semente_mesma_faixa(tmp_path):
    _faixas(tmp_path, "a.mp3", "b.mp3", "c.mp3", "d.wav")
    primeira = escolher_trilha(tmp_path, semente="run-1")
    segunda = escolher_trilha(tmp_path, semente="run-1")
    assert primeira == segunda


def test_sementes_diferentes_distribuem(tmp_path):
    _faixas(tmp_path, "a.mp3", "b.mp3", "c.mp3", "d.mp3", "e.mp3")
    escolhidas = {
        escolher_trilha(tmp_path, semente=f"run-{i}").caminho.name
        for i in range(20)
    }
    assert len(escolhidas) >= 2


def test_subpasta_do_eixo_tem_preferencia(tmp_path):
    _faixas(tmp_path, "raiz.mp3")
    _faixas(tmp_path / "estoicismo", "eixo.mp3")
    trilha = escolher_trilha(tmp_path, semente="x", eixo="estoicismo")
    assert trilha.caminho == tmp_path / "estoicismo" / "eixo.mp3"


def test_subpasta_do_eixo_vazia_cai_na_raiz(tmp_path):
    _faixas(tmp_path, "raiz.mp3")
    (tmp_path / "estoicismo").mkdir()
    (tmp_path / "estoicismo" / "nota.txt").write_text("x")
    trilha = escolher_trilha(tmp_path, semente="x", eixo="estoicismo")
    assert trilha.caminho == tmp_path / "raiz.mp3"


def test_subpasta_do_eixo_ausente_cai_na_raiz(tmp_path):
    _faixas(tmp_path, "raiz.mp3")
    trilha = escolher_trilha(tmp_path, semente="x", eixo="estoicismo")
    assert trilha.caminho == tmp_path / "raiz.mp3"


def test_nao_recursa_em_outras_subpastas(tmp_path):
    _faixas(tmp_path / "outro", "escondida.mp3")
    assert escolher_trilha(tmp_path, semente="x") is None
    assert escolher_trilha(tmp_path, semente="x", eixo="estoicismo") is None


def test_credito_vem_da_primeira_linha_nao_vazia(tmp_path):
    _faixas(tmp_path, "calma.mp3")
    (tmp_path / "calma.txt").write_text(
        "\n  \n  Música: Autor — CC BY 4.0  \nsegunda linha\n", encoding="utf-8",
    )
    trilha = escolher_trilha(tmp_path, semente="x")
    assert trilha.credito == "Música: Autor — CC BY 4.0"


def test_credito_none_sem_arquivo_ou_vazio(tmp_path):
    _faixas(tmp_path, "calma.mp3")
    assert escolher_trilha(tmp_path, semente="x").credito is None
    (tmp_path / "calma.txt").write_text("\n \n", encoding="utf-8")
    assert escolher_trilha(tmp_path, semente="x").credito is None


def test_extensao_maiuscula_aceita(tmp_path):
    _faixas(tmp_path, "CALMA.MP3")
    trilha = escolher_trilha(tmp_path, semente="x")
    assert trilha.caminho.name == "CALMA.MP3"


def test_extensoes_publicas():
    assert ".mp3" in EXTENSOES and ".m4a" in EXTENSOES
