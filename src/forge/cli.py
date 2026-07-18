import argparse

from forge.config import get_settings
from forge.llm.model import build_chat_model
from forge.logging import setup_logging
from forge.orchestrator.graph import build_graph
from forge.output.storage import gravar_roteiro


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="forge")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("roteiro", help="Gera um roteiro de vídeo")
    r.add_argument("--tema", default=None, help="Tema (opcional; gerado se ausente)")
    args = parser.parse_args(argv)

    settings = get_settings()
    setup_logging(settings.log_level)
    model = build_chat_model(settings)
    graph = build_graph(model, settings)

    final = graph.invoke({"tema": args.tema, "rounds": 0})
    path = gravar_roteiro(final["roteiro"], settings, rounds=final.get("rounds"))
    print(path)
    return 0
