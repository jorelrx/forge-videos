import argparse
import sys

from forge.config import get_settings
from forge.llm.model import build_chat_model
from forge.logging import setup_logging, get_logger
from forge.orchestrator.graph import build_graph
from forge.output.storage import gravar_roteiro

logger = get_logger("forge.cli")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="forge")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("roteiro", help="Gera um roteiro de vídeo")
    r.add_argument("--tema", default=None, help="Tema (opcional; gerado se ausente)")
    r.add_argument(
        "--provider",
        choices=["anthropic", "lm-studio", "openai"],
        default=None,
        help="Provider do LLM (default: config/env, senão anthropic)",
    )
    args = parser.parse_args(argv)

    logger.info("Starting", command="roteiro", provider=args.provider, tema=args.tema)
    
    settings = get_settings()
    if args.provider is not None:
        settings = settings.model_copy(update={"provider": args.provider})
    setup_logging(settings.log_level)
    model = build_chat_model(settings)
    logger.info("Model built", model=settings.model, provider=settings.provider)
    graph = build_graph(model, settings)

    logger.info("Starting graph invocation", tema=args.tema, rounds=0)
    try:
        final = graph.invoke({"tema": args.tema, "rounds": 0})
    except Exception as e:
        logger.error("Graph invocation failed", error=str(e), exc_info=True)
        sys.exit(1)
    
    aprovado = final["review"].aprovado if final.get("review") is not None else None
    path = gravar_roteiro(
        final["roteiro"], settings, rounds=final.get("rounds"), aprovado=aprovado
    )
    logger.info("Completed", output_path=str(path), aprovados=aprovado)
    print(str(path))
    return 0
