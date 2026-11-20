"""Revisor de outro provider: o modelo que escreve não revisa o próprio texto."""

from pathlib import Path

from forge.agents.research import ResearchBundle
from forge.domain.execucao import RunSnapshot
from forge.domain.models import Roteiro, Secao
from forge.domain.operacao import StageName
from forge.domain.roteiro import SECOES_NOMES
from forge.executors.roteiro import ScriptExecutor
from forge.infrastructure.config import Settings
from forge.llms.claude import ClaudeChatModel
from forge.llms.model import build_review_model
from forge.services.persistencia import gravar_modelo


def test_sem_review_provider_nao_ha_segundo_modelo():
    assert build_review_model(Settings(_env_file=None, provider='codex')) is None


def test_review_provider_igual_ao_principal_nao_ha_segundo_modelo():
    settings = Settings(_env_file=None, provider='claude', review_provider='claude')
    assert build_review_model(settings) is None


def test_review_provider_diferente_constroi_revisor_com_modelo_proprio():
    settings = Settings(_env_file=None, provider='codex', model='gpt-6.1-sol', review_provider='claude')
    revisor = build_review_model(settings)
    assert isinstance(revisor, ClaudeChatModel)
    # FORGE_MODEL é do escritor: não pode vazar para o revisor.
    assert revisor.model == 'claude-opus-5-5'


def test_review_model_sobrepoe_o_padrao_do_revisor():
    settings = Settings(
        _env_file=None, provider='codex', review_provider='claude',
        review_model='claude-sonnet-5-5',
    )
    assert build_review_model(settings).model == 'claude-sonnet-5-5'


def test_chave_generica_do_escritor_nao_vai_para_o_revisor():
    """`FORGE_API_KEY` é a chave do escritor; cruzá-la manda credencial
    OpenAI para a Anthropic, o 401 opaco que a config existe para evitar."""
    settings = Settings(
        _env_file=None, provider='openai', api_key='sk-openai',
        anthropic_api_key='sk-ant', review_provider='anthropic',
    )
    revisor = build_review_model(settings)
    assert revisor.anthropic_api_key.get_secret_value() == 'sk-ant'


def test_revisor_lm_studio_e_recusado_na_config():
    """Modelo local como revisor exigiria carregar e liberar a VRAM no meio
    da etapa; o broker só sabe fazer isso para o provider principal."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match='lm-studio'):
        Settings(_env_file=None, provider='claude', review_provider='lm-studio')


def _snapshot(tmp_path: Path) -> RunSnapshot:
    root = tmp_path / 'runs'
    return RunSnapshot(
        run_id='run-1', video_id='video-1', tema='Tema', tese='Tese',
        stage=StageName.ROTEIRO, attempt=1, output_root=root,
        run_dir=root / 'run-1', config_snapshot={}, artifacts=[], work_items=[],
    )


def test_hash_da_etapa_muda_com_o_revisor(tmp_path):
    contexto = _snapshot(tmp_path)
    sem = ScriptExecutor(settings=Settings(_env_file=None)).prepare(contexto)
    com = ScriptExecutor(settings=Settings(_env_file=None, review_provider='claude')).prepare(contexto)
    assert sem.input_hash != com.input_hash


def test_hash_nao_muda_sem_revisor_efetivo(tmp_path):
    """Runs antigas não podem perder o roteiro por causa de um revisor que
    não existe (vazio ou igual ao escritor)."""
    contexto = _snapshot(tmp_path)
    base = ScriptExecutor(settings=Settings(_env_file=None, provider='codex')).prepare(contexto)
    igual = ScriptExecutor(settings=Settings(
        _env_file=None, provider='codex', review_provider='codex',
    )).prepare(contexto)
    assert base.input_hash == igual.input_hash


def test_executor_entrega_o_revisor_ao_grafo(tmp_path, monkeypatch):
    contexto = _snapshot(tmp_path)
    contexto.run_dir.mkdir(parents=True)
    gravar_modelo(contexto.run_dir / 'video' / 'research.json', ResearchBundle(
        brief='brief', fontes=[], raw_markdown='raw', passages=[], passage_count=0,
        canonical_paths=[],
    ))
    roteiro = Roteiro(tema='Tema', tese='Tese',
                      secoes=[Secao(nome=n, conteudo='Texto.') for n in SECOES_NOMES])
    capturado = {}

    class Graph:
        def invoke(self, state):
            return {'roteiro': roteiro}

    def build(model, settings, **kwargs):
        capturado.update(kwargs)
        return Graph()

    monkeypatch.setattr('forge.executors.roteiro.build_graph', build)
    settings = Settings(_env_file=None, provider='codex', review_provider='claude')
    executor = ScriptExecutor(settings=settings, model=object())
    executor.execute(contexto, executor.prepare(contexto), lambda **event: None)
    assert isinstance(capturado['revisor'], ClaudeChatModel)
