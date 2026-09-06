import argparse
import sys
from pathlib import Path

from forge.gpu.liberadores import montar_broker
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

    args = parser.parse_args(argv)

    return _cmd_roteiro(args)


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

    # O slot cobre o grafo E o plano de mídia: o plano é emitido de propósito
    # com o modelo ainda residente. Sair do `with` é o que descarrega o LLM
    # antes de o TTS ou o SDXL pedirem a placa — sem isso o Qwen fica com ~6 GB
    # ocupados e a fase seguinte aloca numa placa cheia, que é exatamente a OOM
    # que o broker existe para evitar. Com provider na nuvem o LLM não usa VRAM
    # e `montar_broker` já o tira da disputa, então aqui vira no-op.
    with montar_broker(settings).exclusivo("llm"):
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

        _plano_de_midia(model, settings, run_dir, final, aprovado)

    print(str(path))
    print(f"run: {run_dir}", file=sys.stderr)
    return 0


def _plano_de_midia(model, settings, run_dir: Path, final: dict,
                    aprovado: bool | None) -> None:
    """O plano de mídia sai junto do roteiro porque é a última coisa que exige
    LLM: emiti-lo aqui evita recarregar o modelo na fase de GPU.

    Só de roteiro APROVADO (spec D3/S3). O grafo também termina por esgotar
    `max_passos` ou `max_review_rounds`, com `aprovado` False: planejar mídia aí
    gastaria horas de TTS e de SDXL num roteiro que o revisor reprovou.
    """
    from forge.agents.midia import gravar_plano, planejar_midia

    if aprovado is not True:
        logger.info(
            "Plano de mídia pulado: roteiro não aprovado",
            aprovado=aprovado, rounds=final.get("rounds"), passos=final.get("passos"),
        )
        return

    try:
        plano = planejar_midia(
            model, final["roteiro"], alvo_segundos=settings.midia_alvo_segundos
        )
        caminho_midia = gravar_plano(run_dir, plano)
        logger.info("Plano de mídia gravado", path=str(caminho_midia),
                    blocos=len(plano.blocos), beats=len(plano.beats))
    except Exception as e:
        # Roteiro aprovado é o entregável desta etapa; falhar o plano de mídia
        # não pode apagá-lo. `forge video` refaz o plano depois.
        logger.error("Plano de mídia falhou", error=str(e), exc_info=True)
