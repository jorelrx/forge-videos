from __future__ import annotations

import json
import subprocess
from pathlib import Path

import httpx
import pytest

from forge.executors.audiocpp_server import (
    ContratoServidorQuebrado,
    ServidorIndisponivel,
    ServidorTTS,
    caminho_registro,
)
from forge.infrastructure.config import Settings


class PopenFalso:
    """Processo falso: grava argv, lê o config enquanto o servidor vive."""

    def __init__(self, *, morre_na_subida=False, wait_trava_uma_vez=False):
        self.instancias: list[PopenFalso._Proc] = []
        self.morre_na_subida = morre_na_subida
        self.wait_trava_uma_vez = wait_trava_uma_vez

    class _Proc:
        def __init__(self, dono, argv, kwargs):
            self.argv = argv
            self.kwargs = kwargs
            self.pid = 4321 + len(dono.instancias)
            self.returncode = 1 if dono.morre_na_subida else None
            self.terminados = 0
            self.mortos = 0
            self._trava = dono.wait_trava_uma_vez
            config = Path(argv[argv.index("--config") + 1])
            self.config = json.loads(config.read_text(encoding="utf-8"))
            stdout = kwargs.get("stdout")
            if dono.morre_na_subida and stdout is not None:
                stdout.write(b"audiocpp_server failed: missing required json key: path\n")
                stdout.flush()

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminados += 1

        def kill(self):
            self.mortos += 1
            self.returncode = -9

        def wait(self, timeout=None):
            if self._trava:
                self._trava = False
                raise subprocess.TimeoutExpired(self.argv, timeout)
            if self.returncode is None:
                self.returncode = 0
            return self.returncode

    def __call__(self, argv, **kwargs):
        proc = PopenFalso._Proc(self, argv, kwargs)
        self.instancias.append(proc)
        return proc


def _http(*, health=None, sonda_status=500, sonda_corpo=None, chamadas=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if chamadas is not None:
            chamadas.append((request.method, request.url.path, request.content))
        if request.url.path == "/health":
            return health(request) if health else httpx.Response(200, json={"status": "ok", "models": 1})
        if request.url.path == "/v1/audio/speech":
            corpo = sonda_corpo or {"error": {"message": "could not open WAV input: x.wav"}}
            return httpx.Response(sonda_status, json=corpo)
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _settings(tmp_path: Path, **kwargs) -> Settings:
    return Settings(
        _env_file=None,
        audio_generate_dir=tmp_path / "audio-generate",
        output_dir=tmp_path / "output" / "roteiros",
        **kwargs,
    )


def _servidor(tmp_path, backend="vulkan", *, popen=None, http=None, **settings_kwargs):
    return ServidorTTS(
        _settings(tmp_path, **settings_kwargs), backend,
        pasta_log=tmp_path / "run" / "video" / "audio",
        popen=popen or PopenFalso(), http=http or _http(),
    )


def test_sobe_com_config_path_e_espera_health(tmp_path):
    popen = PopenFalso()
    with _servidor(tmp_path, popen=popen) as servidor:
        proc = popen.instancias[0]
        modelo = proc.config["models"][0]
        settings = _settings(tmp_path)
        assert modelo["path"] == str(settings.resolved_tts_model)
        assert "model" not in modelo
        assert modelo["family"] == "higgs_audio_tts" and modelo["task"] == "tts"
        assert proc.argv[0] == str(settings.resolved_tts_server_binary)
        assert proc.argv[proc.argv.index("--backend") + 1] == "vulkan"
        assert "--no-ui" in proc.argv
        log = Path(proc.argv[proc.argv.index("--log-file") + 1])
        assert log.name == ".servidor-vulkan.log"
        assert "--threads" not in proc.argv
        assert proc.kwargs.get("shell", False) is False
        assert servidor.url == f"http://127.0.0.1:{proc.config['port']}"
        assert servidor.backend == "vulkan"


def test_backend_cpu_passa_threads(tmp_path):
    popen = PopenFalso()
    with _servidor(tmp_path, "cpu", popen=popen):
        argv = popen.instancias[0].argv
        assert argv[argv.index("--threads") + 1] == "12"
        assert argv[argv.index("--backend") + 1] == "cpu"


def test_sonda_manda_voice_ref_inexistente_no_nivel_de_cima(tmp_path):
    chamadas = []
    with _servidor(tmp_path, http=_http(chamadas=chamadas)):
        pass
    sonda = next(json.loads(c) for m, p, c in chamadas if p == "/v1/audio/speech")
    assert "options" not in sonda
    assert not Path(sonda["voice_ref"]).exists()
    assert sonda["reference_text"]


def test_sonda_de_contrato_reprova_servidor_que_ignora_voice_ref(tmp_path):
    popen = PopenFalso()
    with pytest.raises(ContratoServidorQuebrado):
        with _servidor(tmp_path, popen=popen, http=_http(sonda_status=200, sonda_corpo={})):
            pass
    assert popen.instancias[0].returncode is not None


def test_processo_que_sai_antes_do_health_e_indisponivel(tmp_path):
    def health(request):
        raise httpx.ConnectError("recusada", request=request)

    with pytest.raises(ServidorIndisponivel, match="missing required json key"):
        with _servidor(tmp_path, popen=PopenFalso(morre_na_subida=True), http=_http(health=health)):
            pass


def test_health_que_nao_chega_no_prazo_e_indisponivel(tmp_path):
    def health(request):
        raise httpx.ConnectError("recusada", request=request)

    popen = PopenFalso()
    with pytest.raises(ServidorIndisponivel):
        with _servidor(tmp_path, popen=popen, http=_http(health=health), tts_server_start_timeout=0.2):
            pass
    assert popen.instancias[0].returncode is not None


def test_registro_ganha_e_perde_o_pid(tmp_path):
    registro = caminho_registro(_settings(tmp_path))
    with _servidor(tmp_path):
        assert {"pid": 4321, "backend": "vulkan"} in json.loads(registro.read_text(encoding="utf-8"))
    assert json.loads(registro.read_text(encoding="utf-8")) == []


def test_registro_fica_ao_lado_da_raiz_do_output(tmp_path):
    assert caminho_registro(_settings(tmp_path)) == tmp_path / "output" / ".tts-servidor.json"


def test_saida_encerra_e_mata_se_terminate_nao_basta(tmp_path):
    popen = PopenFalso(wait_trava_uma_vez=True)
    with _servidor(tmp_path, popen=popen):
        pass
    proc = popen.instancias[0]
    assert proc.terminados == 1 and proc.mortos == 1


def test_reiniciar_sobe_processo_novo(tmp_path):
    popen = PopenFalso()
    with _servidor(tmp_path, popen=popen) as servidor:
        servidor.reiniciar()
        assert len(popen.instancias) == 2
        assert popen.instancias[0].returncode is not None
        assert popen.instancias[1].returncode is None
    assert popen.instancias[1].returncode is not None


def test_falha_ao_registrar_pid_encerra_o_processo(tmp_path, monkeypatch):
    import forge.executors.audiocpp_server as modulo

    original = modulo._alterar_registro
    chamadas = []

    def alterar(caminho, alterar_fn):
        chamadas.append(caminho)
        if len(chamadas) == 1:
            raise PermissionError("registro travado pelo antivírus")
        return original(caminho, alterar_fn)

    monkeypatch.setattr(modulo, "_alterar_registro", alterar)
    popen = PopenFalso()
    with pytest.raises(ServidorIndisponivel, match="registro"):
        with _servidor(tmp_path, popen=popen):
            pass
    assert popen.instancias[0].returncode is not None


class _ProcTeimoso(PopenFalso):
    """Processo que não sai nem com kill (driver Vulkan travado)."""

    def __call__(self, argv, **kwargs):
        proc = super().__call__(argv, **kwargs)

        def wait(timeout=None):
            raise subprocess.TimeoutExpired(argv, timeout)

        proc.wait = wait
        return proc


def test_reiniciar_com_processo_que_nao_morre_e_indisponivel_e_mantem_registro(tmp_path):
    popen = _ProcTeimoso()
    servidor = _servidor(tmp_path, popen=popen)
    servidor.__enter__()
    with pytest.raises(ServidorIndisponivel):
        servidor.reiniciar()
    registro = json.loads(caminho_registro(_settings(tmp_path)).read_text(encoding="utf-8"))
    assert {"pid": 4321, "backend": "vulkan"} in registro


def test_saida_com_processo_que_nao_morre_nao_levanta(tmp_path):
    popen = _ProcTeimoso()
    with _servidor(tmp_path, popen=popen):
        pass
    registro = json.loads(caminho_registro(_settings(tmp_path)).read_text(encoding="utf-8"))
    assert {"pid": 4321, "backend": "vulkan"} in registro
