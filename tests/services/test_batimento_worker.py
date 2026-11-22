from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from forge.services.batimento_worker import BatimentoWorker, caminho_batimento, ler_batimento
from forge.services.saude import ServiceState

T0 = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


class Inspector:
    def __init__(self, vivos: set[int]) -> None:
        self.vivos = vivos

    def is_alive(self, pid: int) -> bool:
        return pid in self.vivos


def _gravar(caminho: Path, *, pid: int, visto_em: datetime) -> None:
    caminho.write_text(json.dumps({
        "worker_id": "forge-worker",
        "pid": pid,
        "iniciado_em": T0.isoformat(),
        "visto_em": visto_em.isoformat(),
    }), encoding="utf-8")


def test_sem_arquivo_o_worker_nao_esta_rodando(tmp_path):
    leitura = ler_batimento(tmp_path / ".worker-batimento.json", intervalo=5, agora=T0)
    assert leitura.state == ServiceState.UNAVAILABLE
    assert "não está rodando" in leitura.message


def test_batimento_recente_de_pid_vivo_esta_disponivel(tmp_path):
    caminho = tmp_path / ".worker-batimento.json"
    _gravar(caminho, pid=4242, visto_em=T0)
    leitura = ler_batimento(caminho, intervalo=5, agora=T0 + timedelta(seconds=4),
                            inspector=Inspector({4242}))
    assert leitura.state == ServiceState.AVAILABLE
    assert "4242" in leitura.message


def test_pid_morto_e_worker_que_caiu(tmp_path):
    caminho = tmp_path / ".worker-batimento.json"
    _gravar(caminho, pid=4242, visto_em=T0)
    leitura = ler_batimento(caminho, intervalo=5, agora=T0 + timedelta(seconds=2),
                            inspector=Inspector(set()))
    assert leitura.state == ServiceState.UNAVAILABLE
    assert "parou" in leitura.message


def test_pid_vivo_sem_batimento_recente_esta_travado(tmp_path):
    caminho = tmp_path / ".worker-batimento.json"
    _gravar(caminho, pid=4242, visto_em=T0)
    leitura = ler_batimento(caminho, intervalo=5, agora=T0 + timedelta(seconds=40),
                            inspector=Inspector({4242}))
    assert leitura.state == ServiceState.DEGRADED
    assert "40 s" in leitura.message


def test_arquivo_ilegivel_nao_derruba_a_sonda(tmp_path):
    caminho = tmp_path / ".worker-batimento.json"
    caminho.write_text("{quebrado", encoding="utf-8")
    leitura = ler_batimento(caminho, intervalo=5, agora=T0)
    assert leitura.state == ServiceState.DEGRADED


def test_batimento_grava_enquanto_roda_e_apaga_ao_parar(tmp_path):
    caminho = tmp_path / "sub" / ".worker-batimento.json"
    with BatimentoWorker(caminho, worker_id="w1", intervalo=60, agora=lambda: T0):
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        assert dados["worker_id"] == "w1"
        assert dados["pid"] == os.getpid()
        assert ler_batimento(caminho, intervalo=60, agora=T0).state == ServiceState.AVAILABLE
    assert not caminho.exists()


def test_falha_de_escrita_nao_derruba_o_worker(tmp_path, monkeypatch):
    caminho = tmp_path / ".worker-batimento.json"

    def recusar(*_args, **_kwargs):
        raise PermissionError("arquivo em uso")

    monkeypatch.setattr("forge.services.batimento_worker.os.replace", recusar)
    batimento = BatimentoWorker(caminho, worker_id="w1", intervalo=60, agora=lambda: T0)
    batimento.bater()  # não levanta


def test_caminho_fica_na_raiz_do_estado_da_gpu(tmp_path):
    from forge.infrastructure.config import Settings

    settings = Settings(_env_file=None, output_dir=tmp_path / "roteiros")
    assert caminho_batimento(settings) == tmp_path / ".worker-batimento.json"
