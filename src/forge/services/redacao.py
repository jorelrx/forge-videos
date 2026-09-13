from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

CREDENTIAL_KEYS = frozenset(
    {"api_key", "authorization", "password", "secret", "token"}
)


class Redactor:
    def __init__(self, secrets: list[str]) -> None:
        self._secrets = set(secrets)

    def clean(self, data: Any) -> Any:
        if isinstance(data, str):
            return self._redact_string(data)
        if isinstance(data, Mapping):
            result = {}
            for k, v in data.items():
                result[k] = self._redact_credential_value(str(k), v)
            return result
        if isinstance(data, Sequence) and not isinstance(data, (str, bytes)):
            return type(data)(self.clean(item) for item in data)
        return data

    def _redact_credential_value(self, key: str, value: Any) -> Any:
        normalized = key.lower().strip()
        if normalized in CREDENTIAL_KEYS:
            return "[REDACTED]"
        return self.clean(value)

    def _redact_string(self, value: str) -> str:
        for secret in self._secrets:
            value = value.replace(secret, "[REDACTED]")
        return value
