import argparse
import sys
from pathlib import Path

from forge.infrastructure.config import get_settings
from forge.llms.model import build_chat_model
from forge.infrastructure.logging import setup_logging, get_logger
from forge.orchestration.graph import build_graph
from forge.services.storage import gravar_roteiro

logger = get_logger("forge.cli")


def _forcar_stdout_utf8() -> None:
    """Emite UTF-8 no stdout/stderr independente do codepage do console.

    No Windows o console default é cp1252: texto acentuado da base (UTF-8) sai
    como mojibake (`exist�ncia`) mesmo com os dados íntegros. Reconfigurar os
    streams para UTF-8 resolve a exibição sem tocar nos dados.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfig = getattr(stream, "reconfigure", None)
        if reconfig is not None:
            reconfig(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _forcar_stdout_utf8()
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

    ing = sub.add_parser("ingest", help="Ingere livros/textos na base de conhecimento")
    ing.add_argument("--path", default=None, help="Arquivo de livro ou diretório")
    ing.add_argument("--status", action="store_true", help="Conta o que já está indexado")
    ing.add_argument(
        "--source",
        choices=["gutenberg", "internet_archive", "wikisource", "sep", "all"],
        default=None,
        help="Busca por tema numa fonte remota (ou 'all')",
    )
    ing.add_argument("--query", default=None, help="Tema para a busca remota")
    ing.add_argument("--limite", type=int, default=None, help="Máximo de obras NOVAS por fonte")

    ing.add_argument(
        "--reset",
        action="store_true",
        help="APAGA todos os dados dos três stores e recria o schema",
    )
    ing.add_argument(
        "--sim",
        action="store_true",
        help="Pula a confirmação de --reset (para automação)",
    )

    args = parser.parse_args(argv)

    if args.cmd == "ingest":
        return _cmd_ingest(args)
    return _cmd_roteiro(args)


def _confirmar_reset() -> bool:
    """Confirmação interativa de operação destrutiva.

    --reset apaga Postgres, Qdrant e Neo4j de forma irreversível. Exige que o
    usuário digite a palavra, para que não seja acionado por engano.
    """
    print("--reset APAGA todos os dados de Postgres, Qdrant e Neo4j.")
    print("Esta ação é irreversível.")
    try:
        resposta = input("Digite 'apagar' para confirmar: ")
    except EOFError:
        return False
    return resposta.strip().lower() == "apagar"


def _cmd_ingest(args) -> int:
    from forge.knowledge.ingest import _montar, ingerir_caminho

    settings = get_settings()
    setup_logging(settings.log_level)

    if args.reset:
        from forge.knowledge.ingest import resetar_stores

        if not args.sim and not _confirmar_reset():
            logger.warning("Reset cancelado pelo usuário")
            print("cancelado")
            return 1
        try:
            resetar_stores(settings)
        except Exception as e:
            logger.error("Reset falhou", error=str(e), exc_info=True)
            return 1
        print("stores resetados")
        if not args.path and not args.source and not args.status:
            return 0

    if args.source:
        if not args.query:
            logger.error("--source exige --query")
            return 1
        from forge.knowledge.ingest import ingerir_busca_remota

        try:
            total = ingerir_busca_remota(
                [args.source], args.query, settings, limite=args.limite,
            )
        except Exception as e:
            logger.error("Busca remota falhou", error=str(e), exc_info=True)
            return 1
        logger.info("Ingest remoto completo", chunks=total)
        print(f"chunks indexados: {total}")
        return 0

    if args.status:
        _, stores = _montar(settings)
        print(f"qdrant vetores: {stores.vector.contar()}")
        print(f"postgres chunks: {stores.catalog.contar_chunks()}")
        print(f"neo4j entidades: {stores.graph.contar_entidades()}")
        return 0

    if not args.path:
        logger.error("ingest exige --path ou --status")
        return 1
    try:
        total = ingerir_caminho(Path(args.path), settings)
    except Exception as e:
        logger.error("Ingestão falhou", error=str(e), exc_info=True)
        return 1
    logger.info("Ingest completed", chunks=total)
    print(f"chunks indexados: {total}")
    return 0


def _cmd_roteiro(args) -> int:
    logger.info("Starting", command="roteiro", provider=args.provider, tema=args.tema)

    settings = get_settings()
    if args.provider is not None:
        settings = settings.model_copy(update={"provider": args.provider})
    setup_logging(settings.log_level)
    model = build_chat_model(settings)
    logger.info("Model built", model=settings.resolved_model, provider=settings.provider)

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
