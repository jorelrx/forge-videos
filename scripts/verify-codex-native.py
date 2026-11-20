"""Smoke real e opt-in: uv run python scripts/verify-codex-native.py --research --image."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import monotonic

from PIL import Image
from pydantic import BaseModel

from forge.executors.imagens import ImageExecutor
from forge.infrastructure.config import Settings
from forge.llms.model import build_chat_model, invoke_structured
from forge.services.acervo import Acervo

IMAGE_PROMPT = "Fotografia realista de uma biblioteca antiga de filosofia ao amanhecer, livros de couro sem letras legiveis, feixe de luz dourada, composicao cinematografica horizontal, sem texto"


class Confirmacao(BaseModel):
    resposta: str


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validação real da assinatura Codex, sem gerar vídeo completo"
    )
    parser.add_argument("--auth-file", type=Path)
    parser.add_argument(
        "--output", type=Path, default=Path("output/validations/codex-native-20261023")
    )
    parser.add_argument(
        "--image",
        action="store_true",
        help="Gerar uma imagem (consome assinatura se não houver cache)",
    )
    parser.add_argument(
        "--research",
        action="store_true",
        help="Consultar acervo real e exigir citação na síntese",
    )
    args = parser.parse_args()
    settings = Settings()
    if settings.provider != "codex" or settings.codex_transport != "native":
        parser.error("Selecione FORGE_PROVIDER=codex e FORGE_CODEX_TRANSPORT=native")
    if settings.resolved_model != "gpt-6.1-sol":
        parser.error("Este smoke exige exatamente FORGE_MODEL=gpt-6.1-sol")
    updates = {"codex_runs_dir": args.output / "text"}
    if args.auth_file:
        updates["codex_auth_file"] = args.auth_file
    settings = settings.model_copy(update=updates)
    args.output.mkdir(parents=True, exist_ok=True)
    report = {
        "status": "running",
        "transport": "native",
        "model": settings.resolved_model,
    }
    try:
        model = build_chat_model(settings)
        started = monotonic()
        response = model.invoke(
            [
                ("system", "Responda somente à tarefa."),
                ("human", "Responda somente OK."),
            ]
        )
        assert response.content.strip() == "OK", "Smoke de texto não retornou OK"
        assert response.response_metadata["model_name"] == settings.resolved_model
        report["text"] = {
            "status": "passed",
            "seconds": round(monotonic() - started, 3),
            "metadata": response.response_metadata,
            "usage": response.usage_metadata,
        }
        started = monotonic()
        parsed = invoke_structured(
            model, Confirmacao, [("human", "Retorne resposta com valor confirmado.")]
        )
        assert parsed.resposta == "confirmado", (
            "Contrato Pydantic não retornou confirmação"
        )
        report["structured"] = {
            "status": "passed",
            "seconds": round(monotonic() - started, 3),
            "result": parsed.model_dump(),
        }
        if args.research:
            started = monotonic()
            passages = Acervo(
                settings.acervo_url, timeout=settings.acervo_timeout
            ).buscar("liberdade", top=1, excerpt=600)
            assert passages, "Acervo retornou pool vazio"
            source = passages[0]
            text = model.invoke(
                [
                    (
                        "system",
                        "Use somente o trecho fornecido. Sintetize em português em duas frases e cite literalmente o caminho informado.",
                    ),
                    (
                        "human",
                        f"Obra: {source.book_title}\nCaminho: {source.path}\nTrecho: {source.text}",
                    ),
                ]
            )
            assert source.path in text.content, "Síntese perdeu caminho da fonte"
            report["research"] = {
                "status": "passed",
                "seconds": round(monotonic() - started, 3),
                "book_id": source.book_id,
                "book_title": source.book_title,
                "path": source.path,
                "summary": text.content,
            }
        if args.image:
            if settings.image_provider != "codex":
                raise ValueError("Smoke de imagem exige FORGE_IMAGE_PROVIDER=codex")
            image_client = ImageExecutor(settings=settings).client
            dest = args.output / "images/smoke.png"
            started = monotonic()
            image_client.generate(IMAGE_PROMPT, dest=dest)
            first_seconds = round(monotonic() - started, 3)
            with Image.open(dest) as image:
                image.load()
                assert image.size == (settings.image_width, settings.image_height)

            class NoNetwork:
                def access_token(self):
                    raise AssertionError("Cache tentou autenticar ou gastar")

            image_client.auth = NoNetwork()
            started = monotonic()
            image_client.generate(IMAGE_PROMPT, dest=dest)
            report["image"] = {
                "status": "passed",
                "path": str(dest.resolve()),
                "seconds": first_seconds,
                "cache_seconds": round(monotonic() - started, 3),
                "metadata": image_client.artifact_metadata(dest),
            }
        assert not any(
            name in ("hermes_cli", "agent")
            or name.startswith(("hermes_cli.", "agent."))
            for name in sys.modules
        ), "Runtime importou Hermes"
        report["independence"] = {
            "status": "passed",
            "hermes_imported": False,
            "python": sys.executable,
        }
        report["status"] = "passed"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = str(error)
        raise
    finally:
        (args.output / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
