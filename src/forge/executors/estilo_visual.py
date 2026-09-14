"""Direção de arte "Cosmos Interior" e validação real de LoRA SDXL.

O style token é o que faz dois vídeos diferentes parecerem do mesmo canal:
mesmo sufixo de prompt, mesmo negativo, mesmas LoRAs, mesmo sampler.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from pathlib import Path

from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Sufixo aplicado a TODA imagem. Não há "starfield" aqui de propósito: com o
# campo estelar no style token, ele vazava para cenas internas — pontos brancos
# sobre paredes sólidas. O cosmos entra pela CENA; o estilo carrega luz, paleta
# e câmera.
STYLE_TOKEN = (
    "cinematic still, deep midnight blue and warm amber accent, "
    "volumetric god rays, atmospheric haze, high contrast chiaroscuro, "
    "lone small human silhouette for scale, "
    "painterly digital art, subtle film grain, 35mm anamorphic, "
    "shallow depth of field, dramatic rim light, awe and solitude, "
    "clean smooth surfaces, highly detailed, masterpiece, 8k"
)

# As últimas linhas cobrem defeitos medidos em frame renderizado: sem elas, as
# "estrelas" do estilo apareciam dentro de paredes e móveis.
NEGATIVE_PROMPT = (
    "text, watermark, signature, logo, letters, caption, "
    "deformed hands, extra fingers, mutated limbs, bad anatomy, "
    "close-up face, portrait, facial features, eyes, "
    "cartoon, anime, comic, 3d render, cgi, plastic, "
    "oversaturated, neon pink, lowres, blurry, jpeg artifacts, "
    "cluttered, busy composition, collage, multiple panels, nsfw, "
    "stars on walls, double exposure, overlay texture, speckled surfaces, "
    "white dots on solid objects, banding, vertical stripes, scan lines"
)

CHECKPOINT_CORPO = "juggernautXL_ragnarok_dmd2.safetensors"
CHECKPOINT_CAPA = "epicrealismXL_vxviiCrystalclear.safetensors"

# LoRAs de estilo pretendidas. Só SDXL vale: ver `inspect_lora`.
LORAS = (
    {"nome": "add-detail-xl.safetensors", "peso": 0.55},
    {"nome": "more_details.safetensors", "peso": 0.35},
)

# SDXL de verdade tem ~2000+ tensores e dimensão chegando a 3072.
SDXL_MIN_KEYS = 1500
SDXL_MIN_DIM = 2048


@dataclass(frozen=True)
class CosmosInteriorPreset:
    name: str = "cosmos-interior"
    width: int = 1024
    height: int = 576
    # 8 passos (DMD2 puro) produz listras verticais na imagem inteira; 14 passos
    # com CFG 3.2 limpam o artefato mantendo o custo viável nesta placa.
    steps: int = 14
    cfg: float = 3.2
    sampler: str = "dpmpp_2m"
    scheduler: str = "karras"
    # VAEDecode estoura a VRAM de 8 GB; o decode tem de ser em tiles.
    decoder: str = "VAEDecodeTiled"
    seed: int = 42

    @property
    def negative_prompt(self) -> str:
        return NEGATIVE_PROMPT


COSMOS_INTERIOR = CosmosInteriorPreset()


@dataclass(frozen=True)
class LoraInspection:
    path: Path
    compatible_sdxl: bool = False
    keys: int = 0
    max_dim: int = 0
    error: str = ""


def inspect_lora(path: Path) -> LoraInspection:
    """Lê o header safetensors e decide se a LoRA é SDXL.

    Uma LoRA de SD 1.5 aplicada a checkpoint SDXL não levanta erro: o ComfyUI
    loga `shape ... is invalid` por centenas de tensores e segue SEM aplicar
    nada. Conferir na carga evita depurar uma imagem que "não mudou".
    """
    path = Path(path)
    if not path.is_file():
        return LoraInspection(path=path, error="arquivo ausente")
    try:
        with path.open("rb") as handle:
            header_len = struct.unpack("<Q", handle.read(8))[0]
            header = json.loads(handle.read(header_len).decode("utf-8"))
    except (OSError, ValueError, struct.error) as error:
        return LoraInspection(path=path, error=f"header ilegível: {error}")

    keys = [key for key in header if key != "__metadata__"]
    dims = {
        max(header[key].get("shape") or [0])
        for key in keys[:200]
    }
    maior = max(dims) if dims else 0
    return LoraInspection(
        path=path,
        compatible_sdxl=len(keys) >= SDXL_MIN_KEYS and maior >= SDXL_MIN_DIM,
        keys=len(keys),
        max_dim=maior,
    )


def loras_disponiveis(lora_dir: Path) -> list[dict]:
    """Só as LoRAs configuradas que existem e são de fato SDXL."""
    base = Path(lora_dir)
    compativeis: list[dict] = []
    for lora in LORAS:
        inspecao = inspect_lora(base / lora["nome"])
        if inspecao.compatible_sdxl:
            compativeis.append(lora)
        else:
            # Logger, não print: stdout do executor carrega o protocolo JSONL.
            logger.warning(
                "LoRA ignorada",
                lora=lora["nome"],
                motivo=inspecao.error
                or f"chaves={inspecao.keys}, maior_dim={inspecao.max_dim}",
            )
    return compativeis


def prompt_de_imagem(descricao_cena: str) -> str:
    """Junta a cena específica ao style token do canal."""
    return f"{descricao_cena.strip().rstrip('.')}, {STYLE_TOKEN}"
