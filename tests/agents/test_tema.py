"""Seletor de tema: o canal só faz vídeo sobre o que o acervo sustenta.

O tema antigo era uma frase inventada pelo modelo, sem olhar os livros nem o
público. Aqui o modelo propõe candidatos, o código busca no acervo, e um
segundo passo julga — com os trechos na mão — quais candidatos têm fonte.
"""
import json
import types

import pytest

from forge.agents.tema import (
    SemTemaSustentado, TemaCandidato, TemasPropostos, VeredictoTema, VeredictoTemas,
    gerar_tema, sugerir_temas, temas_feitos,
)
from forge.infrastructure.config import Settings
from forge.llms.parsing import _texto
from forge.services.acervo import Livro, Passagem


def _settings(tmp_path, **extra):
    return Settings(
        _env_file=None, output_dir=tmp_path / "roteiros",
        studio_runs_dir=tmp_path / "runs", research_min_sources=3, **extra,
    )


def _cand(tema, eixo, buscas):
    return TemaCandidato(
        tema=tema, eixo=eixo, dor=f"dor de {tema}", promessa=f"promessa de {tema}",
        buscas=buscas,
    )


def _p(livro, n=1, titulo=None):
    return Passagem(
        path=f"{livro}/p{n}", book_id=livro, book_title=titulo or f"Livro {livro}",
        authors=["Autor"], text=f"trecho {n} do livro {livro}",
    )


def _veredicto(indice, sustentado=True, apelo=3):
    return VeredictoTema(indice=indice, sustentado=sustentado, apelo=apelo, motivo="m")


def _tres_candidatos():
    return TemasPropostos(candidatos=[
        _cand("A", "niilismo-absurdo", ["q1"]),
        _cand("B", "estoicismo", ["q2"]),
        _cand("C", "autoconhecimento", ["q3"]),
    ])


def _acervo_dos_tres(acervo_fake):
    return acervo_fake(por_query={
        "q1": [_p(1998, 1, "Zarathustra"), _p(1998, 2, "Zarathustra"), _p(4363, 1, "Beyond")],
        "q2": [],
        "q3": [_p(57628), _p(57634), _p(60333)],
    })


def test_sugere_so_temas_sustentados_ordenados_por_apelo(scripted, acervo_fake, tmp_path):
    veredictos = VeredictoTemas(veredictos=[
        _veredicto(0, apelo=3), _veredicto(1, sustentado=False, apelo=5), _veredicto(2, apelo=5),
    ])
    model = scripted(structured=[_tres_candidatos(), veredictos])

    sugestoes = sugerir_temas(model, _acervo_dos_tres(acervo_fake), _settings(tmp_path))

    assert [t.tema for t in sugestoes.temas] == ["C", "A"]
    assert sugestoes.temas[0].apelo == 5 and sugestoes.temas[0].eixo == "autoconhecimento"
    assert sugestoes.temas[1].livros == ["Zarathustra", "Beyond"]
    assert sugestoes.eixos_sem_cobertura == ["estoicismo", "etica-digital-ia"]


def test_empate_de_apelo_favorece_mais_livros(scripted, acervo_fake, tmp_path):
    veredictos = VeredictoTemas(veredictos=[_veredicto(0, apelo=4), _veredicto(2, apelo=4)])
    model = scripted(structured=[_tres_candidatos(), veredictos])

    sugestoes = sugerir_temas(model, _acervo_dos_tres(acervo_fake), _settings(tmp_path))

    # C tem três livros distintos; A tem dois.
    assert [t.tema for t in sugestoes.temas] == ["C", "A"]


def test_limita_a_n_sugestoes(scripted, acervo_fake, tmp_path):
    veredictos = VeredictoTemas(veredictos=[_veredicto(0, apelo=3), _veredicto(2, apelo=5)])
    model = scripted(structured=[_tres_candidatos(), veredictos])

    sugestoes = sugerir_temas(model, _acervo_dos_tres(acervo_fake), _settings(tmp_path), n=1)

    assert [t.tema for t in sugestoes.temas] == ["C"]
    # A cobertura do eixo não depende do corte em n.
    assert "niilismo-absurdo" not in sugestoes.eixos_sem_cobertura


def test_candidato_com_menos_passagens_que_o_minimo_sai(scripted, acervo_fake, tmp_path):
    propostos = TemasPropostos(candidatos=[_cand("A", "niilismo-absurdo", ["q1", "q1b"])])
    # Duas buscas devolvendo a mesma passagem contam uma vez só.
    acervo = acervo_fake(por_query={"q1": [_p(1998, 1), _p(1998, 2)], "q1b": [_p(1998, 1)]})
    model = scripted(structured=[propostos, VeredictoTemas(veredictos=[_veredicto(0)])])

    sugestoes = sugerir_temas(model, acervo, _settings(tmp_path))

    assert sugestoes.temas == []


def test_indice_invalido_e_veredicto_ausente_nao_sustentam(scripted, acervo_fake, tmp_path):
    """O juiz é um modelo: pode devolver índice fora da lista ou esquecer um candidato."""
    veredictos = VeredictoTemas(veredictos=[
        _veredicto(7, apelo=5), _veredicto(-1, apelo=5), _veredicto(2, apelo=2),
    ])
    model = scripted(structured=[_tres_candidatos(), veredictos])

    sugestoes = sugerir_temas(model, _acervo_dos_tres(acervo_fake), _settings(tmp_path))

    assert [t.tema for t in sugestoes.temas] == ["C"]


def test_busca_que_falha_e_pulada(scripted, acervo_fake, tmp_path):
    """Uma busca que estoura o prazo não derruba a sugestão inteira."""
    acervo = _acervo_dos_tres(acervo_fake)
    acervo.falhas = {"q1"}
    veredictos = VeredictoTemas(veredictos=[_veredicto(0), _veredicto(2)])
    model = scripted(structured=[_tres_candidatos(), veredictos])

    sugestoes = sugerir_temas(model, acervo, _settings(tmp_path))

    assert [t.tema for t in sugestoes.temas] == ["C"]


def test_sem_candidato_com_passagem_nao_chama_o_juiz(scripted, acervo_fake, tmp_path):
    model = scripted(structured=[_tres_candidatos()])

    sugestoes = sugerir_temas(model, acervo_fake(), _settings(tmp_path))

    assert sugestoes.temas == []
    assert model.structured == []


def test_prompt_traz_catalogo_eixos_e_temas_feitos(monkeypatch, acervo_fake, tmp_path):
    from forge.agents import tema

    settings = _settings(tmp_path)
    settings.output_dir.mkdir(parents=True)
    (settings.output_dir / "a.md").write_text(
        "---\ntema: O medo de escolher\ntese: x\n---\n\n## Gancho\n", encoding="utf-8",
    )
    prompts = []

    def invoke(model, schema, messages, **kwargs):
        prompts.append(messages[0].content)
        return TemasPropostos(candidatos=[])

    monkeypatch.setattr(tema, "invoke_structured", invoke)
    acervo = acervo_fake(livros=[Livro(
        id=1998, title="Thus Spake Zarathustra", authors=["Nietzsche"], languages=["en"],
    )])

    sugerir_temas(object(), acervo, settings)

    assert "Thus Spake Zarathustra" in prompts[0] and "[en]" in prompts[0]
    assert "- niilismo-absurdo:" in prompts[0]
    assert "O medo de escolher" in prompts[0]


def test_juiz_recebe_os_trechos_de_cada_candidato(monkeypatch, acervo_fake, tmp_path):
    from forge.agents import tema

    prompts = []
    respostas = [_tres_candidatos(), VeredictoTemas(veredictos=[])]

    def invoke(model, schema, messages, **kwargs):
        prompts.append(messages[0].content)
        return respostas.pop(0)

    monkeypatch.setattr(tema, "invoke_structured", invoke)
    sugerir_temas(object(), _acervo_dos_tres(acervo_fake), _settings(tmp_path))

    assert "trecho 1 do livro 1998" in prompts[1]
    assert "promessa de C" in prompts[1]


def test_temas_feitos_le_roteiros_e_runs_do_studio(tmp_path):
    settings = _settings(tmp_path)
    settings.output_dir.mkdir(parents=True)
    (settings.output_dir / "a.md").write_text(
        "---\ntema: O medo de escolher\ntese: x\n---\n", encoding="utf-8",
    )
    run = settings.studio_runs_dir / "run-1" / "video"
    run.mkdir(parents=True)
    (run / "input.json").write_text(json.dumps({"tema": "O que é ética?"}), encoding="utf-8")
    quebrada = settings.studio_runs_dir / "run-2" / "video"
    quebrada.mkdir(parents=True)
    (quebrada / "input.json").write_text("{não é json", encoding="utf-8")

    assert temas_feitos(settings) == ["O medo de escolher", "O que é ética?"]


def test_temas_feitos_sem_diretorios_e_vazio(tmp_path):
    assert temas_feitos(_settings(tmp_path)) == []


def test_tema_fornecido_nao_chama_modelo():
    assert gerar_tema(None, "Sobre o tédio") == "Sobre o tédio"


def test_gerar_tema_usa_a_primeira_sugestao(scripted, acervo_fake, tmp_path):
    veredictos = VeredictoTemas(veredictos=[_veredicto(0, apelo=3), _veredicto(2, apelo=5)])
    model = scripted(structured=[_tres_candidatos(), veredictos])

    tema = gerar_tema(
        model, None, acervo=_acervo_dos_tres(acervo_fake), settings=_settings(tmp_path),
    )

    assert tema == "C"


def test_gerar_tema_sem_sustentacao_levanta(scripted, acervo_fake, tmp_path):
    """Sem fonte não há tema: inventar um reabriria a porta do conteúdo sem lastro."""
    model = scripted(structured=[_tres_candidatos()])

    with pytest.raises(SemTemaSustentado):
        gerar_tema(model, None, acervo=acervo_fake(), settings=_settings(tmp_path))


def test_texto_lista_de_blocos_de_conteudo():
    resp = types.SimpleNamespace(content=[
        {"type": "text", "text": "abc"},
        {"type": "thinking", "thinking": "x"},
        {"type": "text", "text": "def"},
    ])
    assert _texto(resp) == "abcdef"
