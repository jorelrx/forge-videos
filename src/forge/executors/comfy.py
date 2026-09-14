"""Cliente ComfyUI real: SDXL txt2img pela API HTTP.

Armadilhas já medidas nesta máquina (RX 580 8 GB), embutidas aqui:

- `VAEDecode` estoura a VRAM; o decode tem de ser `VAEDecodeTiled`.
- Uma LoRA de SD 1.5 aplicada a checkpoint SDXL não levanta erro: o ComfyUI
  segue SEM aplicar nada. Por isso a cadeia só recebe LoRA validada.
- O dict de `status` cru vinha truncado no JSON e escondia a causa real
  (`Could not allocate tensor ... not enough GPU video memory`). A mensagem do
  nó que falhou é extraída explicitamente.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

import httpx

from forge.executors.estilo_visual import (
    COSMOS_INTERIOR,
    CHECKPOINT_CORPO,
    CosmosInteriorPreset,
    loras_disponiveis,
    prompt_de_imagem,
)
from forge.infrastructure.config import Settings
from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)

POLL_INTERVAL_SECONDS = 5.0
NEGATIVE_NODE = "7"
POSITIVE_NODE = "6"
SAMPLER_NODE = "3"
LATENT_NODE = "5"
CHECKPOINT_NODE = "4"
DECODE_NODE = "8"
SAVE_NODE = "9"
FIRST_LORA_NODE = 20


class ComfyError(RuntimeError):
    """O ComfyUI não produziu a imagem, com a causa que ele mesmo relatou."""


class ComfyClient:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        offline: bool = False,
        client: httpx.Client | None = None,
        poll_interval: float = POLL_INTERVAL_SECONDS,
    ) -> None:
        self.settings = settings or Settings()
        # `offline` fabrica um caminho inexistente de propósito: é o seam que
        # exercita o gate de imagem ilegível. Nunca é o caminho de produção.
        self.offline = offline
        self.url = self.settings.comfy_url
        self.poll_interval = poll_interval
        self._client = client or httpx.Client(
            base_url=self.url.rstrip("/"), timeout=60.0
        )

    # ------------------------------------------------------------------
    # Saúde
    # ------------------------------------------------------------------

    def alive(self, timeout: float = 5.0) -> bool:
        try:
            resp = self._client.get("/system_stats", timeout=timeout)
            resp.raise_for_status()
        except Exception:  # noqa: BLE001 - qualquer falha aqui é "fora do ar"
            return False
        return True

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------

    def build_workflow(
        self,
        prompt: str,
        seed: int,
        *,
        preset: CosmosInteriorPreset = COSMOS_INTERIOR,
        loras: list[dict] | None = None,
    ) -> dict[str, Any]:
        """SDXL txt2img 16:9 nativo, com decode em tiles e LoRAs validadas."""
        if loras is None:
            loras = loras_disponiveis(self.settings.lora_dir)

        workflow: dict[str, Any] = {
            CHECKPOINT_NODE: {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": CHECKPOINT_CORPO},
            }
        }

        # Cadeia de LoRAs: cada uma recebe a saída da anterior.
        model_ref: list[Any] = [CHECKPOINT_NODE, 0]
        clip_ref: list[Any] = [CHECKPOINT_NODE, 1]
        node_id = FIRST_LORA_NODE
        for lora in loras:
            workflow[str(node_id)] = {
                "class_type": "LoraLoader",
                "inputs": {
                    "lora_name": lora["nome"],
                    "strength_model": lora["peso"],
                    "strength_clip": lora["peso"],
                    "model": model_ref,
                    "clip": clip_ref,
                },
            }
            model_ref, clip_ref = [str(node_id), 0], [str(node_id), 1]
            node_id += 1

        workflow.update(
            {
                POSITIVE_NODE: {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"text": prompt, "clip": clip_ref},
                },
                NEGATIVE_NODE: {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"text": preset.negative_prompt, "clip": clip_ref},
                },
                LATENT_NODE: {
                    "class_type": "EmptyLatentImage",
                    "inputs": {
                        "width": preset.width,
                        "height": preset.height,
                        "batch_size": 1,
                    },
                },
                SAMPLER_NODE: {
                    "class_type": "KSampler",
                    "inputs": {
                        "seed": seed,
                        "steps": preset.steps,
                        "cfg": preset.cfg,
                        "sampler_name": preset.sampler,
                        "scheduler": preset.scheduler,
                        "denoise": 1.0,
                        "model": model_ref,
                        "positive": [POSITIVE_NODE, 0],
                        "negative": [NEGATIVE_NODE, 0],
                        "latent_image": [LATENT_NODE, 0],
                    },
                },
                DECODE_NODE: {
                    "class_type": preset.decoder,
                    "inputs": {
                        "samples": [SAMPLER_NODE, 0],
                        "vae": [CHECKPOINT_NODE, 2],
                        "tile_size": 512,
                        "overlap": 64,
                        "temporal_size": 64,
                        "temporal_overlap": 8,
                    },
                },
                SAVE_NODE: {
                    "class_type": "SaveImage",
                    "inputs": {
                        "filename_prefix": "forge",
                        "images": [DECODE_NODE, 0],
                    },
                },
            }
        )
        return workflow

    # ------------------------------------------------------------------
    # Geração
    # ------------------------------------------------------------------

    def default_destination(self, prompt: str, seed: int) -> Path:
        return Path(self.settings.image_library_dir) / f"{self.cache_key(prompt, seed, COSMOS_INTERIOR, [])}.png"

    def generate(
        self,
        prompt: str,
        seed: int = 42,
        *,
        dest: Path | None = None,
        preset: CosmosInteriorPreset = COSMOS_INTERIOR,
        timeout: float | None = None,
    ) -> Path:
        """Gera uma imagem e a grava em `dest`.

        Sem `dest`, grava na biblioteca local indexada por cache key — é o que
        torna uma imagem já produzida reutilizável entre vídeos.
        """
        if self.offline:
            return Path("video/images/fallback.png")

        destino = Path(dest) if dest is not None else self.default_destination(prompt, seed)
        if not self.alive():
            raise ComfyError(
                f"ComfyUI offline em {self.url}: inicie o servidor (system_stats não respondeu)"
            )

        prompt_final = prompt_de_imagem(prompt)
        client_id = hashlib.sha256(
            f"{prompt_final}|{seed}".encode("utf-8")
        ).hexdigest()[:16]

        prompt_id = self._enqueue(prompt_final, seed, client_id, preset)
        imagem = self._await_image(prompt_id, timeout or self.settings.image_timeout)

        destino.parent.mkdir(parents=True, exist_ok=True)
        self._download(imagem, destino)
        logger.info(
            "Comfy image generated",
            prompt_id=prompt_id,
            dest=str(destino),
            bytes=destino.stat().st_size,
        )
        return destino

    def _enqueue(
        self,
        prompt: str,
        seed: int,
        client_id: str,
        preset: CosmosInteriorPreset,
    ) -> str:
        try:
            resp = self._client.post(
                "/prompt",
                json={"prompt": self.build_workflow(prompt, seed, preset=preset),
                      "client_id": client_id},
            )
            resp.raise_for_status()
            return str(resp.json()["prompt_id"])
        except (httpx.HTTPError, KeyError, ValueError) as error:
            raise ComfyError(f"falha ao enfileirar no ComfyUI: {error}") from error

    def _await_image(self, prompt_id: str, timeout: float) -> dict[str, Any]:
        prazo = time.monotonic() + timeout
        while time.monotonic() < prazo:
            time.sleep(self.poll_interval)
            try:
                resp = self._client.get(f"/history/{prompt_id}", timeout=30.0)
                resp.raise_for_status()
                historico = resp.json()
            except (httpx.HTTPError, ValueError):
                continue
            entrada = historico.get(prompt_id)
            if entrada is None:
                continue
            imagens = [
                imagem
                for node in entrada.get("outputs", {}).values()
                for imagem in node.get("images", [])
            ]
            if imagens:
                return imagens[0]
            raise ComfyError(
                f"ComfyUI terminou sem imagem: {_detalhe_do_erro(entrada.get('status', {}))}"
            )
        raise ComfyError(f"ComfyUI não produziu imagem em {timeout:.0f}s")

    def _download(self, imagem: dict[str, Any], destino: Path) -> None:
        params = {
            "filename": str(imagem.get("filename", "")),
            "subfolder": str(imagem.get("subfolder", "")),
            "type": str(imagem.get("type", "output")),
        }
        try:
            resp = self._client.get("/view", params=params, timeout=180.0)
            resp.raise_for_status()
        except httpx.HTTPError as error:
            raise ComfyError(f"falha ao baixar a imagem do ComfyUI: {error}") from error
        destino.write_bytes(resp.content)

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def cache_key(
        self,
        prompt: str,
        seed: int,
        preset: CosmosInteriorPreset,
        loras: list[str],
        sampler: str | None = None,
    ) -> str:
        amostragem = sampler or preset.sampler
        return hashlib.sha256(
            (prompt + str(seed) + preset.name + ":".join(loras) + amostragem).encode("utf-8")
        ).hexdigest()


def _detalhe_do_erro(status: dict[str, Any]) -> str:
    """Extrai a mensagem do nó que falhou, em vez do dict cru truncado."""
    for mensagem in status.get("messages", []) or []:
        if not mensagem:
            continue
        if mensagem[0] == "execution_error":
            dados = mensagem[1] if len(mensagem) > 1 else {}
            return (
                f"{dados.get('node_type')}#{dados.get('node_id')}: "
                f"{dados.get('exception_message')}"
            )
    return str(status)[:400]


__all__ = ["ComfyClient", "ComfyError"]
