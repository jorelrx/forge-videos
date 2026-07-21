import argparse
import sys
from pathlib import Path

from forge.infrastructure.config import get_settings
from forge.llms.model import build_chat_model
from forge.infrastructure.logging import setup_logging, get_logger
from forge.orchestration.graph import build_graph
from forge.services.storage import gravar_roteiro

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
    r.add_argument(
        "--retomar",
        default=None,
        help="Diretório de uma run anterior; pula estágios já concluídos",
    )
    args = parser.parse_args(argv)

    logger.info("Starting", command="roteiro", provider=args.provider, tema=args.tema)
    
    settings = get_settings()
    if args.provider is not None:
        settings = settings.model_copy(update={"provider": args.provider})
    setup_logging(settings.log_level)
    model = build_chat_model(settings)
    logger.info("Model built", model=settings.model, provider=settings.provider)

    from forge.services.artefatos import carregar_run, criar_run_dir

    if args.retomar:
        run_dir = Path(args.retomar)
        if not run_dir.is_dir():
            logger.error("Run directory not found", run_dir=str(run_dir))
            sys.exit(1)
        try:
            conteudo, inicio = carregar_run(run_dir)
        except Exception as e:
            # Artefato truncado ou malformado é justamente o cenário que
            # --retomar existe para recuperar; falhar limpo em vez de traceback.
            logger.error("Failed to read run artifacts", run_dir=str(run_dir),
                         error=str(e), exc_info=True)
            sys.exit(1)
        logger.info("Resuming run", run_dir=str(run_dir), inicio=inicio,
                    carregados=sorted(conteudo))
    else:
        run_dir = criar_run_dir(settings, args.tema or "roteiro")
        conteudo, inicio = {"tema": args.tema}, "tema"

    graph = build_graph(model, settings, inicio=inicio)
    estado_inicial = {**conteudo, "rounds": 0, "passos": 0, "run_dir": run_dir}

    logger.info("Starting graph invocation", tema=args.tema, rounds=0)
    try:
        state: dict = dict(estado_inicial)
        for step in graph.stream(estado_inicial):
            node_name = next(iter(step))
            logger.info("Node finished", node=node_name)
            print(f"[{node_name}]", file=sys.stderr)
            state.update(step[node_name])
        final = state
    except Exception as e:
        logger.error("Graph invocation failed", error=str(e), exc_info=True)
        sys.exit(1)

    aprovado = final["review"].aprovado if final.get("review") is not None else None
    path = gravar_roteiro(
        final["roteiro"], settings, rounds=final.get("rounds"), aprovado=aprovado
    )
    logger.info("Completed", output_path=str(path), aprovados=aprovado)
    print(str(path))
    print(f"run: {run_dir}", file=sys.stderr)
    return 0
