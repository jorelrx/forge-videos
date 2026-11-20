from forge.domain.models import Fonte
from forge.domain.models import BlocoRoteiro, Roteiro, Secao
from forge.services.artefatos import _fmt_fontes, _ler_fontes, carregar_run, gravar_artefato


def test_fonte_do_acervo_sobrevive_ao_round_trip():
    """path e book_id são a procedência; perdê-los no disco quebra o --retomar."""
    fontes = [
        Fonte(
            titulo="Beyond Good and Evil",
            autor="Friedrich Nietzsche",
            url="http://acervo.test/books/4363",
            path="4363/ch2/p7",
            book_id=4363,
        )
    ]

    linha = _fmt_fontes(fontes)
    lidas = _ler_fontes(linha)

    assert lidas == fontes


def test_fonte_antiga_sem_procedencia_ainda_carrega():
    """Runs gravadas antes do acervo não têm path; devem continuar legíveis."""
    lidas = _ler_fontes('fontes: [{"titulo": "Ética", "autor": "Espinosa", "url": null}]')

    assert lidas[0].titulo == "Ética"
    assert lidas[0].path is None
    assert lidas[0].book_id is None


def test_run_retomada_preserva_referencias_estruturadas(tmp_path):
    roteiro = Roteiro(
        tema="Tema", tese="Tese", fontes=[Fonte(titulo="Obra", path="1/ch1/p1")],
        secoes=[Secao(
            nome="Gancho", conteudo="Uma fala.",
            blocos=[BlocoRoteiro(texto="Uma fala.", referencias=["1/ch1/p1"])],
        )],
    )
    gravar_artefato(tmp_path, "tema", {"tema": "Tema"})
    gravar_artefato(tmp_path, "research", {"research_notes": "Brief", "fontes": []})
    gravar_artefato(tmp_path, "plan", {"tese": "Tese", "esboco": "Esboço"})
    write = gravar_artefato(tmp_path, "write", {"roteiro": roteiro})

    conteudo, pendente = carregar_run(tmp_path)

    assert write.with_suffix(".json").is_file()
    assert pendente == "review"
    assert conteudo["roteiro"].secoes[0].blocos[0].referencias == ["1/ch1/p1"]


def test_plano_persiste_e_retoma_eixo(tmp_path):
    gravar_artefato(tmp_path, "tema", {"tema": "Tema"})
    gravar_artefato(tmp_path, "research", {"research_notes": "Brief", "fontes": []})
    gravar_artefato(
        tmp_path, "plan", {"tese": "Tese", "esboco": "Esboço", "eixo": "estoicismo"}
    )

    conteudo, pendente = carregar_run(tmp_path)

    assert pendente == "write"
    assert conteudo["eixo"] == "estoicismo"
    assert conteudo["tese"] == "Tese" and conteudo["esboco"] == "Esboço"


def test_plano_antigo_sem_eixo_retoma_com_none(tmp_path):
    """Runs anteriores ao eixo têm o plano sem essa linha no frontmatter."""
    gravar_artefato(tmp_path, "tema", {"tema": "Tema"})
    gravar_artefato(tmp_path, "research", {"research_notes": "Brief", "fontes": []})
    (tmp_path / "02-plan.md").write_text(
        "---\nagente: plan\n---\n\n## Tese\n\nTese\n\n## Esboço\n\nEsboço\n",
        encoding="utf-8",
    )

    conteudo, _ = carregar_run(tmp_path)

    assert conteudo["eixo"] is None
    assert conteudo["esboco"] == "Esboço"


def test_retomada_recupera_as_passagens_da_pesquisa(tmp_path):
    """Sem as passagens o write da retomada escreve às cegas, reclama do
    acervo vazio e devolve a run à pesquisa: medido numa run real."""
    from forge.agents.research import PassageEvidence

    passagens = [
        PassageEvidence(
            path="5.f6", book_id=12, title="Die Philosophie der Freiheit",
            authors=["Steiner, Rudolf"], text="Nicht darauf kommt es an.",
            url="https://www.gutenberg.org/ebooks/12",
        ),
        PassageEvidence(path="2.3.11.1.f14", title="Essai", text="La croûte."),
    ]
    gravar_artefato(tmp_path, "tema", {"tema": "Tema"})
    research = gravar_artefato(tmp_path, "research", {
        "research_notes": "Brief", "fontes": [], "research_passages": passagens,
    })

    conteudo, pendente = carregar_run(tmp_path)

    assert pendente == "plan"
    assert conteudo["research_passages"] == passagens
    assert research.name == "01-research.md"


def test_pesquisa_antiga_sem_passagens_retoma_sem_a_chave(tmp_path):
    gravar_artefato(tmp_path, "tema", {"tema": "Tema"})
    gravar_artefato(tmp_path, "research", {"research_notes": "Brief", "fontes": []})

    conteudo, _ = carregar_run(tmp_path)

    assert "research_passages" not in conteudo
