from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from forge.domain.operacao import (
    ETAPAS,
    CommandStatus,
    CommandType,
    Run,
    RunStatus,
    StageName,
    StageStatus,
    dependentes_de,
)


def test_ordem_canônica_põe_audio_antes_de_imagens():
    assert ETAPAS == (
        StageName.PREPARACAO,
        StageName.PESQUISA,
        StageName.ROTEIRO,
        StageName.PLANO_MIDIA,
        StageName.AUDIO,
        StageName.IMAGENS,
        StageName.MONTAGEM,
        StageName.VALIDACAO,
    )
    assert ETAPAS.index(StageName.AUDIO) < ETAPAS.index(StageName.IMAGENS)


def test_dependentes_de_roteiro_inclui_tudo_apos_roteiro():
    assert dependentes_de(StageName.ROTEIRO) == (
        StageName.ROTEIRO,
        StageName.PLANO_MIDIA,
        StageName.AUDIO,
        StageName.IMAGENS,
        StageName.MONTAGEM,
        StageName.VALIDACAO,
    )


def test_run_recusa_prioridade_fora_de_0_a_100():
    with pytest.raises(ValidationError):
        Run(
            id="r1",
            video_id="v1",
            status=RunStatus.QUEUED,
            priority=101,
            queue_position=1,
            config_snapshot={},
            workflow_version=1,
            git_commit="abc",
            created_at=datetime.now(UTC),
        )


def test_enums_serializam_com_valores_estaveis():
    assert RunStatus.PAUSING.value == "pausing"
    assert StageStatus.INVALIDATED.value == "invalidated"
    assert CommandType.RETRY_STAGE.value == "retry_stage"
    assert CommandStatus.PENDING.value == "pending"
