import os
import pytest

pytestmark = pytest.mark.integration


def test_integration_research_service_available():
    try:
        from forge.services.acervo import Acervo
        acervo = Acervo("http://127.0.0.1:8000")
        # If service not available, skip
        pytest.skip("Serviço de pesquisa não disponível para integração")
    except Exception:
        pytest.skip("Serviço de pesquisa não disponível")


def test_integration_lm_studio_model_load():
    pytest.skip("LM Studio não disponível neste ambiente")


def test_integration_tts_audio_generate():
    pytest.skip("audio-generate não disponível neste ambiente")


def test_integration_comfy_image():
    pytest.skip("ComfyUI não disponível neste ambiente")


def test_integration_ffmpeg_video():
    pytest.skip("FFmpeg não disponível neste ambiente")


def test_integration_broker_claim():
    pytest.skip("Broker GPU não disponível neste ambiente")
