"""Cliente HTTP do `audiocpp_server`: um pedido por trecho de narração.

O servidor (ver `audiocpp_server.py`) mantém o Higgs carregado; aqui só se
monta o pedido, grava o WAV e classifica a falha. A classificação decide o que
o executor faz: falha de *trecho* troca de semente e pode ir para a CPU; falha
de *servidor* reinicia o processo; o resto falha o trecho na hora.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from forge.domain.execucao import FailureClass, FailureDetail
from forge.infrastructure.config import Settings

_EMOTION_TAG = re.compile(r"<\|emotion:[^|]*\|>")
_ITEM_KEY = re.compile(r"[A-Za-z0-9_-]+")
_MAX_STDERR_BYTES = 4 * 1024
MODELO_ID = "higgs"

SERVIDOR_INDISPONIVEL = "tts_servidor_indisponivel"
# Códigos que dizem respeito ao processo, não ao trecho: o executor reinicia o
# servidor e repete o mesmo trecho com a mesma semente.
FALHAS_DE_SERVIDOR = frozenset({"tts_vulkan_oom", SERVIDOR_INDISPONIVEL})


@dataclass(frozen=True, slots=True)
class AudioRequest:
    item_key: str
    text: str
    seed: int | None = None
    max_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class AudioOutcome:
    item_key: str
    path: Path | None = None
    failure: FailureDetail | None = None
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.path is not None and self.failure is None

    @classmethod
    def succeeded(cls, item_key: str, path: Path) -> "AudioOutcome":
        return cls(item_key=item_key, path=Path(path))

    @classmethod
    def failed(cls, item_key: str, code: str, message: str) -> "AudioOutcome":
        return cls(
            item_key=item_key,
            failure=FailureDetail(
                code=code,
                message=message,
                failure_class=FailureClass.PROCESS,
                retriable=True,
                recommended_action="Verificar o gerador de áudio e tentar novamente",
                adapter="audio_generate",
                attempt=1,
                item_key=item_key,
            ),
        )


def _tail(value: object) -> str:
    raw = str(value or "").encode("utf-8", errors="replace")
    return raw[-_MAX_STDERR_BYTES:].decode("utf-8", errors="replace")


def classify_audio_failure(
    message: str, *, status: int, item_key: str | None = None, attempt: int = 1
) -> FailureDetail:
    """Classifica a resposta de erro do servidor sem expor texto ilimitado."""
    message = _tail(message)
    if "reached max_tokens before EOC" in message:
        code, failure_class, retriable, action = (
            "tts_max_tokens_before_eoc", FailureClass.DETERMINISTIC, False,
            "Encurtar o bloco de narração antes de gerar novamente",
        )
    elif "ggml_vulkan: Device memory allocation" in message:
        code, failure_class, retriable, action = (
            "tts_vulkan_oom", FailureClass.CAPACITY, True,
            "Liberar VRAM ou reiniciar o servidor de áudio",
        )
    else:
        code, failure_class, retriable, action = (
            "tts_process_failed", FailureClass.PROCESS, False,
            "Verificar o gerador de áudio (modelo, referência de voz) e tentar novamente",
        )
    return FailureDetail(
        code=code,
        message=f"Geração de áudio falhou (status={status})",
        failure_class=failure_class,
        retriable=retriable,
        recommended_action=action,
        adapter="audio_generate",
        attempt=attempt,
        item_key=item_key,
        services={"status": status, "stderr_tail": message},
    )


def _indisponivel(item_key: str, error: Exception) -> AudioOutcome:
    detalhe = _tail(f"{type(error).__name__}: {error}")
    return AudioOutcome(
        item_key=item_key,
        stderr=detalhe,
        failure=FailureDetail(
            code=SERVIDOR_INDISPONIVEL,
            message="Servidor de áudio não respondeu",
            failure_class=FailureClass.TRANSIENT,
            retriable=True,
            recommended_action="Reiniciar o servidor de áudio",
            adapter="audio_generate",
            attempt=1,
            item_key=item_key,
            services={"stderr_tail": detalhe},
        ),
    )


def _saida_invalida(item_key: str, detalhe: str) -> AudioOutcome:
    return AudioOutcome(
        item_key=item_key,
        failure=FailureDetail(
            code="tts_output_missing",
            message=f"Áudio não produzido: {detalhe}",
            failure_class=FailureClass.DETERMINISTIC,
            retriable=False,
            recommended_action="Conferir o pedido enviado ao audiocpp_server",
            adapter="audio_generate",
            attempt=1,
            item_key=item_key,
        ),
    )


def _clean_text(value: str) -> str:
    # O servidor trata o texto como fala; tags de emoção e quebras de linha
    # não são narração.
    return _EMOTION_TAG.sub("", value).strip().replace("\r", " ").replace("\n", " ")


def montar_payload(request: AudioRequest, settings: Settings) -> dict[str, Any]:
    """Corpo de `/v1/audio/speech`.

    Os campos de clonagem vão no nível de cima: dentro de `options` o servidor
    os ignora em silêncio e devolve uma voz não clonada com status 200.
    """
    payload: dict[str, Any] = {
        "model": MODELO_ID,
        "input": _clean_text(request.text),
        "response_format": "wav",
        "voice_ref": str(settings.resolved_tts_voice_reference),
        "reference_text": settings.tts_reference_text,
        "seed": settings.tts_seed if request.seed is None else request.seed,
    }
    if request.max_tokens is not None:
        payload["max_tokens"] = request.max_tokens
    return payload


class AudioGenerateClient:
    def __init__(self, settings: Settings, *, http: httpx.Client | None = None) -> None:
        self.settings = settings
        self._http = http or httpx.Client()

    def synthesize(self, request: AudioRequest, servidor: Any, destino_dir: Path) -> AudioOutcome:
        """Sintetiza um trecho em `destino_dir/<item_key>.wav`."""
        if not _ITEM_KEY.fullmatch(request.item_key):
            return _saida_invalida(request.item_key, "identificador de bloco inválido")
        destino_dir = Path(destino_dir)
        destino_dir.mkdir(parents=True, exist_ok=True)
        try:
            resposta = self._http.post(
                servidor.url + "/v1/audio/speech",
                json=montar_payload(request, self.settings),
                timeout=self.settings.tts_item_timeout,
            )
        except httpx.HTTPError as error:
            return _indisponivel(request.item_key, error)
        if resposta.status_code != 200:
            try:
                mensagem = str(resposta.json()["error"]["message"])
            except (ValueError, KeyError, TypeError):
                mensagem = resposta.text
            failure = classify_audio_failure(
                mensagem, status=resposta.status_code, item_key=request.item_key,
            )
            return AudioOutcome(item_key=request.item_key, failure=failure, stderr=_tail(mensagem))
        if not resposta.content:
            return _saida_invalida(request.item_key, "resposta vazia do servidor")
        destino = destino_dir / f"{request.item_key}.wav"
        # Nunca meio arquivo com o nome canônico: a montagem e o reuso leem
        # `<key>.wav` direto do disco.
        temporario = destino.with_name(destino.name + ".tmp")
        temporario.write_bytes(resposta.content)
        temporario.replace(destino)
        return AudioOutcome.succeeded(request.item_key, destino)


__all__ = [
    "FALHAS_DE_SERVIDOR",
    "SERVIDOR_INDISPONIVEL",
    "AudioGenerateClient",
    "AudioOutcome",
    "AudioRequest",
    "classify_audio_failure",
    "montar_payload",
]
