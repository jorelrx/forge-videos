import pytest

from forge.gpu.broker import Broker, GPUOcupada


def _broker(tmp_path, registro, **kwargs):
    """Broker com liberadores que só anotam quem foi liberado."""
    return Broker(
        lock_path=tmp_path / "gpu.lock",
        estado_path=tmp_path / "residente.json",
        liberadores={
            "llm": lambda: registro.append("llm"),
            "tts": lambda: registro.append("tts"),
            "imagem": lambda: registro.append("imagem"),
        },
        **kwargs,
    )


def test_primeiro_uso_nao_libera_nada(tmp_path):
    registro = []
    b = _broker(tmp_path, registro)

    with b.exclusivo("llm"):
        pass

    assert registro == []
    assert b.residente() == "llm"


def test_trocar_de_recurso_libera_o_anterior(tmp_path):
    registro = []
    b = _broker(tmp_path, registro)

    with b.exclusivo("llm"):
        pass
    with b.exclusivo("imagem"):
        pass

    assert registro == ["llm"]
    assert b.residente() == "imagem"


def test_mesmo_recurso_duas_vezes_nao_recarrega(tmp_path):
    """Trocar por item pagaria um reload de modelo por item — o slot é por fase."""
    registro = []
    b = _broker(tmp_path, registro)

    with b.exclusivo("imagem"):
        pass
    with b.exclusivo("imagem"):
        pass

    assert registro == []


def test_residente_sobrevive_a_uma_instancia_nova(tmp_path):
    """O modelo continua carregado no serviço externo depois que o forge sai."""
    registro = []
    with _broker(tmp_path, registro).exclusivo("llm"):
        pass

    outro = _broker(tmp_path, registro)
    with outro.exclusivo("tts"):
        pass

    assert registro == ["llm"]


def test_recurso_sem_gpu_nao_disputa_o_slot(tmp_path):
    """FORGE_TTS_BACKEND=cpu: a narração roda na CPU e não reivindica a placa."""
    registro = []
    b = _broker(tmp_path, registro, sem_gpu=frozenset({"tts"}))

    with b.exclusivo("imagem"):
        pass
    with b.exclusivo("tts"):
        pass

    assert registro == []
    assert b.residente() == "imagem"


def test_segundo_processo_espera_e_estoura(tmp_path):
    registro = []
    a = _broker(tmp_path, registro, timeout_lock=0.1)
    b = _broker(tmp_path, registro, timeout_lock=0.1)

    with a.exclusivo("imagem"):
        with pytest.raises(GPUOcupada):
            with b.exclusivo("llm"):
                pass


def test_liberacao_que_estoura_solta_o_lock(tmp_path):
    """Liberador quebrado não pode deixar a GPU trancada para sempre."""
    def explode():
        raise RuntimeError("lms sumiu")

    b = Broker(
        lock_path=tmp_path / "gpu.lock",
        estado_path=tmp_path / "residente.json",
        liberadores={"llm": explode, "imagem": lambda: None},
        timeout_lock=0.1,
    )

    with b.exclusivo("llm"):
        pass
    with pytest.raises(RuntimeError):
        with b.exclusivo("imagem"):
            pass

    # o lock foi solto: um novo uso não estoura por timeout
    with b.exclusivo("llm"):
        pass


def test_estado_ilegivel_libera_todos_os_recursos(tmp_path):
    """Estado corrompido significa que ALGO foi reivindicado e perdemos o
    registro de quem. Não existe "próximo liberador" que cubra isso: `_trocar`
    só libera o residente registrado, então tratar corrupção como placa vazia
    deixaria o modelo carregado para sempre."""
    registro = []
    b = _broker(tmp_path, registro)
    (tmp_path / "residente.json").write_text("{truncad", encoding="utf-8")

    with b.exclusivo("imagem"):
        pass

    assert sorted(registro) == ["imagem", "llm", "tts"]
    assert b.residente() == "imagem"


def test_arquivo_ausente_continua_sendo_placa_vazia(tmp_path):
    """O oposto do teste acima: sem arquivo, ninguém reivindicou nada e liberar
    seria pagar reload à toa."""
    registro = []
    b = _broker(tmp_path, registro)

    assert b.residente() is None
    with b.exclusivo("imagem"):
        pass
    assert registro == []


def test_escrita_interrompida_nao_apaga_o_residente(tmp_path, monkeypatch):
    """O estado é reescrito exatamente quando um modelo ESTÁ carregado. Uma
    escrita não-atômica o truncaria no pior momento possível."""
    from forge.gpu import broker as mod

    registro = []
    b = _broker(tmp_path, registro)
    with b.exclusivo("llm"):
        pass

    def _corte(*args):
        raise OSError("corte de energia")

    monkeypatch.setattr(mod.os, "replace", _corte)
    with pytest.raises(OSError):
        b._gravar("imagem")

    assert b.residente() == "llm"
