from __future__ import annotations

from pathlib import Path

import pytest

from forge.domain.execucao import RunSnapshot
from forge.domain.midia import Beat, BeatProposto, BeatsDaSecao, PlanoMidia
from forge.domain.models import Roteiro, Secao
from forge.domain.operacao import StageName
from forge.executors.plano_midia import MediaPlanExecutor, hash_json
from forge.infrastructure.config import Settings
from forge.services.persistencia import carregar_modelo, gravar_modelo


@pytest.fixture(autouse=True)
def embalagem_pronta(monkeypatch):
    """Estes testes são do plano de mídia; a embalagem tem arquivo próprio.

    A etapa embala antes de planejar a mídia. Sem esta troca, cada teste daqui
    teria de roteirizar também a proposta de embalagem e as citações.
    """
    from forge.domain.embalagem import (
        Capitulo, Embalagem, ThumbnailProposta, TituloProposto,
    )

    pronta = Embalagem(
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
    monkeypatch.setattr(
        "forge.executors.plano_midia.embalar", lambda *args, **kwargs: pronta,
    )


def _snapshot(tmp_path: Path) -> RunSnapshot:
    root = tmp_path / "runs"
    snapshot = RunSnapshot(
        run_id="run-1",
        video_id="video-1",
        tema="Tema",
        tese="Tese",
        stage=StageName.PLANO_MIDIA,
        attempt=1,
        output_root=root,
        run_dir=root / "run-1",
        config_snapshot={"midia_alvo_segundos": 15},
        artifacts=[],
        work_items=[],
    )
    roteiro = Roteiro(
        tema="Tema",
        tese="Tese",
        secoes=[
            Secao(
                nome="Gancho",
                conteudo="A primeira frase abre o problema. A segunda mantém a tensão.",
            ),
            Secao(
                nome="Fecho",
                conteudo="A última frase devolve a pergunta ao público.",
            ),
        ],
    )
    gravar_modelo(snapshot.run_dir / "video" / "roteiro.json", roteiro)
    return snapshot


def _model(scripted):
    return scripted(
        structured=[
            BeatsDaSecao(
                beats=[
                    BeatProposto(bloco_id="b001", prompt="a door opening"),
                ]
            ),
            BeatsDaSecao(
                beats=[
                    BeatProposto(bloco_id="b002", prompt="a road at dusk"),
                ]
            ),
        ]
    )


def test_media_plan_reproduces_narration_word_for_word(tmp_path, scripted):
    snapshot = _snapshot(tmp_path)
    events = []
    result = MediaPlanExecutor(
        model=_model(scripted), settings=Settings(_env_file=None, provider="anthropic")
    ).run(
        snapshot, lambda **event: events.append(event)
    )

    plan = carregar_modelo(snapshot.run_dir / "video" / "midia.json", PlanoMidia)

    assert " ".join(block.texto for block in plan.blocos) == (
        "A primeira frase abre o problema. A segunda mantém a tensão. "
        "A última frase devolve a pergunta ao público."
    )
    assert result.gate.approved
    assert result.gate.code == "media_plan_approved"
    assert [event["payload"]["item_key"] for event in events if event["kind"] == "item.planned"] == [
        "b001", "b002", "i001", "i002"
    ]


def test_media_plan_rejects_missing_beat_reference(tmp_path, monkeypatch, scripted):
    snapshot = _snapshot(tmp_path)
    invalid = PlanoMidia(
        blocos=[
            {"id": "b001", "secao": "Gancho", "texto": "A primeira frase abre o problema. A segunda mantém a tensão."},
            {"id": "b002", "secao": "Fecho", "texto": "A última frase devolve a pergunta ao público."},
        ],
        beats=[
            Beat(id="i001", bloco_id="ghost", prompt="a missing block"),
            Beat(id="i002", bloco_id="b002", prompt="a road at dusk"),
        ],
    )
    monkeypatch.setattr("forge.executors.plano_midia.planejar_midia", lambda *args, **kwargs: invalid)

    result = MediaPlanExecutor(
        model=scripted(), settings=Settings(_env_file=None, provider="anthropic")
    ).run(
        snapshot, lambda **event: None
    )

    assert result.gate.code == "media_plan_gate_failed"
    assert result.gate.findings[0].code == "beat_block_missing"


def test_media_item_hash_is_derived_from_canonical_model_json():
    block = {"id": "b001", "secao": "Gancho", "texto": "Uma fala."}

    assert hash_json(block) == (
        "62f76a572160931687da9d507320736df04d0d747839594435f08cf89c5132eb"
    )


def test_media_plan_rejects_crossed_block_and_beat_id_prefixes(tmp_path, monkeypatch, scripted):
    snapshot = _snapshot(tmp_path)
    events = []
    invalid = PlanoMidia(
        blocos=[
            {"id": "i001", "secao": "Gancho", "texto": "A primeira frase abre o problema. A segunda mantém a tensão."},
            {"id": "i002", "secao": "Fecho", "texto": "A última frase devolve a pergunta ao público."},
        ],
        beats=[
            Beat(id="b001", bloco_id="i001", prompt="a door opening"),
            Beat(id="b002", bloco_id="i002", prompt="a road at dusk"),
        ],
    )
    monkeypatch.setattr("forge.executors.plano_midia.planejar_midia", lambda *args, **kwargs: invalid)

    result = MediaPlanExecutor(
        model=scripted(), settings=Settings(_env_file=None, provider="anthropic")
    ).run(snapshot, lambda **event: events.append(event))

    assert {finding.code for finding in result.gate.findings} >= {
        "block_id_invalid", "beat_id_invalid"
    }
    assert not [event for event in events if event["kind"] == "item.planned"]
    assert not (snapshot.run_dir / "video" / "midia.json").exists()
