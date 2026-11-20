"""A etapa `plano_midia` do Studio também entrega a embalagem do vídeo.

É a última etapa com modelo carregado, então a embalagem sai aqui — antes do
plano de mídia, para que um título reprovado não gaste as chamadas dos beats.
"""
from __future__ import annotations

import json
from pathlib import Path

from forge.agents.embalagem import AVISO_IA
from forge.agents.research import PassageEvidence
from forge.domain.embalagem import (
    Embalagem, EmbalagemProposta, RotuloCapitulo, ThumbnailProposta, TituloProposto,
)
from forge.domain.execucao import RunSnapshot
from forge.domain.midia import BeatProposto, BeatsDaSecao
from forge.domain.models import BlocoRoteiro, Roteiro, Secao
from forge.domain.operacao import StageName
from forge.executors.plano_midia import MediaPlanExecutor
from forge.infrastructure.config import Settings
from forge.services.citacoes import Citacao, gravar_citacoes
from forge.services.persistencia import carregar_modelo, gravar_modelo

CAMINHO = "4363/ch2/p7"

# Uma frase longa por seção: cada seção vira exatamente um bloco de narração
# (b001, b002, b003) e dura mais que os 10 s mínimos de um capítulo.
_FRASES = {
    "Gancho": "Você segue a regra à risca enquanto alguém que não fez nada de errado perde o atendimento de que precisava e todos ao seu redor aplaudem a sua firmeza.",
    "Prova": "Nietzsche desconfia de toda utilidade que não diz para que serve e pergunta que tipo de vida uma regra favorece antes de aceitar que ela merece ser obedecida por alguém.",
    "Fecho": "Agora o aplauso continua ali mas você já sabe que ele nunca foi a resposta e que a pergunta sobre o que a regra promove continua sendo inteiramente sua.",
}


def _roteiro() -> Roteiro:
    return Roteiro(tema="Tema", tese="Tese", secoes=[
        Secao(nome=nome, conteudo=frase, blocos=[BlocoRoteiro(
            texto=frase, referencias=[] if nome == "Gancho" else [CAMINHO],
        )])
        for nome, frase in _FRASES.items()
    ])


def _snapshot(tmp_path: Path, *, com_citacoes: bool = True) -> RunSnapshot:
    root = tmp_path / "runs"
    snapshot = RunSnapshot(
        run_id="run-1", video_id="video-1", tema="Tema", tese="Tese",
        stage=StageName.PLANO_MIDIA, attempt=1, output_root=root,
        run_dir=root / "run-1", config_snapshot={"midia_alvo_segundos": 15},
        artifacts=[], work_items=[],
    )
    gravar_modelo(snapshot.run_dir / "video" / "roteiro.json", _roteiro())
    if com_citacoes:
        gravar_citacoes(snapshot.run_dir, [Citacao(
            secao="Prova", bloco=0, tipo="parafrase", texto="fala",
            autor="Nietzsche, Friedrich Wilhelm", obra="Beyond Good and Evil",
            path=CAMINHO, book_id=4363, url="https://www.gutenberg.org/ebooks/4363",
        )])
    return snapshot


def _proposta(titulo_3="Como saber se uma regra merece obediência") -> EmbalagemProposta:
    return EmbalagemProposta(
        titulos=[
            TituloProposto(texto="Por que o aplauso não prova que você está certo", angulo="pergunta"),
            TituloProposto(texto="O erro de quem sempre segue a regra", angulo="contraintuitivo"),
            TituloProposto(texto=titulo_3, angulo="benefício"),
        ],
        thumbnail=ThumbnailProposta(texto="O aplauso mente", prompt="a lone figure on a stage"),
        abertura="Todos aprovam. E se ainda assim estiver errado?",
        resumo="Um exame do que justifica uma regra.",
        capitulos=[
            RotuloCapitulo(secao="Gancho", titulo="O prêmio"),
            RotuloCapitulo(secao="Prova", titulo="O teste de Nietzsche"),
            RotuloCapitulo(secao="Fecho", titulo="O que fazer com o aplauso"),
        ],
        tags=["filosofia", "ética"],
        hashtags=["#filosofia"],
    )


def _beats():
    return [
        BeatsDaSecao(beats=[BeatProposto(bloco_id=f"b00{n}", prompt=f"scene {n}")])
        for n in (1, 2, 3)
    ]


def _executor(model, **settings):
    return MediaPlanExecutor(
        model=model, settings=Settings(_env_file=None, provider="anthropic", **settings),
    )


def test_etapa_grava_embalagem_antes_do_plano_de_midia(tmp_path, scripted):
    snapshot = _snapshot(tmp_path)
    events = []
    model = scripted(structured=[_proposta(), *_beats()])

    result = _executor(model).run(snapshot, lambda **event: events.append(event))

    assert result.gate.approved, result.gate
    embalagem = carregar_modelo(snapshot.run_dir / "video" / "embalagem.json", Embalagem)
    assert [c.titulo for c in embalagem.capitulos] == [
        "O prêmio", "O teste de Nietzsche", "O que fazer com o aplauso",
    ]
    assert embalagem.fontes == [
        "Nietzsche, Friedrich Wilhelm — Beyond Good and Evil "
        "(https://www.gutenberg.org/ebooks/4363)",
    ]
    assert AVISO_IA in embalagem.descricao
    assert (snapshot.run_dir / "embalagem.md").is_file()
    assert (snapshot.run_dir / "video" / "midia.json").is_file()

    criados = [e["payload"]["kind"] for e in events if e["kind"] == "artifact.created"]
    assert criados == ["embalagem", "embalagem_markdown", "media_plan"]
    assert {a.kind: a.relative_path for a in result.artifacts} == {
        "embalagem": "video/embalagem.json",
        "embalagem_markdown": "embalagem.md",
        "media_plan": "video/midia.json",
    }


def test_embalagem_reprovada_falha_a_etapa_sem_gastar_beats(tmp_path, scripted):
    snapshot = _snapshot(tmp_path)
    model = scripted(structured=[_proposta("x" * 80), _proposta("x" * 80), *_beats()])

    result = _executor(model).run(snapshot, lambda **event: None)

    assert not result.gate.approved
    assert result.gate.code == "packaging_gate_failed"
    assert "titulo_longo" in {finding.code for finding in result.gate.findings}
    # Os três pedidos de beats continuam na fila: a etapa parou antes deles.
    assert len(model.structured) == 3
    assert not (snapshot.run_dir / "video" / "midia.json").exists()
    assert not (snapshot.run_dir / "video" / "embalagem.json").exists()


def test_sem_citacoes_json_deriva_do_roteiro_e_das_evidencias(tmp_path, scripted):
    """Runs anteriores ao `citacoes.json` só têm as evidências da pesquisa."""
    snapshot = _snapshot(tmp_path, com_citacoes=False)
    evidencia = PassageEvidence(
        path=CAMINHO, book_id=4363, title="Beyond Good and Evil",
        authors=["Nietzsche, Friedrich Wilhelm"], text="x",
    )
    (snapshot.run_dir / "video" / "research-evidence.json").write_text(
        json.dumps({"passages": [evidencia.model_dump()]}), encoding="utf-8",
    )
    model = scripted(structured=[_proposta(), *_beats()])

    result = _executor(model).run(snapshot, lambda **event: None)

    assert result.gate.approved, result.gate
    embalagem = carregar_modelo(snapshot.run_dir / "video" / "embalagem.json", Embalagem)
    assert embalagem.fontes == ["Nietzsche, Friedrich Wilhelm — Beyond Good and Evil"]


def test_roteiro_sem_fonte_nenhuma_reprova_a_embalagem(tmp_path, scripted):
    snapshot = _snapshot(tmp_path, com_citacoes=False)
    model = scripted(structured=[_proposta(), _proposta(), *_beats()])

    result = _executor(model).run(snapshot, lambda **event: None)

    assert result.gate.code == "packaging_gate_failed"
    assert "descricao_sem_fontes" in {finding.code for finding in result.gate.findings}


def test_aviso_ia_desligado_nao_entra_na_descricao(tmp_path, scripted):
    snapshot = _snapshot(tmp_path)
    model = scripted(structured=[_proposta(), *_beats()])

    _executor(model, aviso_ia=False).run(snapshot, lambda **event: None)

    embalagem = carregar_modelo(snapshot.run_dir / "video" / "embalagem.json", Embalagem)
    assert AVISO_IA not in embalagem.descricao


def test_aviso_ia_entra_no_hash_de_entrada(tmp_path, scripted):
    """Trocar o aviso muda a descrição; a etapa não pode reaproveitar a antiga."""
    snapshot = _snapshot(tmp_path)

    com = _executor(scripted()).prepare(snapshot).input_hash
    sem = _executor(scripted(), aviso_ia=False).prepare(snapshot).input_hash

    assert com != sem
