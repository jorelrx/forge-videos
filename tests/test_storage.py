from forge.infrastructure.config import Settings
from forge.services.storage import gravar_roteiro
from forge.domain.models import Roteiro, Secao, Fonte

def _roteiro():
    return Roteiro(
        tema="O tédio como alarme",
        tese="O tédio informa",
        secoes=[Secao(nome=n, conteudo=f"conteúdo {n}") for n in
                ["Hook", "Problema", "História", "Explicação", "Filósofo",
                 "Psicologia", "Aplicação", "Resumo", "Conclusão"]],
        fontes=[Fonte(titulo="Obra", autor="Autor")],
    )

def test_grava_arquivo_com_secoes_e_frontmatter(tmp_path):
    settings = Settings(_env_file=None, output_dir=tmp_path)
    path = gravar_roteiro(_roteiro(), settings, rounds=2, aprovado=True)
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---")            # frontmatter
    assert "tema: O tédio como alarme" in text
    assert "rounds: 2" in text
    assert "aprovado: True" in text
    for nome in ["Hook", "Conclusão"]:
        assert f"## {nome}" in text
    # ordem: Hook antes de Conclusão
    assert text.index("## Hook") < text.index("## Conclusão")

def test_frontmatter_aprovado_none_quando_nao_informado(tmp_path):
    settings = Settings(_env_file=None, output_dir=tmp_path)
    path = gravar_roteiro(_roteiro(), settings, rounds=1)
    text = path.read_text(encoding="utf-8")
    assert "aprovado: None" in text

def test_slug_no_nome_do_arquivo(tmp_path):
    settings = Settings(_env_file=None, output_dir=tmp_path)
    path = gravar_roteiro(_roteiro(), settings)
    assert path.suffix == ".md"
    assert "o-tedio" in path.name

def test_fontes_do_acervo_saem_com_caminho_canonico(tmp_path):
    """O caminho canônico é o que torna a citação verificável no acervo."""
    roteiro = Roteiro(
        tema="determinismo",
        tese="tese",
        secoes=[Secao(nome="Hook", conteudo="c")],
        fontes=[Fonte(titulo="Beyond Good and Evil", autor="Nietzsche",
                      path="4363/ch2/p7", book_id=4363)],
    )
    settings = Settings(_env_file=None, output_dir=tmp_path)

    path = gravar_roteiro(roteiro, settings, rounds=1, aprovado=True)

    assert "- Beyond Good and Evil — Nietzsche (`4363/ch2/p7`)" in path.read_text(encoding="utf-8")

def test_fonte_sem_caminho_sai_sem_parenteses_vazio(tmp_path):
    settings = Settings(_env_file=None, output_dir=tmp_path)

    path = gravar_roteiro(_roteiro(), settings, rounds=1, aprovado=True)

    assert "- Obra — Autor\n" in path.read_text(encoding="utf-8")
