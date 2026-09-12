# Broker de GPU, plano de mídia e manifesto — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir a infraestrutura que a geração de vídeo exige antes de existir qualquer geração: o slot exclusivo de GPU, o plano de mídia derivado do roteiro, e o manifesto retomável item a item.

**Architecture:** Três peças independentes que se encontram no runner. O broker (`gpu/`) serializa o acesso à placa e descarrega o modelo residente ao trocar de fase. O plano de mídia (`agents/midia.py`) é a última coisa que gasta LLM: fatia o roteiro em blocos de narração com tags de controle validadas e propõe um prompt de imagem por beat visual. O manifesto (`services/manifesto.py`) transforma esse plano numa lista de itens com estado próprio, e o runner (`services/runner.py`) consome os pendentes agrupados por tipo, tomando o slot uma vez por grupo. Nada aqui gera áudio ou imagem — os executores entram por injeção e chegam no plano seguinte.

**Tech Stack:** Python 3.12, `uv`, pydantic v2, pydantic-settings, httpx, filelock, langchain-core, pytest, structlog.

**Spec:** [docs/superpowers/specs/2026-09-06-video-pipeline-design.md](../specs/2026-09-06-video-pipeline-design.md) — sub-projetos S2, S3, S4, mais a decisão D11 do adendo.

## Global Constraints

- Nomes de domínio, de estado e mensagens de log em português; identificadores de código misturam português e inglês. Casar com o arquivo ao redor.
- Log estruturado com `structlog`: `get_logger(__name__)`, campos `chave=valor`, nunca f-string dentro da chamada de log.
- Nenhum teste toca a rede, a GPU, o LM Studio, o ComfyUI ou um binário externo. Modelo é a fixture `scripted`; HTTP é `httpx.MockTransport`; subprocess e liberadores entram por injeção.
- `uv run pytest` roda com `addopts = ["-m", "not integration"]` já configurado — a suíte padrão é offline.
- `docs/superpowers/` está no `.gitignore`. Nunca commitar spec nem plano.
- Todo componente com dependência externa recebe essa dependência por injeção, com o default real montado por uma função `montar_*` separada. É o padrão que `services/acervo.py` já segue com `client`.
- Caminhos do ComfyUI e do LM Studio nunca são literais no código: saem de `Settings`.
- Rodar a suíte com `uv run pytest`. Mensagens de commit em inglês, prefixo `feat:`/`fix:`/`chore:`/`test:`/`docs:`.

---

### Task 1: Broker de GPU — slot exclusivo

O mecanismo do slot, com os liberadores injetados. Os liberadores reais chegam na Task 2, e separar os dois é deliberado: esta tarefa é lógica pura e testável sem nenhum serviço no ar.

**Files:**
- Create: `src/forge/gpu/__init__.py`, `src/forge/gpu/broker.py`
- Create: `tests/gpu/__init__.py`, `tests/gpu/test_broker.py`
- Modify: `pyproject.toml` (dependência `filelock`)
- Modify: `src/forge/infrastructure/config.py` (campos do broker)
- Modify: `tests/test_config.py`

**Interfaces:**
- Consumes: `Settings`.
- Produces:
  - `Recurso = Literal["llm", "tts", "imagem"]`
  - `class GPUOcupada(RuntimeError)`, `class LiberacaoFalhou(RuntimeError)`
  - `class Broker` com `__init__(self, *, lock_path: Path, estado_path: Path, liberadores: dict[str, Callable[[], None]], timeout_lock: float = 900.0, sem_gpu: frozenset[str] = frozenset())`
  - `Broker.exclusivo(recurso: Recurso)` — context manager
  - `Broker.residente() -> str | None`
  - `Settings.gpu_lock_timeout: float`, `Settings.tts_backend: Literal["vulkan", "cpu"]`

- [ ] **Step 1: Adicionar `filelock`**

Em `pyproject.toml`, dentro de `dependencies`, acrescentar `"filelock>=3.13",`.

Um lock entre processos escrito à mão em cima de `os.O_EXCL` precisa de detecção de lock órfão, e errar isso trava a máquina inteira até alguém apagar um arquivo. `filelock` já resolve isso em todas as plataformas.

Run: `uv sync`
Expected: instala `filelock`

- [ ] **Step 2: Escrever os testes do broker**

Criar `tests/gpu/__init__.py` vazio e `tests/gpu/test_broker.py`:

```python
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
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `uv run pytest tests/gpu/test_broker.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'forge.gpu'`

- [ ] **Step 4: Implementar o broker**

Criar `src/forge/gpu/__init__.py` vazio e `src/forge/gpu/broker.py`:

```python
"""Slot exclusivo de GPU.

Uma RX 580 de 8 GB, três consumidores que não cabem juntos: o LLM do LM Studio,
o TTS via Vulkan e o SDXL do ComfyUI. O broker garante um residente por vez e
descarrega o anterior ao trocar.

A troca acontece por FASE, não por item: trocar a cada item pagaria um reload de
modelo por item. Quem entra e sai do mesmo recurso em sequência não paga nada.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, Literal

from filelock import FileLock, Timeout

from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)

Recurso = Literal["llm", "tts", "imagem"]


class GPUOcupada(RuntimeError):
    """Outro processo segura o slot há mais tempo que o timeout."""


class LiberacaoFalhou(RuntimeError):
    """O serviço respondeu mas não confirmou a VRAM livre."""


class Broker:
    def __init__(
        self,
        *,
        lock_path: Path,
        estado_path: Path,
        liberadores: dict[str, Callable[[], None]],
        timeout_lock: float = 900.0,
        sem_gpu: frozenset[str] = frozenset(),
    ) -> None:
        self.lock_path = Path(lock_path)
        self.estado_path = Path(estado_path)
        self.liberadores = liberadores
        self.timeout_lock = timeout_lock
        # Recursos que declaram não usar a placa (TTS na CPU, por exemplo).
        # Eles não disputam o slot nem deslocam o residente.
        self.sem_gpu = sem_gpu

    @contextmanager
    def exclusivo(self, recurso: Recurso) -> Iterator[None]:
        if recurso in self.sem_gpu:
            logger.debug("Recurso não usa GPU", recurso=recurso)
            yield
            return

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock = FileLock(str(self.lock_path), timeout=self.timeout_lock)
        try:
            lock.acquire()
        except Timeout as e:
            raise GPUOcupada(
                f"outro processo segura a GPU há mais de {self.timeout_lock}s"
            ) from e
        try:
            self._trocar(recurso)
            yield
        finally:
            # Solta o lock mesmo se a liberação ou o corpo estourarem: um
            # liberador quebrado não pode trancar a placa para sempre.
            lock.release()

    def residente(self) -> str | None:
        if not self.estado_path.exists():
            return None
        try:
            return json.loads(self.estado_path.read_text(encoding="utf-8"))["recurso"]
        except (ValueError, KeyError):
            # Estado corrompido: tratar como placa vazia é seguro — o pior caso
            # é uma liberação a menos, que o próximo liberador cobre.
            logger.warning("Estado do broker ilegível", path=str(self.estado_path))
            return None

    def _trocar(self, recurso: str) -> None:
        atual = self.residente()
        if atual == recurso:
            logger.debug("Recurso já residente", recurso=recurso)
            return
        if atual is not None:
            logger.info("Liberando GPU", de=atual, para=recurso)
            liberador = self.liberadores.get(atual)
            if liberador is not None:
                liberador()
        self._gravar(recurso)

    def _gravar(self, recurso: str) -> None:
        self.estado_path.parent.mkdir(parents=True, exist_ok=True)
        self.estado_path.write_text(
            json.dumps({"recurso": recurso}), encoding="utf-8"
        )
```

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest tests/gpu/test_broker.py -v`
Expected: PASS, 7 testes

- [ ] **Step 6: Escrever o teste dos defaults de config**

Acrescentar a `tests/test_config.py`:

```python
def test_broker_tem_defaults():
    from forge.infrastructure.config import Settings

    s = Settings(_env_file=None)
    assert s.gpu_lock_timeout == 900.0
    assert s.tts_backend == "vulkan"
```

- [ ] **Step 7: Rodar e ver falhar**

Run: `uv run pytest tests/test_config.py::test_broker_tem_defaults -v`
Expected: FAIL com `AttributeError`

- [ ] **Step 8: Adicionar os campos**

Em `src/forge/infrastructure/config.py`, dentro de `Settings`, junto dos campos do acervo:

```python
    # Gerência da GPU. Ver gpu/broker.py: um recurso residente por vez.
    gpu_lock_timeout: float = 900.0
    # `cpu` faz a narração não disputar o slot, liberando-a para rodar
    # concorrente com a fase de imagem.
    tts_backend: Literal["vulkan", "cpu"] = "vulkan"
```

`Literal` já vem importado de `typing` no topo do arquivo; conferir.

- [ ] **Step 9: Rodar a suíte**

Run: `uv run pytest`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat: add GPU broker with an exclusive resource slot

One 8GB card, three consumers that do not fit together. The broker keeps one
resident at a time and unloads the previous one when switching. Switching is
per phase, not per item: per-item switching would pay a model reload per item.
Releasers are injected so the whole mechanism is testable with no service up.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Liberadores reais

**Files:**
- Create: `src/forge/gpu/liberadores.py`
- Create: `tests/gpu/test_liberadores.py`
- Modify: `src/forge/infrastructure/config.py` (ComfyUI, LM Studio, timeouts de liberação)
- Modify: `tests/test_config.py`

**Interfaces:**
- Consumes: `LiberacaoFalhou` (Task 1), `Settings`.
- Produces:
  - `liberar_llm(settings, *, executar=subprocess.run, cliente: httpx.Client | None = None) -> None`
  - `liberar_imagem(settings, *, cliente: httpx.Client | None = None) -> None`
  - `liberar_tts(settings) -> None`
  - `montar_liberadores(settings) -> dict[str, Callable[[], None]]`
  - `montar_broker(settings) -> Broker`
  - `Settings.comfy_url: str`, `Settings.comfy_vram_livre_min: int`, `Settings.lms_bin: str`, `Settings.gpu_liberacao_timeout: float`

- [ ] **Step 1: Escrever os testes**

Criar `tests/gpu/test_liberadores.py`:

```python
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
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/gpu/test_liberadores.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'forge.gpu.liberadores'`

- [ ] **Step 3: Adicionar os campos de config**

Em `src/forge/infrastructure/config.py`, junto dos demais:

```python
    comfy_url: str = "http://127.0.0.1:8188"
    # VRAM que precisa estar livre para o ComfyUI aceitar a próxima geração.
    # 6 GB numa placa de 8 GB: o SDXL não entra abaixo disso.
    comfy_vram_livre_min: int = 6_000_000_000
    lms_bin: str = str(Path.home() / ".lmstudio" / "bin" / "lms.exe")
    gpu_liberacao_timeout: float = 60.0
```

`Path` já vem importado no topo do arquivo.

Acrescentar a `tests/test_config.py`:

```python
def test_liberadores_tem_defaults():
    from forge.infrastructure.config import Settings

    s = Settings(_env_file=None)
    assert s.comfy_url == "http://127.0.0.1:8188"
    assert s.comfy_vram_livre_min == 6_000_000_000
    assert s.gpu_liberacao_timeout == 60.0
    assert s.lms_bin.endswith("lms.exe")
```

- [ ] **Step 4: Implementar os liberadores**

Criar `src/forge/gpu/liberadores.py`:

```python
"""Como cada recurso devolve a VRAM, e como isso é confirmado.

Dois modos de falha, tratados de forma diferente de propósito:

- serviço no ar que não confirma a liberação -> LiberacaoFalhou. Seguir em
  frente aqui é gerar imagem numa placa cheia, que é o crash que este desenho
  existe para evitar.
- serviço fora do ar ou binário ausente -> aviso e segue. Não há o que liberar
  num serviço que não está rodando.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Callable

import httpx

from forge.gpu.broker import Broker, LiberacaoFalhou
from forge.infrastructure.config import Settings
from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)

INTERVALO_POLL = 0.5


def _base_lm_studio(settings: Settings) -> str:
    """`http://host/v1` -> `http://host`. A API de estado não fica sob /v1."""
    return settings.lm_studio_base_url.rstrip("/").removesuffix("/v1")


def liberar_llm(
    settings: Settings,
    *,
    executar: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    cliente: httpx.Client | None = None,
) -> None:
    try:
        proc = executar(
            [settings.lms_bin, "unload", "--all"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except (FileNotFoundError, OSError) as e:
        logger.warning("lms indisponível; nada a descarregar", error=str(e))
        return
    if proc.returncode != 0:
        logger.warning("lms unload falhou", returncode=proc.returncode)

    fechar = cliente is None
    cliente = cliente or httpx.Client(base_url=_base_lm_studio(settings), timeout=10.0)
    try:
        _esperar(
            settings,
            "llm",
            lambda: _nenhum_carregado(cliente),
        )
    finally:
        if fechar:
            cliente.close()


def _nenhum_carregado(cliente: httpx.Client) -> bool | None:
    """True liberado, False ainda carregado, None serviço fora do ar."""
    try:
        resp = cliente.get("/api/v0/models")
        resp.raise_for_status()
        modelos = resp.json().get("data", [])
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("LM Studio não respondeu; seguindo", error=str(e))
        return None
    return all(m.get("state") != "loaded" for m in modelos)


def liberar_imagem(settings: Settings, *, cliente: httpx.Client | None = None) -> None:
    fechar = cliente is None
    cliente = cliente or httpx.Client(base_url=settings.comfy_url, timeout=10.0)
    try:
        try:
            resp = cliente.post(
                "/free", json={"unload_models": True, "free_memory": True}
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("ComfyUI não respondeu ao /free; seguindo", error=str(e))
            return
        _esperar(settings, "imagem", lambda: _vram_livre(cliente, settings))
    finally:
        if fechar:
            cliente.close()


def _vram_livre(cliente: httpx.Client, settings: Settings) -> bool | None:
    try:
        resp = cliente.get("/system_stats")
        resp.raise_for_status()
        devices = resp.json().get("devices", [])
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("ComfyUI não respondeu ao /system_stats", error=str(e))
        return None
    if not devices:
        return None
    livre = max(int(d.get("vram_free", 0)) for d in devices)
    logger.debug("VRAM livre", livre=livre, minimo=settings.comfy_vram_livre_min)
    return livre >= settings.comfy_vram_livre_min


def liberar_tts(settings: Settings) -> None:
    """O audiocpp_cli é um processo por trecho: sai e devolve a VRAM sozinho."""
    return None


def _esperar(settings: Settings, recurso: str, checar: Callable[[], bool | None]) -> None:
    limite = time.monotonic() + settings.gpu_liberacao_timeout
    while True:
        resultado = checar()
        if resultado is None:  # serviço fora do ar: não há o que confirmar
            return
        if resultado:
            logger.info("GPU liberada", recurso=recurso)
            return
        if time.monotonic() >= limite:
            raise LiberacaoFalhou(
                f"{recurso} não liberou a VRAM em {settings.gpu_liberacao_timeout}s"
            )
        time.sleep(INTERVALO_POLL)


def montar_liberadores(settings: Settings) -> dict[str, Callable[[], None]]:
    return {
        "llm": lambda: liberar_llm(settings),
        "imagem": lambda: liberar_imagem(settings),
        "tts": lambda: liberar_tts(settings),
    }


def montar_broker(settings: Settings, *, base: Path = Path("output")) -> Broker:
    """O broker real, montado a partir de Settings — contraparte do injetado."""
    sem_gpu = frozenset({"tts"}) if settings.tts_backend == "cpu" else frozenset()
    return Broker(
        lock_path=base / ".gpu.lock",
        estado_path=base / ".gpu-residente.json",
        liberadores=montar_liberadores(settings),
        timeout_lock=settings.gpu_lock_timeout,
        sem_gpu=sem_gpu,
    )
```

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest tests/gpu/ -v`
Expected: PASS

Se `test_liberar_llm_estoura_se_o_modelo_continuar_carregado` demorar, conferir que `gpu_liberacao_timeout=0.5` está chegando ao `_esperar` — o teste não pode levar 60 s.

- [ ] **Step 6: Rodar a suíte**

Run: `uv run pytest`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: add real GPU releasers for LM Studio and ComfyUI

Each releaser verifies the memory actually came back: `lms unload --all` is
confirmed against /api/v0/models, and ComfyUI's /free against /system_stats.
A service that is up but will not release raises; a service that is not
running only warns, since there is nothing to unload.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Catálogo de tags de controle

O TTS aceita 43 tags. Uma tag inválida só é descoberta depois de minutos de síntese, então a validação precisa acontecer antes de qualquer GPU — no plano de mídia, que é a Task 4.

**Files:**
- Create: `src/forge/narracao/__init__.py`, `src/forge/narracao/tags.py`
- Create: `tests/narracao/__init__.py`, `tests/narracao/test_tags.py`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `TAGS_SENTENCA: dict[str, frozenset[str]]`, `TAGS_INLINE: dict[str, frozenset[str]]`
  - `class TagInvalida(ValueError)`
  - `validar_texto(texto: str) -> None`
  - `sanear_texto(texto: str) -> tuple[str, list[str]]` — devolve o texto sem as tags inválidas e a lista do que foi removido

- [ ] **Step 1: Escrever os testes**

Criar `tests/narracao/__init__.py` vazio e `tests/narracao/test_tags.py`:

```python
import pytest

from forge.narracao.tags import (
    TAGS_INLINE,
    TAGS_SENTENCA,
    TagInvalida,
    sanear_texto,
    validar_texto,
)


def test_catalogo_tem_as_43_tags():
    total = sum(len(v) for v in TAGS_SENTENCA.values())
    total += sum(len(v) for v in TAGS_INLINE.values())
    assert total == 43


def test_texto_valido_passa():
    validar_texto("<|emotion:contemplation|><|prosody:speed_slow|>Olá.<|prosody:long_pause|>")


def test_texto_sem_tag_passa():
    validar_texto("Uma frase comum, sem nenhuma tag.")


def test_categoria_desconhecida_estoura():
    with pytest.raises(TagInvalida) as exc:
        validar_texto("<|mood:happy|>Olá.")
    assert "mood" in str(exc.value)


def test_nome_desconhecido_estoura_com_sugestao():
    with pytest.raises(TagInvalida) as exc:
        validar_texto("<|emotion:contemplacion|>Olá.")
    assert "contemplation" in str(exc.value)


def test_sanear_remove_a_tag_invalida_e_preserva_a_valida():
    texto, removidas = sanear_texto("<|emotion:contemplation|><|mood:happy|>Olá.")

    assert texto == "<|emotion:contemplation|>Olá."
    assert removidas == ["<|mood:happy|>"]
    validar_texto(texto)


def test_sanear_texto_limpo_nao_muda_nada():
    texto, removidas = sanear_texto("<|emotion:awe|>Olá.")

    assert removidas == []
    assert texto == "<|emotion:awe|>Olá."
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/narracao/test_tags.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'forge.narracao'`

- [ ] **Step 3: Implementar o catálogo**

Criar `src/forge/narracao/__init__.py` vazio e `src/forge/narracao/tags.py`:

```python
"""As 43 tags de controle do higgs-tts-3-4b.

Espelho de `C:\\dev\\audio-generate\\src\\audio_generate\\tags.py`. É cópia, não
import: aquele pacote expõe `synthesize` no `__init__`, então importar qualquer
coisa dele arrasta torch e transformers — que o caminho GPU (subprocess para o
audiocpp_cli) não usa. O catálogo é dado, não lógica; ao mudar lá, mudar aqui.

Sintaxe do modelo: `<|categoria:nome|>`. Emoção, estilo e prosódia de frase vão
no começo da sentença; pausa e efeito sonoro são inline.
"""

from __future__ import annotations

import difflib
import re

TAG_RE = re.compile(r"<\|([a-z_]+):([a-z_]+)\|>")

TAGS_SENTENCA: dict[str, frozenset[str]] = {
    "emotion": frozenset({
        "elation", "amusement", "enthusiasm", "determination", "pride",
        "contentment", "affection", "relief", "contemplation", "confusion",
        "surprise", "awe", "longing", "arousal", "anger", "fear", "disgust",
        "bitterness", "sadness", "shame", "helplessness",
    }),
    "style": frozenset({"singing", "shouting", "whispering"}),
    "prosody": frozenset({
        "speed_very_slow", "speed_slow", "speed_fast", "speed_very_fast",
        "pitch_low", "pitch_high", "expressive_high", "expressive_low",
    }),
}

TAGS_INLINE: dict[str, frozenset[str]] = {
    "prosody": frozenset({"pause", "long_pause"}),
    "sfx": frozenset({
        "cough", "laughter", "crying", "screaming", "burping", "humming",
        "sigh", "sniff", "sneeze",
    }),
}


class TagInvalida(ValueError):
    """Tag fora do catálogo. Descobrir isso na GPU custaria minutos por trecho."""


def _nomes(categoria: str) -> frozenset[str]:
    return TAGS_SENTENCA.get(categoria, frozenset()) | TAGS_INLINE.get(
        categoria, frozenset()
    )


def _categorias() -> set[str]:
    return set(TAGS_SENTENCA) | set(TAGS_INLINE)


def validar_texto(texto: str) -> None:
    for categoria, nome in TAG_RE.findall(texto):
        if categoria not in _categorias():
            raise TagInvalida(
                f"categoria de tag desconhecida: {categoria!r}. "
                f"Conhecidas: {sorted(_categorias())}"
            )
        validos = _nomes(categoria)
        if nome not in validos:
            perto = difflib.get_close_matches(nome, sorted(validos), n=1)
            sugestao = f" Você quis dizer {perto[0]!r}?" if perto else ""
            raise TagInvalida(
                f"tag desconhecida: <|{categoria}:{nome}|>.{sugestao}"
            )


def sanear_texto(texto: str) -> tuple[str, list[str]]:
    """Remove as tags fora do catálogo e devolve quais foram removidas.

    Preferido a levantar num pipeline autônomo: uma tag inventada pelo modelo
    não deve derrubar o vídeo inteiro, e o texto sem ela ainda é narrável.
    """
    removidas: list[str] = []

    def _troca(m: re.Match) -> str:
        categoria, nome = m.group(1), m.group(2)
        if categoria in _categorias() and nome in _nomes(categoria):
            return m.group(0)
        removidas.append(m.group(0))
        return ""

    return TAG_RE.sub(_troca, texto), removidas
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/narracao/test_tags.py -v`
Expected: PASS, 7 testes

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add the higgs TTS control tag catalogue

43 tags, mirrored from audio-generate rather than imported: that package's
__init__ pulls torch and transformers, which the GPU path (a subprocess call to
audiocpp_cli) never uses. sanear_texto strips unknown tags instead of raising,
so a tag the model invented costs a warning rather than the whole video.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Plano de mídia

**Files:**
- Create: `src/forge/domain/midia.py`
- Create: `src/forge/agents/midia.py`
- Create: `src/forge/prompts/midia.md`
- Create: `tests/agents/test_midia.py`
- Modify: `src/forge/cli.py` (`_cmd_roteiro`, ao fim)
- Modify: `src/forge/infrastructure/config.py` (`midia_alvo_segundos`)
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `Roteiro` (`domain/models.py`), `sanear_texto` (Task 3).
- Produces:
  - `class BlocoNarracao(BaseModel)` com `id: str`, `secao: str`, `texto: str`
  - `class Beat(BaseModel)` com `id: str`, `bloco_id: str`, `prompt: str`
  - `class PlanoMidia(BaseModel)` com `blocos: list[BlocoNarracao]`, `beats: list[Beat]`
  - `planejar_midia(model, roteiro: Roteiro, *, alvo_segundos: int = 15) -> PlanoMidia`
  - `gravar_plano(run_dir: Path, plano: PlanoMidia) -> Path` — grava `<run_dir>/video/midia.json`
  - `carregar_plano(run_dir: Path) -> PlanoMidia`
  - `LE = ["tema", "roteiro"]`

- [ ] **Step 1: Escrever os testes**

Criar `tests/agents/test_midia.py`:

```python
from forge.agents.midia import carregar_plano, gravar_plano, planejar_midia
from forge.domain.midia import Beat, BlocoNarracao, PlanoMidia
from forge.domain.models import Roteiro, Secao


def _roteiro():
    return Roteiro(
        tema="livre-arbítrio",
        tese="a vontade é sentida, não observada",
        secoes=[Secao(nome="Hook", conteudo="c1"), Secao(nome="Problema", conteudo="c2")],
    )


def _plano_cru():
    """O que o modelo devolve: ids arbitrários, uma tag inventada."""
    return PlanoMidia(
        blocos=[
            BlocoNarracao(id="qualquer", secao="Hook",
                          texto="<|emotion:contemplation|>Primeira frase."),
            BlocoNarracao(id="outro", secao="Problema",
                          texto="<|mood:pensativo|>Segunda frase."),
        ],
        beats=[
            Beat(id="x", bloco_id="qualquer", prompt="uma ampulheta"),
            Beat(id="y", bloco_id="outro", prompt="uma estrada bifurcada"),
        ],
    )


def test_ids_sao_renumerados_deterministicamente(scripted):
    model = scripted(structured=[_plano_cru()])

    plano = planejar_midia(model, _roteiro())

    assert [b.id for b in plano.blocos] == ["b001", "b002"]
    assert [i.id for i in plano.beats] == ["i001", "i002"]
    assert [i.bloco_id for i in plano.beats] == ["b001", "b002"]


def test_tag_inventada_e_removida_em_vez_de_derrubar(scripted):
    model = scripted(structured=[_plano_cru()])

    plano = planejar_midia(model, _roteiro())

    assert plano.blocos[1].texto == "Segunda frase."
    assert plano.blocos[0].texto.startswith("<|emotion:contemplation|>")


def test_beat_orfao_e_descartado(scripted):
    cru = _plano_cru()
    cru.beats.append(Beat(id="z", bloco_id="nao-existe", prompt="perdido"))
    model = scripted(structured=[cru])

    plano = planejar_midia(model, _roteiro())

    assert len(plano.beats) == 2


def test_plano_faz_round_trip_no_disco(tmp_path, scripted):
    plano = planejar_midia(scripted(structured=[_plano_cru()]), _roteiro())

    caminho = gravar_plano(tmp_path, plano)

    assert caminho == tmp_path / "video" / "midia.json"
    assert carregar_plano(tmp_path) == plano
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/agents/test_midia.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'forge.domain.midia'`

- [ ] **Step 3: Criar os modelos**

Criar `src/forge/domain/midia.py`:

```python
"""O plano de mídia: a ponte entre o roteiro aprovado e a execução do vídeo.

É o último artefato que exige LLM. Depois dele, narração e imagem são pura
execução — nenhuma chamada de modelo acontece na fase de GPU.
"""

from pydantic import BaseModel, Field


class BlocoNarracao(BaseModel):
    """Um trecho de 1 a 3 frases, com as tags de controle do TTS."""

    id: str
    secao: str
    texto: str


class Beat(BaseModel):
    """Uma imagem e o ponto da narração em que ela entra."""

    id: str
    bloco_id: str
    prompt: str


class PlanoMidia(BaseModel):
    blocos: list[BlocoNarracao] = Field(default_factory=list)
    beats: list[Beat] = Field(default_factory=list)
```

- [ ] **Step 4: Escrever o prompt**

Criar `src/forge/prompts/midia.md`:

```markdown
Você vai preparar a produção de um vídeo a partir do roteiro abaixo.

Tema: {tema}
Tese: {tese}

Roteiro:

{roteiro}

Duas listas.

**Blocos de narração.** Fatie o roteiro inteiro, na ordem, em trechos de 1 a 3
frases. Nenhuma palavra do roteiro pode ser perdida ou reescrita — você está
cortando, não editando. Cada bloco registra de qual seção veio.

Cada bloco pode começar com tags de controle de voz, e usar pausas no meio.
Use-as com parcimônia: só onde a leitura muda de verdade.

- emoção: `<|emotion:contemplation|>`, `<|emotion:awe|>`, `<|emotion:bitterness|>`,
  `<|emotion:determination|>`, `<|emotion:sadness|>`, `<|emotion:surprise|>`
- ritmo: `<|prosody:speed_slow|>`, `<|prosody:speed_fast|>`,
  `<|prosody:pitch_low|>`, `<|prosody:expressive_high|>`
- pausa, no meio do texto: `<|prosody:pause|>`, `<|prosody:long_pause|>`

Não invente tag fora dessa lista.

**Beats visuais.** Uma imagem a cada {alvo_segundos} segundos de narração
aproximadamente — conte cerca de 15 palavras por 5 segundos. Cada beat aponta o
bloco em que a imagem entra e traz o prompt de geração, em inglês, concreto e
visual: cena, luz, composição, atmosfera. Nada de texto na imagem, nada de
rosto de pessoa real, nada abstrato demais para desenhar.

Os ids que você escrever são ignorados e renumerados — não gaste esforço neles,
mas mantenha `bloco_id` apontando para um bloco que existe na sua lista.
```

- [ ] **Step 5: Implementar o agente**

Criar `src/forge/agents/midia.py`:

```python
"""Deriva o plano de mídia do roteiro aprovado.

Roda com o LLM ainda residente, no fim do `forge roteiro`, para que a fase de
GPU não precise recarregar o modelo só para pedir prompts de imagem.
"""

from __future__ import annotations

import json
from pathlib import Path

from langchain_core.messages import HumanMessage

from forge.domain.midia import Beat, BlocoNarracao, PlanoMidia
from forge.domain.models import Roteiro
from forge.infrastructure.logging import get_logger
from forge.narracao.tags import sanear_texto
from forge.prompts.loader import load_prompt

logger = get_logger(__name__)

LE = ["tema", "roteiro"]


def planejar_midia(model, roteiro: Roteiro, *, alvo_segundos: int = 15) -> PlanoMidia:
    prompt = load_prompt("midia").format(
        tema=roteiro.tema,
        tese=roteiro.tese,
        roteiro=_fmt_roteiro(roteiro),
        alvo_segundos=alvo_segundos,
    )
    cru = model.with_structured_output(PlanoMidia).invoke([HumanMessage(content=prompt)])
    plano = _normalizar(cru)
    logger.info("Plano de mídia pronto", blocos=len(plano.blocos), beats=len(plano.beats))
    return plano


def _fmt_roteiro(roteiro: Roteiro) -> str:
    return "\n\n".join(f"## {s.nome}\n\n{s.conteudo}" for s in roteiro.secoes)


def _normalizar(cru: PlanoMidia) -> PlanoMidia:
    """Renumera os ids e limpa o que o modelo errou.

    Ids vêm de nós, não do modelo: são a chave que o manifesto e os arquivos de
    saída usam, e um id repetido pelo modelo sobrescreveria um item já gerado.
    """
    mapa: dict[str, str] = {}
    blocos: list[BlocoNarracao] = []
    for i, bloco in enumerate(cru.blocos, 1):
        novo = f"b{i:03d}"
        mapa[bloco.id] = novo
        texto, removidas = sanear_texto(bloco.texto)
        if removidas:
            logger.warning("Tags inválidas removidas", bloco=novo, tags=removidas)
        blocos.append(BlocoNarracao(id=novo, secao=bloco.secao, texto=texto.strip()))

    beats: list[Beat] = []
    for beat in cru.beats:
        alvo = mapa.get(beat.bloco_id)
        if alvo is None:
            # Beat apontando para bloco inexistente não tem quando entrar em
            # tela; descartar é melhor que ancorá-lo em algum bloco arbitrário.
            logger.warning("Beat órfão descartado", bloco_id=beat.bloco_id)
            continue
        beats.append(Beat(id=f"i{len(beats) + 1:03d}", bloco_id=alvo, prompt=beat.prompt))

    return PlanoMidia(blocos=blocos, beats=beats)


def caminho_plano(run_dir: Path) -> Path:
    return Path(run_dir) / "video" / "midia.json"


def gravar_plano(run_dir: Path, plano: PlanoMidia) -> Path:
    caminho = caminho_plano(run_dir)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps(plano.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return caminho


def carregar_plano(run_dir: Path) -> PlanoMidia:
    return PlanoMidia(**json.loads(caminho_plano(run_dir).read_text(encoding="utf-8")))
```

- [ ] **Step 6: Rodar e ver passar**

Run: `uv run pytest tests/agents/test_midia.py -v`
Expected: PASS, 4 testes

- [ ] **Step 7: Ligar ao `forge roteiro`**

Em `src/forge/infrastructure/config.py`:

```python
    midia_alvo_segundos: int = 15
```

Em `src/forge/cli.py`, dentro de `_cmd_roteiro`, depois de `gravar_roteiro(...)` e antes do `print(str(path))`:

```python
    # O plano de mídia sai junto do roteiro porque é a última coisa que exige
    # LLM: emiti-lo aqui evita recarregar o modelo na fase de GPU.
    from forge.agents.midia import gravar_plano, planejar_midia

    try:
        plano = planejar_midia(
            model, final["roteiro"], alvo_segundos=settings.midia_alvo_segundos
        )
        caminho_midia = gravar_plano(run_dir, plano)
        logger.info("Plano de mídia gravado", path=str(caminho_midia),
                    blocos=len(plano.blocos), beats=len(plano.beats))
    except Exception as e:
        # Roteiro aprovado é o entregável desta etapa; falhar o plano de mídia
        # não pode apagá-lo. `forge video` refaz o plano depois.
        logger.error("Plano de mídia falhou", error=str(e), exc_info=True)
```

- [ ] **Step 8: Testar a integração no CLI**

Acrescentar a `tests/test_cli.py`, seguindo o padrão de `test_main_roteiro` (que já monkeypatcha `get_settings`, `build_chat_model` e `build_graph`):

```python
def test_roteiro_grava_o_plano_de_midia(monkeypatch, tmp_path, capsys):
    from forge.agents import midia as midia_mod
    from forge.domain.midia import Beat, BlocoNarracao, PlanoMidia

    settings = Settings(_env_file=None, output_dir=tmp_path / "roteiros",
                        anthropic_api_key="sk-test")
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "build_chat_model", lambda s: object())

    roteiro = Roteiro(tema="tema", tese="tese",
                      secoes=[Secao(nome="Hook", conteudo="c")])

    class FakeGraph:
        def stream(self, state):
            yield {"write": {"roteiro": roteiro}}

    monkeypatch.setattr(cli, "build_graph", lambda model, s, inicio="tema": FakeGraph())

    plano = PlanoMidia(
        blocos=[BlocoNarracao(id="b001", secao="Hook", texto="c")],
        beats=[Beat(id="i001", bloco_id="b001", prompt="uma ampulheta")],
    )
    monkeypatch.setattr(midia_mod, "planejar_midia", lambda *a, **k: plano)

    rc = cli.main(["roteiro", "--tema", "meu tema"])

    assert rc == 0
    # criar_run_dir monta `settings.output_dir.parent / "runs" / <ts>-<slug>`
    # (services/artefatos.py:17), por isso output_dir aponta para um subdiretório
    # de tmp_path: as runs caem em tmp_path/runs e nada escapa do tmp.
    runs = list((tmp_path / "runs").iterdir())
    assert len(runs) == 1
    assert carregar_plano(runs[0]) == plano
```

O `settings` deste teste precisa de `output_dir=tmp_path / "roteiros"` (não `tmp_path`), pela razão do comentário. Importar `carregar_plano` de `forge.agents.midia` no topo do teste.

- [ ] **Step 9: Rodar a suíte**

Run: `uv run pytest`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat: derive a media plan from the approved script

Narration blocks with validated TTS control tags, plus one image prompt per
visual beat. Ids are assigned by us, not by the model: they key the manifest
and the output files, and a repeated id would overwrite an item already
generated. Invented tags are stripped with a warning rather than raising —
in an autonomous loop a bad tag must not cost the whole video.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Manifesto

**Files:**
- Create: `src/forge/services/manifesto.py`
- Create: `tests/services/test_manifesto.py`

**Interfaces:**
- Consumes: `PlanoMidia`, `BlocoNarracao`, `Beat` (Task 4).
- Produces:
  - `class Item(BaseModel)` com `id: str`, `tipo: Literal["audio", "imagem"]`, `estado: Literal["pendente", "ok", "falhou"]`, `entrada: dict`, `saida: str`, `duracao_ms: int | None`, `tentativas: int`, `erro: str`
  - `class Manifesto(BaseModel)` com `itens: list[Item]`
  - `caminho(run_dir: Path) -> Path`
  - `criar_ou_carregar(run_dir: Path, plano: PlanoMidia) -> Manifesto`
  - `carregar(run_dir: Path) -> Manifesto`
  - `gravar(run_dir: Path, manifesto: Manifesto) -> None`
  - `pendentes(manifesto: Manifesto, tipo: str | None = None) -> list[Item]`

- [ ] **Step 1: Escrever os testes**

Criar `tests/services/test_manifesto.py`:

```python
import json

from forge.domain.midia import Beat, BlocoNarracao, PlanoMidia
from forge.services.manifesto import (
    caminho,
    carregar,
    criar_ou_carregar,
    gravar,
    pendentes,
)


def _plano():
    return PlanoMidia(
        blocos=[
            BlocoNarracao(id="b001", secao="Hook", texto="Primeira."),
            BlocoNarracao(id="b002", secao="Hook", texto="Segunda."),
        ],
        beats=[Beat(id="i001", bloco_id="b001", prompt="uma ampulheta")],
    )


def test_criar_gera_um_item_por_bloco_e_por_beat(tmp_path):
    m = criar_ou_carregar(tmp_path, _plano())

    assert [i.id for i in m.itens] == ["b001", "b002", "i001"]
    assert [i.tipo for i in m.itens] == ["audio", "audio", "imagem"]
    assert all(i.estado == "pendente" for i in m.itens)


def test_criar_preserva_o_progresso_de_um_manifesto_existente(tmp_path):
    """Retomar não pode zerar o que já foi gerado."""
    m = criar_ou_carregar(tmp_path, _plano())
    m.itens[0].estado = "ok"
    m.itens[0].saida = "video/audio/b001.wav"
    gravar(tmp_path, m)

    de_novo = criar_ou_carregar(tmp_path, _plano())

    assert de_novo.itens[0].estado == "ok"
    assert de_novo.itens[0].saida == "video/audio/b001.wav"


def test_pendentes_filtra_por_tipo(tmp_path):
    m = criar_ou_carregar(tmp_path, _plano())
    m.itens[0].estado = "ok"

    assert [i.id for i in pendentes(m, "audio")] == ["b002"]
    assert [i.id for i in pendentes(m, "imagem")] == ["i001"]
    assert [i.id for i in pendentes(m)] == ["b002", "i001"]


def test_gravar_e_atomico(tmp_path):
    """O manifesto é reescrito depois de cada item; um corte no meio da escrita
    não pode deixar um JSON truncado no lugar do progresso."""
    m = criar_ou_carregar(tmp_path, _plano())
    gravar(tmp_path, m)

    assert not list(caminho(tmp_path).parent.glob("*.tmp"))
    json.loads(caminho(tmp_path).read_text(encoding="utf-8"))
    assert carregar(tmp_path) == m
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/services/test_manifesto.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'forge.services.manifesto'`

- [ ] **Step 3: Implementar**

Criar `src/forge/services/manifesto.py`:

```python
"""Estado por item da fase de vídeo.

40 imagens numa RX 580 são horas. O manifesto existe para que um crash na
imagem 33 custe uma imagem, não a noite inteira: cada item carrega o próprio
estado e o arquivo é regravado depois de cada um.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from forge.domain.midia import PlanoMidia
from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)

Tipo = Literal["audio", "imagem"]
Estado = Literal["pendente", "ok", "falhou"]


class Item(BaseModel):
    id: str
    tipo: Tipo
    estado: Estado = "pendente"
    entrada: dict = Field(default_factory=dict)
    saida: str = ""
    duracao_ms: int | None = None
    tentativas: int = 0
    erro: str = ""


class Manifesto(BaseModel):
    itens: list[Item] = Field(default_factory=list)


def caminho(run_dir: Path) -> Path:
    return Path(run_dir) / "video" / "manifesto.json"


def _do_plano(plano: PlanoMidia) -> Manifesto:
    itens = [
        Item(id=b.id, tipo="audio", entrada={"texto": b.texto, "secao": b.secao})
        for b in plano.blocos
    ]
    itens += [
        Item(id=i.id, tipo="imagem", entrada={"prompt": i.prompt, "bloco_id": i.bloco_id})
        for i in plano.beats
    ]
    return Manifesto(itens=itens)


def criar_ou_carregar(run_dir: Path, plano: PlanoMidia) -> Manifesto:
    """Monta o manifesto do plano, preservando o que um run anterior já fez.

    O id vem do plano e é estável, então o estado antigo reata com o item novo
    sem ambiguidade.
    """
    novo = _do_plano(plano)
    if not caminho(run_dir).exists():
        return novo

    antigo = {i.id: i for i in carregar(run_dir).itens}
    itens = [antigo.get(i.id, i) for i in novo.itens]
    logger.info(
        "Manifesto retomado",
        total=len(itens),
        pendentes=sum(1 for i in itens if i.estado == "pendente"),
    )
    return Manifesto(itens=itens)


def carregar(run_dir: Path) -> Manifesto:
    return Manifesto(**json.loads(caminho(run_dir).read_text(encoding="utf-8")))


def gravar(run_dir: Path, manifesto: Manifesto) -> None:
    destino = caminho(run_dir)
    destino.parent.mkdir(parents=True, exist_ok=True)
    # Escrita atômica: um corte de energia no meio da gravação deixaria um JSON
    # truncado no lugar do progresso de horas.
    temporario = destino.with_suffix(".json.tmp")
    temporario.write_text(
        json.dumps(manifesto.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporario, destino)


def pendentes(manifesto: Manifesto, tipo: str | None = None) -> list[Item]:
    return [
        i for i in manifesto.itens
        if i.estado == "pendente" and (tipo is None or i.tipo == tipo)
    ]
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/services/test_manifesto.py -v`
Expected: PASS, 4 testes

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add the per-item video manifest

Each narration block and image beat becomes an item with its own state,
rewritten atomically after every item. Ids come from the media plan and are
stable, so resuming reattaches old state to new items unambiguously.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Runner

**Files:**
- Create: `src/forge/services/runner.py`
- Create: `tests/services/test_runner.py`

**Interfaces:**
- Consumes: `Manifesto`, `Item`, `pendentes`, `gravar` (Task 5); `Broker` (Task 1).
- Produces:
  - `Executor = Callable[[Item, Path], None]` — recebe o item e o run dir e preenche `saida` e `duracao_ms` **no próprio item**, por mutação. O runner não lê retorno: o item já está dentro do manifesto que vai ser gravado, então devolver uma cópia só criaria duas verdades.
  - `RECURSO_DE: dict[str, str]` — `{"audio": "tts", "imagem": "imagem"}`
  - `executar(run_dir: Path, manifesto: Manifesto, executores: dict[str, Executor], broker, *, so: str | None = None) -> Manifesto`

- [ ] **Step 1: Escrever os testes**

Criar `tests/services/test_runner.py`:

```python
from contextlib import contextmanager

from forge.domain.midia import Beat, BlocoNarracao, PlanoMidia
from forge.services.manifesto import carregar, criar_ou_carregar
from forge.services.runner import executar


class BrokerFalso:
    def __init__(self):
        self.slots = []

    @contextmanager
    def exclusivo(self, recurso):
        self.slots.append(recurso)
        yield


def _plano():
    return PlanoMidia(
        blocos=[
            BlocoNarracao(id="b001", secao="Hook", texto="Primeira."),
            BlocoNarracao(id="b002", secao="Hook", texto="Segunda."),
        ],
        beats=[Beat(id="i001", bloco_id="b001", prompt="uma ampulheta")],
    )


def _ok(item, run_dir):
    """Executor falso: preenche o item por mutação, como o contrato pede."""
    item.saida = f"video/{item.tipo}/{item.id}"
    item.duracao_ms = 1000


def test_executa_todos_os_pendentes(tmp_path):
    m = criar_ou_carregar(tmp_path, _plano())

    final = executar(tmp_path, m, {"audio": _ok, "imagem": _ok}, BrokerFalso())

    assert [i.estado for i in final.itens] == ["ok", "ok", "ok"]
    assert carregar(tmp_path) == final


def test_toma_o_slot_uma_vez_por_grupo(tmp_path):
    """Trocar de recurso por item pagaria um reload de modelo por item."""
    m = criar_ou_carregar(tmp_path, _plano())
    broker = BrokerFalso()

    executar(tmp_path, m, {"audio": _ok, "imagem": _ok}, broker)

    assert broker.slots == ["tts", "imagem"]


def test_item_que_estoura_nao_derruba_os_seguintes(tmp_path):
    m = criar_ou_carregar(tmp_path, _plano())

    def audio(item, run_dir):
        if item.id == "b001":
            raise RuntimeError("audiocpp morreu")
        _ok(item, run_dir)

    final = executar(tmp_path, m, {"audio": audio, "imagem": _ok}, BrokerFalso())

    por_id = {i.id: i for i in final.itens}
    assert por_id["b001"].estado == "falhou"
    assert "audiocpp morreu" in por_id["b001"].erro
    assert por_id["b001"].tentativas == 1
    assert por_id["b002"].estado == "ok"
    assert por_id["i001"].estado == "ok"


def test_retomada_so_roda_os_pendentes(tmp_path):
    m = criar_ou_carregar(tmp_path, _plano())
    m.itens[0].estado = "ok"
    vistos = []

    def audio(item, run_dir):
        vistos.append(item.id)
        _ok(item, run_dir)

    executar(tmp_path, m, {"audio": audio, "imagem": _ok}, BrokerFalso())

    assert vistos == ["b002"]


def test_so_um_grupo(tmp_path):
    m = criar_ou_carregar(tmp_path, _plano())
    broker = BrokerFalso()

    final = executar(tmp_path, m, {"audio": _ok, "imagem": _ok}, broker, so="audio")

    por_id = {i.id: i for i in final.itens}
    assert por_id["i001"].estado == "pendente"
    assert broker.slots == ["tts"]


def test_grupo_sem_pendente_nao_toma_o_slot(tmp_path):
    m = criar_ou_carregar(tmp_path, _plano())
    for item in m.itens:
        if item.tipo == "audio":
            item.estado = "ok"
    broker = BrokerFalso()

    executar(tmp_path, m, {"audio": _ok, "imagem": _ok}, broker)

    assert broker.slots == ["imagem"]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/services/test_runner.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'forge.services.runner'`

- [ ] **Step 3: Implementar**

Criar `src/forge/services/runner.py`:

```python
"""Consome os pendentes do manifesto, um grupo de cada vez.

Agrupar por tipo é o que torna o slot de GPU barato: o recurso é tomado uma vez
por grupo, não uma vez por item. Dentro do grupo, cada item grava o manifesto ao
terminar, e um item que estoura não interrompe os seguintes — quem decide o que
fazer com a falha é quem lê o manifesto depois.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from forge.infrastructure.logging import get_logger
from forge.services.manifesto import Item, Manifesto, gravar, pendentes

logger = get_logger(__name__)

# O executor preenche `saida` e `duracao_ms` no próprio item, por mutação: o
# item já pertence ao manifesto que será gravado, e devolver uma cópia criaria
# duas verdades sobre o mesmo id.
Executor = Callable[[Item, Path], None]

# Ordem fixa: o áudio primeiro porque as durações que ele mede são o que
# cronometra as imagens na montagem.
ORDEM: tuple[str, ...] = ("audio", "imagem")
RECURSO_DE: dict[str, str] = {"audio": "tts", "imagem": "imagem"}


def executar(
    run_dir: Path,
    manifesto: Manifesto,
    executores: dict[str, Executor],
    broker,
    *,
    so: str | None = None,
) -> Manifesto:
    for tipo in ORDEM:
        if so is not None and tipo != so:
            continue
        fila = pendentes(manifesto, tipo)
        if not fila:
            logger.debug("Nada pendente", tipo=tipo)
            continue
        executor = executores.get(tipo)
        if executor is None:
            logger.warning("Sem executor para o tipo", tipo=tipo)
            continue

        logger.info("Iniciando grupo", tipo=tipo, pendentes=len(fila))
        with broker.exclusivo(RECURSO_DE[tipo]):
            for item in fila:
                _um(run_dir, manifesto, item, executor)
    return manifesto


def _um(run_dir: Path, manifesto: Manifesto, item: Item, executor: Executor) -> None:
    item.tentativas += 1
    try:
        executor(item, run_dir)
    except Exception as e:
        item.estado = "falhou"
        item.erro = str(e)
        logger.error("Item falhou", id=item.id, tipo=item.tipo, error=str(e))
    else:
        item.estado = "ok"
        item.erro = ""
        logger.info("Item pronto", id=item.id, tipo=item.tipo, saida=item.saida)
    # Gravar por item é o ponto do manifesto: um crash custa um item, não o run.
    gravar(run_dir, manifesto)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/services/test_runner.py -v`
Expected: PASS, 6 testes

- [ ] **Step 5: Rodar a suíte**

Run: `uv run pytest`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: add the manifest runner

Pending items are consumed one group at a time, so the GPU slot is taken once
per group instead of once per item. The manifest is rewritten after every item,
and a failing item marks itself and lets the rest of the group continue.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Prazo para as chamadas de LLM

O run real do Plano 1 travou duas vezes na síntese do LM Studio — 10 e 12 minutos sem retorno, sem erro. Num loop autônomo isso não é lentidão, é parada. Decisão D11 do adendo do spec.

**Files:**
- Modify: `src/forge/llms/model.py`
- Modify: `src/forge/infrastructure/config.py`
- Modify: `tests/test_llm_model.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: `Settings`.
- Produces: `Settings.llm_timeout: float`, `Settings.llm_max_retries: int`; modelos construídos com timeout e retentativa.

- [ ] **Step 1: Escrever os testes**

Acrescentar a `tests/test_config.py`:

```python
def test_llm_tem_prazo():
    from forge.infrastructure.config import Settings

    s = Settings(_env_file=None)
    assert s.llm_timeout == 600.0
    assert s.llm_max_retries == 1
```

Acrescentar a `tests/test_llm_model.py`, seguindo o padrão de construção de `Settings` que já existe no arquivo:

```python
def test_modelo_local_recebe_prazo():
    """Sem prazo, uma chamada que pendura trava o pipeline inteiro — foi o que
    aconteceu no primeiro run real, duas vezes."""
    from forge.infrastructure.config import Settings
    from forge.llms.model import build_chat_model

    s = Settings(_env_file=None, provider="lm-studio", llm_timeout=30.0)
    model = build_chat_model(s)

    assert model.request_timeout == 30.0
    assert model.max_retries == 1
```

Nota para quem implementa: confirmar o nome do atributo na versão instalada de `langchain_openai` — `ChatOpenAI` expõe `request_timeout` com alias `timeout`. Se o atributo diferir, ajustar a asserção para o nome real, sem afrouxar o teste para um `getattr(..., None)` que passaria mesmo sem o prazo configurado.

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_config.py::test_llm_tem_prazo tests/test_llm_model.py -v`
Expected: FAIL

- [ ] **Step 3: Implementar**

Em `src/forge/infrastructure/config.py`:

```python
    # Chamada de modelo sem prazo pendura o pipeline: no primeiro run real o
    # LM Studio ficou 12 min sem responder e sem erro.
    llm_timeout: float = 600.0
    llm_max_retries: int = 1
```

Em `src/forge/llms/model.py`:

```python
    if settings.provider == "lm-studio":
        return ChatOpenAI(
            model=modelo,
            base_url=settings.lm_studio_base_url,
            api_key=chave,
            timeout=settings.llm_timeout,
            max_retries=settings.llm_max_retries,
        )

    if settings.provider == "openai":
        return ChatOpenAI(
            model=modelo,
            api_key=chave,
            timeout=settings.llm_timeout,
            max_retries=settings.llm_max_retries,
        )

    return ChatAnthropic(
        model=modelo,
        api_key=chave,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={"effort": settings.effort},
        timeout=settings.llm_timeout,
        max_retries=settings.llm_max_retries,
    )
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/test_llm_model.py tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Rodar a suíte**

Run: `uv run pytest`
Expected: PASS

- [ ] **Step 6: Atualizar o `CLAUDE.md`**

Acrescentar, depois da seção `### Acervo`:

```markdown
### Vídeo: broker, plano de mídia e manifesto

`forge roteiro` grava, além do roteiro, `<run>/video/midia.json` — os blocos de
narração com tags de controle do TTS e um prompt de imagem por beat visual. É o
último artefato que exige LLM.

[gpu/broker.py](src/forge/gpu/broker.py) mantém **um** consumidor de GPU
residente por vez (`llm`, `tts`, `imagem`), com lock de arquivo em
`output/.gpu.lock`. A troca acontece por fase, nunca por item. Os liberadores
reais estão em [gpu/liberadores.py](src/forge/gpu/liberadores.py) e confirmam a
VRAM de volta antes de devolver o slot.

[services/manifesto.py](src/forge/services/manifesto.py) dá estado próprio a cada
bloco e cada beat; [services/runner.py](src/forge/services/runner.py) consome os
pendentes agrupados por tipo, tomando o slot uma vez por grupo e regravando o
manifesto depois de cada item. Os executores de áudio e imagem entram por
injeção.
```

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "fix: give every LLM call a deadline

The first real pipeline run hung twice on LM Studio synthesis — 10 and 12
minutes, no response, no error. In an autonomous loop that is not slowness, it
is a stop. Every provider now gets timeout and one retry from Settings.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Cobertura do spec

| Requisito do spec | Tarefa |
|---|---|
| S2 — slot exclusivo, um residente por vez, troca por fase | Task 1 |
| S2 — lock de arquivo, dois processos se respeitam | Task 1 |
| S2 — `FORGE_TTS_BACKEND=cpu` não disputa o slot | Task 1 |
| S2 — liberadores `lms unload --all` / `/free`, com confirmação | Task 2 |
| S2 — serviço fora do ar degrada com log, não com exceção | Task 2 |
| S3 — blocos de narração de 1-3 frases com tags | Task 4 |
| S3 — um prompt de imagem por beat, alvo ~15 s | Task 4 |
| S3 — tags validadas contra o catálogo antes de qualquer GPU | Tasks 3 e 4 |
| S3 — gravado em `<run>/video/midia.json` no fim do `forge roteiro` | Task 4 |
| S4 — item por bloco e por beat, com estado próprio | Task 5 |
| S4 — escrita atômica após cada item | Task 5 |
| S4 — retomada recalcula os pendentes | Tasks 5 e 6 |
| S4 — slot tomado uma vez por grupo | Task 6 |
| S4 — `--so audio` / `--so imagens` | Task 6 (parâmetro `so`; a flag de CLI entra com `forge video`, no plano seguinte) |
| D11 — prazo e retentativa em toda chamada de LLM | Task 7 |

Fora deste plano: S5 (narração), S6 (imagens), S7 (montagem), S8 (juiz de relevância e realimentação do acervo), S9 (canal autônomo). O comando `forge video` nasce no plano seguinte, junto dos executores reais que ele precisa ter para fazer alguma coisa.
