import httpx
import pytest

from forge.gpu.broker import LiberacaoFalhou
from forge.gpu.liberadores import liberar_imagem, liberar_llm, liberar_tts
from forge.infrastructure.config import Settings


def _settings(**kwargs):
    return Settings(_env_file=None, gpu_liberacao_timeout=0.5, **kwargs)


class _Proc:
    def __init__(self, returncode=0):
        self.returncode = returncode
        self.stdout = ""
        self.stderr = ""


def test_liberar_llm_chama_o_lms_e_confirma(monkeypatch):
    chamadas = []

    def executar(cmd, **kwargs):
        chamadas.append(cmd)
        return _Proc()

    def handler(request):
        assert request.url.path == "/api/v0/models"
        return httpx.Response(200, json={"data": [
            {"id": "qwen", "state": "not-loaded"},
        ]})

    cliente = httpx.Client(transport=httpx.MockTransport(handler),
                           base_url="http://lm.test")
    liberar_llm(_settings(), executar=executar, cliente=cliente)

    assert chamadas and chamadas[0][1:] == ["unload", "--all"]


def test_liberar_llm_estoura_se_o_modelo_continuar_carregado():
    def handler(request):
        return httpx.Response(200, json={"data": [
            {"id": "qwen", "state": "loaded"},
        ]})

    cliente = httpx.Client(transport=httpx.MockTransport(handler),
                           base_url="http://lm.test")
    with pytest.raises(LiberacaoFalhou):
        liberar_llm(_settings(), executar=lambda cmd, **k: _Proc(), cliente=cliente)


def test_liberar_llm_com_binario_ausente_apenas_avisa():
    """Serviço que não está no ar não tem o que liberar."""
    def executar(cmd, **kwargs):
        raise FileNotFoundError(cmd[0])

    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    cliente = httpx.Client(transport=httpx.MockTransport(handler),
                           base_url="http://lm.test")
    liberar_llm(_settings(), executar=executar, cliente=cliente)  # não levanta


def test_liberar_imagem_chama_free_e_espera_vram():
    rotas = []

    def handler(request):
        rotas.append((request.method, request.url.path))
        if request.url.path == "/free":
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"devices": [
            {"name": "rx580", "vram_free": 7_000_000_000},
        ]})

    cliente = httpx.Client(transport=httpx.MockTransport(handler),
                           base_url="http://comfy.test")
    liberar_imagem(_settings(comfy_vram_livre_min=6_000_000_000), cliente=cliente)

    assert ("POST", "/free") in rotas
    assert ("GET", "/system_stats") in rotas


def test_liberar_imagem_estoura_se_a_vram_nao_baixar():
    def handler(request):
        if request.url.path == "/free":
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"devices": [
            {"name": "rx580", "vram_free": 100_000_000},
        ]})

    cliente = httpx.Client(transport=httpx.MockTransport(handler),
                           base_url="http://comfy.test")
    with pytest.raises(LiberacaoFalhou):
        liberar_imagem(_settings(comfy_vram_livre_min=6_000_000_000), cliente=cliente)


def test_liberar_imagem_com_comfy_fora_do_ar_apenas_avisa():
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    cliente = httpx.Client(transport=httpx.MockTransport(handler),
                           base_url="http://comfy.test")
    liberar_imagem(_settings(), cliente=cliente)  # não levanta


def test_liberar_tts_e_no_op():
    """O audiocpp_cli morre sozinho ao terminar o trecho; não há o que descarregar."""
    liberar_tts(_settings())
