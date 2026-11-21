import shutil

import numpy as np
import pytest
import soundfile as sf
from PIL import Image

from forge.domain.embalagem import Embalagem, ThumbnailProposta, TituloProposto
from forge.domain.execucao import ArtifactOutput, GateResult, RunSnapshot, StageExecutionResult
from forge.domain.midia import Beat, BlocoNarracao, PlanoMidia
from forge.domain.operacao import StageName
from forge.executors import abertura
from forge.executors.audio import AudioExecutor
from forge.executors.ffmpeg import probe_duration
from forge.executors.imagens import ImageExecutor
from forge.infrastructure.config import Settings


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="FFmpeg indisponível")
def test_previa_renderiza_prefixo_e_regenera_apenas_arquivo_editado(tmp_path, monkeypatch):
    chamadas = {"audio": [], "imagem": []}

    def gerar_audio(self, context, plan, emit):
        outputs = []
        for item in plan.items:
            chamadas["audio"].append(item.item_key)
            relative = f"video/audio/{item.item_key}.wav"
            arquivo = context.run_dir / relative
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            amostras = np.sin(2 * np.pi * 220 * np.arange(18_000) / 24_000) * 0.2
            sf.write(arquivo, amostras, 24_000)
            outputs.append(ArtifactOutput(
                item_key=item.item_key, kind="audio.wav", relative_path=relative,
                mime_type="audio/wav", metadata={"duration": 0.75, "seed": self.settings.tts_seed},
            ))
        return StageExecutionResult(current_items=len(outputs), total_items=len(outputs), artifacts=outputs)

    def gerar_imagem(self, context, plan, emit):
        item = plan.items[0]
        chamadas["imagem"].append(item.item_key)
        relative = f"video/images/{item.item_key}.png"
        arquivo = context.run_dir / relative
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1024, 576), (41, 54, 93)).save(arquivo)
        output = ArtifactOutput(
            item_key=item.item_key, kind="image.png", relative_path=relative, mime_type="image/png",
        )
        return StageExecutionResult(current_items=1, total_items=1, artifacts=[output])

    def aprovar(*args, **kwargs):
        return GateResult(approved=True, code="ok")

    monkeypatch.setattr(AudioExecutor, "execute", gerar_audio)
    monkeypatch.setattr(AudioExecutor, "validate", aprovar)
    monkeypatch.setattr(ImageExecutor, "execute", gerar_imagem)
    monkeypatch.setattr(ImageExecutor, "validate", aprovar)
    monkeypatch.setattr(ImageExecutor, "_thumbnail", lambda *args: None)
    monkeypatch.setattr(abertura, "SEGUNDOS", 1.4)
    context = RunSnapshot(
        run_id="run", video_id="video", tema="Tema", tese=None,
        stage=StageName.PLANO_MIDIA, attempt=1, run_dir=tmp_path / "run", output_root=tmp_path,
        config_snapshot={}, artifacts=[], work_items=[],
    )
    plano = PlanoMidia(
        blocos=[BlocoNarracao(id=f"b00{i}", secao="Gancho", texto="Um trecho.") for i in (1, 2, 3)],
        beats=[Beat(id=f"i00{i}", bloco_id=f"b00{i}", prompt="A clock.") for i in (1, 2, 3)],
    )
    embalagem = Embalagem(
        titulos=[TituloProposto(texto="Título")],
        thumbnail=ThumbnailProposta(texto="Imagem", prompt="Céu"), descricao="Descrição",
    )
    settings = Settings(_env_file=None, image_provider="comfyui")
    outputs = abertura.renderizar_abertura(context, plano, embalagem, settings, lambda **_: None)
    assert chamadas == {"audio": ["b001", "b002"], "imagem": ["i001", "i002"]}
    previa = outputs[-1]
    assert previa.kind == "previa_abertura"
    assert probe_duration(context.run_dir / previa.relative_path) == pytest.approx(1.4, abs=0.1)

    ajustes = {"imagem": {"i002": {"revisao": 1, "orientacao": "Uma nuvem"}}}
    revisao = context.model_copy(update={"attempt": 2, "config_snapshot": {"ajustes_abertura": ajustes}})
    plano_revisado = abertura.aplicar_direcao_visual(plano, ajustes)
    abertura.renderizar_abertura(revisao, plano_revisado, embalagem, settings, lambda **_: None)
    assert chamadas == {"audio": ["b001", "b002"], "imagem": ["i001", "i002", "i002"]}
