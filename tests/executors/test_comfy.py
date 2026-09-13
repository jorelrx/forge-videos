"""Testes para ComfyUI client."""

from __future__ import annotations

from pathlib import Path

from forge.executors.comfy import ComfyClient
from forge.infrastructure.config import Settings


def test_client_uses_mock_when_offline():
    client = ComfyClient(settings=Settings(), offline=True)
    path = client.generate("cosmic scene", seed=42)
    # Offline mock retorna caminho relativo; valida apenas conteúdo parcial
    assert "video" in str(path)


def test_cache_key_is_sha256():
    client = ComfyClient()
    key = client.cache_key("prompt", 42, __import__("forge.executors.estilo_visual", fromlist=["COSMOS_INTERIOR"]).COSMOS_INTERIOR, [])
    assert len(key) == 64
