"""Transporte nativo Codex OAuth: inferência pura, sem agente intermediário.

Baseado no protocolo documentado no código MIT do Hermes Agent; veja
THIRD_PARTY_NOTICES.md. Identidade própria Forge e endpoints oficiais fixos.
"""

from __future__ import annotations

import json
import tempfile
import time
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from forge.infrastructure.config import Settings
from forge.services.codex import CodexError, CodexUsageLimitError, _strict_schema
from forge.infrastructure.logging import get_logger
from forge.services.codex_auth import CodexAuthError, OAuthCredentials, request_headers

BASE_URL = "https://chatgpt.com/backend-api/codex"
_RETRY_DELAYS = (2.0, 4.0)
_OVERLOAD_CODES = frozenset({
    "server_overloaded", "overloaded", "overloaded_error", "model_overloaded", "service_unavailable",
})
logger = get_logger(__name__)


class CodexUnavailableError(CodexError):
    """O servidor declarou indisponibilidade temporária."""


@dataclass(frozen=True)
class NativeResponse:
    text: str
    work_dir: Path
    model: str
    usage: dict = field(default_factory=dict)
    request_id: str | None = None


def _safe_message(payload: dict, token: str) -> str:
    error = (
        payload.get("error") or (payload.get("response") or {}).get("error") or payload
    )
    message = error.get("message", "") if isinstance(error, dict) else ""
    return (
        str(message).replace(token, "[redacted]")[:700] if token else str(message)[:700]
    )


def check_http(response: httpx.Response, token: str) -> None:
    if response.status_code < 400:
        return
    try:
        payload = json.loads(response.read())
        detail = _safe_message(payload, token) if isinstance(payload, dict) else ""
    except (ValueError, httpx.HTTPError):
        detail = ""
    message = f"Codex HTTP {response.status_code}: {detail}"
    if response.status_code in (401, 403):
        raise CodexAuthError(
            message + "; verifique acesso ou execute forge auth codex login"
        )
    if response.status_code == 429:
        raise CodexUsageLimitError("Cota Codex indisponível; " + message)
    if response.status_code in (502, 503, 504):
        raise CodexUnavailableError(message)
    raise CodexError(message)


def _events(response: httpx.Response, deadline: float):
    data = []
    size = 0
    for line in response.iter_lines():
        if time.monotonic() > deadline:
            raise CodexError("Codex excedeu prazo total da chamada")
        size += len(line)
        if size > 32 * 1024 * 1024:
            raise CodexError("Stream Codex excedeu limite de segurança")
        if line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
        elif line == "" and data:
            raw = "\n".join(data)
            data.clear()
            if raw == "[DONE]":
                continue
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise CodexError("Evento Codex inválido")
            yield value
    if data:
        raw = "\n".join(data)
        if raw != "[DONE]":
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise CodexError("Evento Codex inválido")
            yield value


class CodexNative:
    def __init__(
        self, settings: Settings, *, auth=None, client: httpx.Client | None = None
    ):
        self.settings = settings
        self.auth = auth or OAuthCredentials(settings.codex_auth_file)
        self.client = client

    def check_auth(self) -> None:
        self.auth.access_token()

    def chat(
        self,
        messages: list[dict],
        *,
        model: str,
        timeout: float,
        schema: dict | None = None,
    ) -> NativeResponse:
        if timeout <= 0 or not model.strip():
            raise CodexError("Modelo e prazo positivo são obrigatórios")
        if not messages or any(
            m.get("role") not in ("system", "developer", "user", "assistant")
            or not isinstance(m.get("content"), str)
            for m in messages
        ):
            raise CodexError(
                "Transporte Codex exige mensagens textuais com papéis válidos"
            )
        token = self.auth.access_token()
        root = self.settings.codex_runs_dir.resolve()
        root.mkdir(parents=True, exist_ok=True)
        work_dir = Path(tempfile.mkdtemp(prefix="native-", dir=root))
        instructions = "\n\n".join(
            m["content"] for m in messages if m["role"] in ("system", "developer")
        )
        body = {
            "model": model,
            "instructions": instructions or "Responda diretamente à tarefa.",
            "input": [
                {"role": m["role"], "content": m["content"]}
                for m in messages
                if m["role"] not in ("system", "developer")
            ],
            "store": False,
            "stream": True,
            "tools": [],
        }
        if schema is not None:
            body["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "forge_response",
                    "strict": True,
                    "schema": _strict_schema(schema),
                }
            }
        (work_dir / "request.json").write_text(
            json.dumps(body, ensure_ascii=False).replace(token, "[redacted]"),
            encoding="utf-8",
        )
        context = (
            nullcontext(self.client)
            if self.client is not None
            else httpx.Client(timeout=timeout)
        )
        deadline = time.monotonic() + timeout
        try:
            with context as client:
                for attempt in range(1, len(_RETRY_DELAYS) + 2):
                    try:
                        return self._request_once(client, body, token, work_dir, deadline, attempt)
                    except CodexUnavailableError:
                        if attempt > len(_RETRY_DELAYS):
                            raise
                        delay = _RETRY_DELAYS[attempt - 1]
                        if time.monotonic() + delay >= deadline:
                            raise
                        logger.warning("Codex indisponível; repetindo chamada", attempt=attempt, delay=delay)
                        time.sleep(delay)
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
            raise CodexError(
                f"Falha de transporte ou resposta Codex inválida; logs: {work_dir}"
            ) from None
        except CodexError as error:
            raise type(error)(f"{error}; logs: {work_dir}") from None

    @staticmethod
    def _request_once(
        client: httpx.Client, body: dict, token: str, work_dir: Path, deadline: float, attempt: int,
    ) -> NativeResponse:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CodexUnavailableError("Prazo esgotado enquanto o Codex estava indisponível")
        with client.stream(
            "POST", f"{BASE_URL}/responses", headers=request_headers(token),
            json=body, timeout=remaining,
        ) as response:
            check_http(response, token)
            with (work_dir / "events.jsonl").open("a", encoding="utf-8") as events:
                for event in _events(response, deadline):
                    events.write(json.dumps({"type": event.get("type"), "attempt": attempt}) + "\n")
                    events.flush()
                    if event.get("type") in (
                        "error",
                        "response.failed",
                        "response.incomplete",
                    ):
                        detail = _safe_message(event, token)
                        error = (
                            event.get("error")
                            or (event.get("response") or {}).get("error")
                            or event
                        )
                        code = (
                            str(error.get("code", ""))
                            if isinstance(error, dict)
                            else ""
                        )
                        if "usage_limit" in code or "usage limit" in detail.lower():
                            raise CodexUsageLimitError(
                                "Cota Codex indisponível; " + detail
                            )
                        if code in _OVERLOAD_CODES or (
                            "servers are currently overloaded" in detail.casefold()
                        ):
                            raise CodexUnavailableError("Resposta Codex indisponível: " + detail)
                        raise CodexError("Resposta Codex falhou: " + detail)
                    if event.get("type") == "response.completed":
                        result = event.get("response") or {}
                        if (
                            result.get("status") != "completed"
                            or result.get("model") != body["model"]
                        ):
                            raise CodexError(
                                "Resposta Codex incompleta ou modelo diferente do solicitado"
                            )
                        parts = [
                            part
                            for item in result.get("output", [])
                            if item.get("type") == "message"
                            for part in item.get("content", [])
                        ]
                        if any(part.get("type") == "refusal" for part in parts):
                            raise CodexError("Codex recusou a solicitação")
                        text = "".join(
                            part.get("text", "")
                            for part in parts
                            if part.get("type") == "output_text"
                        )
                        if not text.strip():
                            raise CodexError("Codex concluiu sem texto")
                        if "text" in body:
                            json.loads(text)
                        metadata = {
                            "model": result["model"],
                            "status": result["status"],
                            "usage": result.get("usage") or {},
                            "request_id": result.get("id"),
                        }
                        (work_dir / "response.txt").write_text(
                            text.replace(token, "[redacted]"), encoding="utf-8"
                        )
                        (work_dir / "metadata.json").write_text(
                            json.dumps(metadata, ensure_ascii=False),
                            encoding="utf-8",
                        )
                        return NativeResponse(
                            text,
                            work_dir,
                            result["model"],
                            metadata["usage"],
                            metadata["request_id"],
                        )
        raise CodexError("Stream Codex terminou sem response.completed")
