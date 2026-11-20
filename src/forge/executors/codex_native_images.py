"""Imagens via endpoint nativo Codex, sem LLM hospedeiro nem GPU local.

Protocolo adaptado do Hermes Agent (MIT); veja THIRD_PARTY_NOTICES.md.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import tempfile
import uuid
from contextlib import nullcontext
from pathlib import Path

import httpx
from filelock import FileLock
from PIL import Image, ImageOps

from forge.executors.estilo_visual import COSMOS_INTERIOR, prompt_de_imagem
from forge.infrastructure.config import Settings
from forge.services.codex import CodexError
from forge.services.codex_auth import OAuthCredentials, request_headers
from forge.services.codex_native import BASE_URL, check_http


class NativeCodexImageClient:
    def __init__(
        self, settings: Settings, *, auth=None, client: httpx.Client | None = None
    ):
        self.settings = settings
        self.auth = auth or OAuthCredentials(settings.codex_auth_file)
        self.client = client
        self._metadata: dict[Path, dict] = {}

    def generate(self, prompt: str, seed: int = 42, *, dest: Path) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(dest) + ".lock", timeout=self.settings.image_timeout):
            try:
                receipt = json.loads(
                    dest.with_suffix(".codex.json").read_text(encoding="utf-8")
                )
                if (
                    receipt["cache_key"] == self.cache_key(prompt, seed)
                    and receipt["sha256"]
                    == hashlib.sha256(dest.read_bytes()).hexdigest()
                ):
                    with Image.open(dest) as cached:
                        cached.load()
                        if cached.size == (
                            self.settings.image_width,
                            self.settings.image_height,
                        ):
                            self._metadata[dest.resolve()] = receipt["metadata"]
                            return dest
            except (
                OSError,
                ValueError,
                KeyError,
                TypeError,
                Image.DecompressionBombError,
            ):
                pass
            try:
                return self._generate(prompt, seed, dest=dest)
            except CodexError:
                raise
            except (
                httpx.HTTPError,
                OSError,
                ValueError,
                KeyError,
                TypeError,
                IndexError,
                Image.DecompressionBombError,
            ):
                raise CodexError(
                    f"Falha de transporte ou imagem Codex inválida; logs: {dest.parent / '.codex-native'}"
                ) from None

    def _generate(self, prompt: str, seed: int, *, dest: Path) -> Path:
        root = dest.parent / ".codex-native"
        root.mkdir(parents=True, exist_ok=True)
        work_dir = Path(tempfile.mkdtemp(prefix=dest.stem + "-", dir=root)).resolve()
        width, height = self.settings.image_width, self.settings.image_height
        size = (
            "1536x1024"
            if width > height
            else "1024x1536"
            if width < height
            else "1024x1024"
        )
        body = {
            "prompt": prompt_de_imagem(prompt),
            "model": self.settings.codex_image_model,
            "quality": self.settings.codex_image_quality,
            "size": size,
            "n": 1,
            "background": "opaque",
        }
        token = self.auth.access_token()
        (work_dir / "request.json").write_text(
            json.dumps(body, ensure_ascii=False).replace(token, "[redacted]"),
            encoding="utf-8",
        )
        headers = request_headers(token)
        headers["x-codex-image-turn-id"] = str(uuid.uuid4())
        context = (
            nullcontext(self.client)
            if self.client is not None
            else httpx.Client(timeout=self.settings.image_timeout)
        )
        with context as client:
            response = client.post(
                f"{BASE_URL}/images/generations",
                json=body,
                headers=headers,
                timeout=self.settings.image_timeout,
            )
        check_http(response, token)
        payload = response.json()
        data = payload["data"]
        if (
            not isinstance(data, list)
            or len(data) != 1
            or not isinstance(data[0], dict)
            or not isinstance(data[0].get("b64_json"), str)
            or len(data[0]["b64_json"]) > 64 * 1024 * 1024
        ):
            raise CodexError("Codex não retornou uma única imagem inline válida")
        raw = base64.b64decode(data[0]["b64_json"], validate=True)
        original = work_dir / "original.png"
        original.write_bytes(raw)
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            pixel_size = f"{image.width}x{image.height}"
            normalized = ImageOps.fit(
                image.convert("RGB"), (width, height), method=Image.Resampling.LANCZOS
            )
            temporary = work_dir / "normalized.png"
            normalized.save(temporary, format="PNG")
        os.replace(temporary, dest)
        meta = {
            "image_provider": "codex",
            "codex_transport": "native",
            "requested_model": self.settings.codex_image_model,
            "image_model": payload.get("model"),
            "requested_quality": self.settings.codex_image_quality,
            "reported_quality": payload.get("quality"),
            "requested_size": size,
            "reported_size": payload.get("size"),
            "pixel_size": pixel_size,
            "seed": None,
            "seed_applied": False,
            "original_path": str(original),
            "imagegen_request_id": response.headers.get("x-codex-imagegen-request-id"),
            "codex_logs": str(work_dir),
        }
        self._metadata[dest.resolve()] = meta
        receipt = {
            "cache_key": self.cache_key(prompt, seed),
            "sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
            "metadata": meta,
        }
        temporary_receipt = work_dir / "receipt.json"
        temporary_receipt.write_text(
            json.dumps(receipt, ensure_ascii=False), encoding="utf-8"
        )
        os.replace(temporary_receipt, dest.with_suffix(".codex.json"))
        (work_dir / "metadata.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )
        return dest

    def artifact_metadata(self, dest: Path) -> dict:
        return dict(self._metadata[Path(dest).resolve()])

    def cache_key(
        self, prompt, seed, preset=COSMOS_INTERIOR, loras=(), sampler=None
    ) -> str:
        identity = [
            "codex-native-v1",
            self.settings.codex_image_model,
            self.settings.codex_image_quality,
            prompt_de_imagem(prompt),
            seed,
            self.settings.image_width,
            self.settings.image_height,
        ]
        return hashlib.sha256(
            json.dumps(identity, ensure_ascii=False).encode()
        ).hexdigest()
