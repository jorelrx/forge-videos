import httpx
import pytest

from forge.gpu.broker import LiberacaoFalhou
from forge.gpu.liberadores import (
    liberar_imagem,
    liberar_llm,
    liberar_tts,
    montar_broker,
    montar_liberadores,
)
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


def test_montar_liberadores_tem_as_tres_chaves_e_sao_chamaveis():
    liberadores = montar_liberadores(_settings())

    assert set(liberadores) == {"llm", "tts", "imagem"}
    assert all(callable(f) for f in liberadores.values())
    # llm e imagem batem em serviço real — não invocar aqui. tts é no-op, seguro.
    liberadores["tts"]()


def test_montar_broker_vulkan_disputa_o_slot(tmp_path):
    broker = montar_broker(
        _settings(tts_backend="vulkan", provider="lm-studio"), base=tmp_path
    )

    assert broker.sem_gpu == frozenset()
    assert broker.timeout_lock == _settings().gpu_lock_timeout
    assert broker.lock_path == tmp_path / ".gpu.lock"
    assert broker.estado_path == tmp_path / ".gpu-residente.json"


def test_montar_broker_cpu_nao_disputa_o_slot(tmp_path):
    """tts_backend=cpu tira o TTS da disputa pela GPU — regressão aqui vira
    contenção silenciosa em produção, não uma falha de teste."""
    broker = montar_broker(
        _settings(tts_backend="cpu", provider="lm-studio"), base=tmp_path
    )

    assert broker.sem_gpu == frozenset({"tts"})


def test_liberar_llm_poe_prazo_no_lms():
    """Sem `timeout=`, um lms.exe travado pendura esta chamada DENTRO do lock da
    GPU e todo outro processo do forge morre com GPUOcupada."""
    kwargs_vistos = {}

    def executar(cmd, **kwargs):
        kwargs_vistos.update(kwargs)
        return _Proc()

    def handler(request):
        return httpx.Response(200, json={"data": []})

    cliente = httpx.Client(transport=httpx.MockTransport(handler),
                           base_url="http://lm.test")
    settings = _settings()
    liberar_llm(settings, executar=executar, cliente=cliente)

    assert kwargs_vistos["timeout"] == settings.gpu_liberacao_timeout


def test_liberar_llm_com_lms_travado_e_modelo_ainda_carregado_estoura():
    """`lms unload --all` travado é o oposto do binário ausente: o LM Studio
    muito provavelmente está NO AR e o modelo continua residente. Retornar sem
    conferir declararia a liberação feita e o próximo consumidor alocaria numa
    placa cheia — por isso cai para `_esperar`, que aqui vê `state: loaded` e
    estoura."""
    import subprocess

    def executar(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 0))

    def handler(request):
        return httpx.Response(200, json={"data": [
            {"id": "qwen", "state": "loaded"},
        ]})

    cliente = httpx.Client(transport=httpx.MockTransport(handler),
                           base_url="http://lm.test")
    with pytest.raises(LiberacaoFalhou):
        liberar_llm(_settings(), executar=executar, cliente=cliente)


def test_liberar_llm_com_lms_travado_mas_ja_descarregado_nao_estoura():
    """Mesmo `lms unload --all` travado, mas `/api/v0/models` já não reporta
    nada carregado: a confirmação por polling é quem decide, e aqui ela
    autoriza a liberação mesmo sem o `lms` ter respondido."""
    import subprocess

    def executar(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 0))

    def handler(request):
        return httpx.Response(200, json={"data": []})

    cliente = httpx.Client(transport=httpx.MockTransport(handler),
                           base_url="http://lm.test")
    liberar_llm(_settings(), executar=executar, cliente=cliente)  # não levanta


def test_lm_studio_ocupado_nao_conta_como_liberado():
    """LM Studio VIVO e ocupado responde ReadTimeout, que é um HTTPError. Ler
    isso como "fora do ar" declara a liberação feita e manda o SDXL para uma
    placa que ainda tem 6 GB de Qwen."""
    def handler(request):
        raise httpx.ReadTimeout("busy", request=request)

    cliente = httpx.Client(transport=httpx.MockTransport(handler),
                           base_url="http://lm.test")
    with pytest.raises(LiberacaoFalhou):
        liberar_llm(_settings(), executar=lambda cmd, **k: _Proc(), cliente=cliente)


def test_lm_studio_que_recusa_conexao_conta_como_fora_do_ar():
    """ConnectTimeout é irmã de ConnectError apesar de ser TimeoutException:
    nunca chegou a abrir a conexão, então não há serviço para liberar."""
    def handler(request):
        raise httpx.ConnectTimeout("no route", request=request)

    cliente = httpx.Client(transport=httpx.MockTransport(handler),
                           base_url="http://lm.test")
    liberar_llm(_settings(), executar=lambda cmd, **k: _Proc(), cliente=cliente)


def test_comfy_ocupado_nao_conta_como_liberado():
    def handler(request):
        if request.url.path == "/free":
            return httpx.Response(200, json={})
        raise httpx.ReadTimeout("busy", request=request)

    cliente = httpx.Client(transport=httpx.MockTransport(handler),
                           base_url="http://comfy.test")
    with pytest.raises(LiberacaoFalhou):
        liberar_imagem(_settings(), cliente=cliente)


def test_vram_livre_olha_o_device_mais_apertado():
    """Um segundo device respaldado por RAM do sistema faria o `max` sempre
    passar do limiar e a confirmação viraria no-op."""
    def handler(request):
        if request.url.path == "/free":
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"devices": [
            {"name": "rx580", "vram_free": 100_000_000},
            {"name": "cpu", "vram_free": 32_000_000_000},
        ]})

    cliente = httpx.Client(transport=httpx.MockTransport(handler),
                           base_url="http://comfy.test")
    with pytest.raises(LiberacaoFalhou):
        liberar_imagem(_settings(comfy_vram_livre_min=6_000_000_000), cliente=cliente)


def test_montar_broker_llm_local_disputa_o_slot(tmp_path):
    """lm-studio: o modelo mora na placa e precisa ser despejado antes do TTS."""
    broker = montar_broker(_settings(provider="lm-studio"), base=tmp_path)

    assert "llm" not in broker.sem_gpu


def test_montar_broker_llm_na_nuvem_nao_disputa_o_slot(tmp_path):
    """Anthropic/OpenAI não gastam um byte de VRAM. Tomar o slot despejaria um
    TTS ou SDXL residente à toa e serializaria o run na nuvem contra a GPU."""
    for provider in ("anthropic", "openai"):
        broker = montar_broker(_settings(provider=provider), base=tmp_path)
        assert "llm" in broker.sem_gpu, provider


def test_montar_broker_sem_base_usa_a_raiz_do_output(tmp_path):
    """Um literal relativo daria um .gpu.lock por diretório de trabalho, e dois
    processos acreditariam ser donos da mesma placa."""
    settings = _settings(output_dir=tmp_path / "saida" / "roteiros")

    broker = montar_broker(settings)

    assert broker.lock_path == tmp_path / "saida" / ".gpu.lock"
    assert broker.estado_path == tmp_path / "saida" / ".gpu-residente.json"
