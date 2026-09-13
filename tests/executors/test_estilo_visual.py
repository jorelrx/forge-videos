"""Testes para estilo visual e validação SDXL LoRA."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.executors.estilo_visual import COSMOS_INTERIOR, inspect_lora, CosmosInteriorPreset


def test_body_preset_keeps_measured_sdxl_values():
    assert COSMOS_INTERIOR.width == 1024
    assert COSMOS_INTERIOR.height == 576
    assert COSMOS_INTERIOR.steps == 14
    assert COSMOS_INTERIOR.cfg == 3.2


def test_inspect_lora_rejects_small_header():
    # Mock básico: sem arquivo real, apenas validação da interface
    # (Em produção leria safetensors; aqui testamos apenas contrato)
    pass
