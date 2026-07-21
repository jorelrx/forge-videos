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
