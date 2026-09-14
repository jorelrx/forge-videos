"""Cliente ComfyUI real: workflow SDXL, enfileiramento e coleta da imagem.

Os testes usam `httpx.MockTransport`, então nada aqui toca a rede.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from forge.executors.comfy import ComfyClient, ComfyError
from forge.executors.estilo_visual import COSMOS_INTERIOR
from forge.infrastructure.config import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        comfy_url="http://comfy.test:8188",
        image_width=1024,
        image_height=576,
        image_steps=14,
        image_cfg=3.2,
        image_seed=42,
    )


def _client(handler, tmp_path: Path) -> ComfyClient:
    transport = httpx.MockTransport(handler)
    return ComfyClient(
        _settings(tmp_path),
        client=httpx.Client(base_url="http://comfy.test:8188", transport=transport),
        poll_interval=0.001,
    )


def test_offline_client_returns_a_placeholder_path_without_network(tmp_path):
    """`offline` é o seam que exercita o gate de imagem ilegível."""
    client = ComfyClient(_settings(tmp_path), offline=True)

    caminho = client.generate("cosmic scene", seed=42)

    assert "video" in str(caminho)
    assert not Path(caminho).is_absolute()


class TestAlive:
    def test_alive_true_when_system_stats_answers(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/system_stats"
            return httpx.Response(200, json={"system": {}})

        assert _client(handler, tmp_path).alive() is True

    def test_alive_false_when_server_is_down(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("recusado")

        assert _client(handler, tmp_path).alive() is False

    def test_alive_false_on_server_error(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        assert _client(handler, tmp_path).alive() is False


class TestBuildWorkflow:
    def test_workflow_is_sdxl_txt2img_with_tiled_decode(self, tmp_path):
        """VAEDecode estoura a VRAM de 8 GB; o decode tem de ser em tiles."""
        workflow = _client(
            lambda request: httpx.Response(200, json={}), tmp_path
        ).build_workflow("a lone figure", seed=7, preset=COSMOS_INTERIOR)

        classes = {node["class_type"] for node in workflow.values()}
        assert "CheckpointLoaderSimple" in classes
        assert "KSampler" in classes
        assert "VAEDecodeTiled" in classes
        assert "VAEDecode" not in classes
        assert "SaveImage" in classes

        latent = next(
            node for node in workflow.values()
            if node["class_type"] == "EmptyLatentImage"
        )
        assert (latent["inputs"]["width"], latent["inputs"]["height"]) == (1024, 576)

        sampler = next(
            node for node in workflow.values() if node["class_type"] == "KSampler"
        )
        assert sampler["inputs"]["seed"] == 7
        assert sampler["inputs"]["steps"] == COSMOS_INTERIOR.steps
        assert sampler["inputs"]["cfg"] == COSMOS_INTERIOR.cfg

    def test_workflow_carries_the_negative_prompt(self, tmp_path):
        workflow = _client(
            lambda request: httpx.Response(200, json={}), tmp_path
        ).build_workflow("cena", seed=1, preset=COSMOS_INTERIOR)

        negatives = [
            node["inputs"]["text"]
            for node in workflow.values()
            if node["class_type"] == "CLIPTextEncode"
        ]
        assert any("watermark" in text for text in negatives)


class TestGenerate:
    def _happy_handler(self, captured: dict, payload: bytes):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/system_stats":
                return httpx.Response(200, json={"system": {}})
            if request.url.path == "/prompt":
                captured["body"] = json.loads(request.content.decode())
                return httpx.Response(200, json={"prompt_id": "pid-1"})
            if request.url.path == "/history/pid-1":
                return httpx.Response(
                    200,
                    json={
                        "pid-1": {
                            "status": {"completed": True, "messages": []},
                            "outputs": {
                                "9": {
                                    "images": [
                                        {
                                            "filename": "canal_00001_.png",
                                            "subfolder": "",
                                            "type": "output",
                                        }
                                    ]
                                }
                            },
                        }
                    },
                )
            if request.url.path == "/view":
                assert request.url.params["filename"] == "canal_00001_.png"
                return httpx.Response(200, content=payload)
            raise AssertionError(f"rota inesperada: {request.url.path}")

        return handler

    def test_generate_enqueues_polls_and_writes_the_image(self, tmp_path):
        png = b"\x89PNG\r\n\x1a\nfake"
        captured: dict = {}
        dest = tmp_path / "run" / "video" / "images" / "i001.png"
        dest.parent.mkdir(parents=True)

        result = _client(self._happy_handler(captured, png), tmp_path).generate(
            "cena qualquer", seed=5, dest=dest
        )

        assert result == dest
        assert dest.read_bytes() == png
        body = captured["body"]
        assert "prompt" in body and "client_id" in body
        sampler = next(
            node for node in body["prompt"].values()
            if node["class_type"] == "KSampler"
        )
        assert sampler["inputs"]["seed"] == 5

    def test_generate_reports_the_execution_error_node(self, tmp_path):
        """O dict de status cru vinha truncado e escondia a causa real."""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/system_stats":
                return httpx.Response(200, json={"system": {}})
            if request.url.path == "/prompt":
                return httpx.Response(200, json={"prompt_id": "pid-2"})
            if request.url.path == "/history/pid-2":
                return httpx.Response(
                    200,
                    json={
                        "pid-2": {
                            "status": {
                                "completed": False,
                                "messages": [
                                    [
                                        "execution_error",
                                        {
                                            "node_id": "3",
                                            "node_type": "KSampler",
                                            "exception_message": (
                                                "Could not allocate tensor"
                                            ),
                                        },
                                    ]
                                ],
                            },
                            "outputs": {},
                        }
                    },
                )
            raise AssertionError(f"rota inesperada: {request.url.path}")

        with pytest.raises(ComfyError, match="KSampler#3.*Could not allocate tensor"):
            _client(handler, tmp_path).generate(
                "cena", seed=1, dest=tmp_path / "out.png"
            )

    def test_generate_raises_when_no_image_is_produced(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/system_stats":
                return httpx.Response(200, json={"system": {}})
            if request.url.path == "/prompt":
                return httpx.Response(200, json={"prompt_id": "pid-3"})
            if request.url.path == "/history/pid-3":
                return httpx.Response(
                    200, json={"pid-3": {"status": {}, "outputs": {}}}
                )
            raise AssertionError(f"rota inesperada: {request.url.path}")

        with pytest.raises(ComfyError, match="sem imagem"):
            _client(handler, tmp_path).generate("cena", seed=1, dest=tmp_path / "o.png")

    def test_generate_raises_when_offline_without_touching_the_disk(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("recusado")

        dest = tmp_path / "out.png"
        with pytest.raises(ComfyError, match="offline"):
            _client(handler, tmp_path).generate("cena", seed=1, dest=dest)

        assert not dest.exists()


class TestCacheKey:
    def test_cache_key_is_stable_and_prompt_sensitive(self, tmp_path):
        client = _client(lambda request: httpx.Response(200, json={}), tmp_path)

        first = client.cache_key("cena", 42, COSMOS_INTERIOR, [])
        assert first == client.cache_key("cena", 42, COSMOS_INTERIOR, [])
        assert first != client.cache_key("outra", 42, COSMOS_INTERIOR, [])
        assert first != client.cache_key("cena", 43, COSMOS_INTERIOR, [])
