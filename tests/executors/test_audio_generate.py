from __future__ import annotations

import json
from pathlib import Path

import httpx

from forge.domain.execucao import FailureClass
from forge.executors.audio_generate import (
    FALHAS_DE_SERVIDOR,
    AudioGenerateClient,
    AudioRequest,
    montar_payload,
)
from forge.infrastructure.config import Settings

WAV = b"RIFF" + b"\0" * 40 + b"dados"


def _settings(tmp_path: Path, **kwargs) -> Settings:
    root = tmp_path / "audio-generate"
    return Settings(
        _env_file=None,
        audio_generate_dir=root,
        tts_model=root / "model.gguf",
        tts_voice_reference=root / "voice.wav",
        **kwargs,
    )


class Servidor:
    url = "http://127.0.0.1:9999"
    backend = "vulkan"


def _client(tmp_path, handler, **settings_kwargs):
    return AudioGenerateClient(
        _settings(tmp_path, **settings_kwargs),
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _erro(status, mensagem):
    return lambda request: httpx.Response(
        status, json={"error": {"message": mensagem, "type": "server_error"}}
    )


def test_payload_leva_clonagem_no_nivel_de_cima(tmp_path):
    settings = _settings(tmp_path)
    p = montar_payload(AudioRequest("b001", "<|emotion:calm|>Olá", seed=7), settings)
    assert p["model"] == "higgs"
    assert p["response_format"] == "wav"
    assert p["voice_ref"] == str(settings.resolved_tts_voice_reference)
    assert p["reference_text"] == settings.tts_reference_text
    assert p["seed"] == 7
    assert p["input"] == "Olá"
    assert "options" not in p
    assert "max_tokens" not in p


def test_seed_ausente_usa_tts_seed(tmp_path):
    p = montar_payload(AudioRequest("b001", "Olá"), _settings(tmp_path, tts_seed=43))
    assert p["seed"] == 43


def test_max_tokens_vai_quando_definido(tmp_path):
    p = montar_payload(AudioRequest("b001", "Olá", max_tokens=20), _settings(tmp_path))
    assert p["max_tokens"] == 20


def test_quebras_de_linha_viram_espaco(tmp_path):
    p = montar_payload(AudioRequest("b001", "Uma\r\nduas"), _settings(tmp_path))
    assert p["input"] == "Uma  duas"


def test_grava_wav_atomico_com_nome_canonico(tmp_path):
    recebido = []

    def handler(request):
        recebido.append((request.url, json.loads(request.content)))
        return httpx.Response(200, content=WAV, headers={"Content-Type": "audio/wav"})

    destino = tmp_path / "run" / "audio"
    outcome = _client(tmp_path, handler).synthesize(AudioRequest("b001", "Texto"), Servidor(), destino)

    assert outcome.ok
    assert outcome.path == destino / "b001.wav"
    assert outcome.path.read_bytes() == WAV
    assert list(destino.glob("*.tmp")) == []
    assert str(recebido[0][0]) == "http://127.0.0.1:9999/v1/audio/speech"
    assert recebido[0][1]["input"] == "Texto"


def test_pedido_usa_tts_item_timeout(tmp_path):
    timeouts = []

    def handler(request):
        timeouts.append(request.extensions["timeout"])
        return httpx.Response(200, content=WAV)

    _client(tmp_path, handler, tts_item_timeout=17).synthesize(
        AudioRequest("b001", "Texto"), Servidor(), tmp_path / "out"
    )
    assert timeouts[0]["read"] == 17


def test_500_max_tokens_classifica_deterministico(tmp_path):
    handler = _erro(500, "Higgs TTS generation reached max_tokens before EOC")
    outcome = _client(tmp_path, handler).synthesize(AudioRequest("b001", "Texto"), Servidor(), tmp_path / "out")

    assert outcome.failure.code == "tts_max_tokens_before_eoc"
    assert outcome.failure.failure_class is FailureClass.DETERMINISTIC
    assert outcome.failure.retriable is False
    assert not (tmp_path / "out" / "b001.wav").exists()


def test_500_oom_vulkan_e_falha_de_servidor(tmp_path):
    handler = _erro(500, "ggml_vulkan: Device memory allocation of size 123 failed")
    outcome = _client(tmp_path, handler).synthesize(AudioRequest("b001", "Texto"), Servidor(), tmp_path / "out")

    assert outcome.failure.code == "tts_vulkan_oom"
    assert outcome.failure.code in FALHAS_DE_SERVIDOR


def test_conexao_recusada_e_timeout_viram_servidor_indisponivel(tmp_path):
    for erro in (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError):
        def handler(request, erro=erro):
            raise erro("falhou", request=request)

        outcome = _client(tmp_path, handler).synthesize(
            AudioRequest("b001", "Texto"), Servidor(), tmp_path / "out"
        )
        assert outcome.failure.code == "tts_servidor_indisponivel", erro
        assert outcome.failure.code in FALHAS_DE_SERVIDOR


def test_outro_500_e_process_failed_com_mensagem_truncada(tmp_path):
    handler = _erro(500, "could not open WAV input: C:/x.wav" + "y" * 6000)
    outcome = _client(tmp_path, handler).synthesize(AudioRequest("b001", "Texto"), Servidor(), tmp_path / "out")

    assert outcome.failure.code == "tts_process_failed"
    assert outcome.failure.code not in FALHAS_DE_SERVIDOR
    assert len(outcome.stderr) == 4096
    assert outcome.failure.services["status"] == 500


def test_item_key_invalido_nao_escreve_fora_do_destino(tmp_path):
    chamadas = []

    def handler(request):
        chamadas.append(request)
        return httpx.Response(200, content=WAV)

    outcome = _client(tmp_path, handler).synthesize(AudioRequest("../x", "Texto"), Servidor(), tmp_path / "out")

    assert not outcome.ok
    assert chamadas == []
    assert not (tmp_path / "x.wav").exists()


def test_resposta_200_vazia_nao_e_sucesso(tmp_path):
    outcome = _client(tmp_path, lambda r: httpx.Response(200, content=b"")).synthesize(
        AudioRequest("b001", "Texto"), Servidor(), tmp_path / "out"
    )
    assert not outcome.ok
    assert not (tmp_path / "out" / "b001.wav").exists()
