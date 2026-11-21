import argparse
import json
import sys
from contextlib import nullcontext
from pathlib import Path

from forge.domain.fluxo_geracao import FLUXOS_INICIAIS, FLUXO_PADRAO, FluxoGeracao
from forge.gpu.broker import GPUOcupada
from forge.gpu.liberadores import montar_broker
from typing import get_args

from forge.infrastructure.config import Provider, get_settings
from forge.infrastructure.logging import get_logger, setup_logging
from forge.llms.model import build_chat_model, build_review_model
from forge.orchestration.graph import build_graph
from forge.repositories.connection import Database
from forge.repositories.fluxos_geracao import FluxosGeracaoRepository
from forge.services.persistencia import carregar_modelo, gravar_modelo
from forge.services.storage import gravar_roteiro

logger = get_logger("forge.cli")
ARQUIVO_FLUXO = "fluxo-geracao.json"


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
        "--fluxo",
        help="ID do fluxo: padrao, comentarios, gancho-inicial ou um ID do Studio",
    )
    r.add_argument(
        "--provider",
        choices=list(get_args(Provider)),
        default=None,
        help="Provider do LLM (default: config/env, senão anthropic)",
    )
    r.add_argument(
        "--retomar",
        default=None,
        help="Diretório de uma run anterior; pula estágios já concluídos",
    )

    t = sub.add_parser("temas", help="Sugere temas que o acervo sustenta")
    t.add_argument("--n", type=int, default=5, help="Quantos temas sugerir")
    t.add_argument(
        "--provider",
        choices=list(get_args(Provider)),
        default=None,
        help="Provider do LLM (default: config/env, senão anthropic)",
    )

    auth = sub.add_parser("auth", help="Autenticação independente do Forge")
    auth.add_argument("backend", choices=["codex", "youtube"])
    auth.add_argument("action", choices=["login", "status"])

    p = sub.add_parser("publicar", help="Envia uma run aprovada ao YouTube (privado ou agendado)")
    p.add_argument("run_dir", help="Diretório da run (output/runs/<id>)")
    p.add_argument("--titulo", default=None,
                   help="Número do título da embalagem (1, 2, 3) ou o texto do título")
    p.add_argument("--canal", default=None,
                   help="Id do canal (UC...) conectado; sem ele, usa o canal padrão")
    p.add_argument("--agendar", default=None,
                   help="Data ISO 8601 com fuso, ex. 2026-11-21T18:00-03:00; sem ela, fica privado")
    args = parser.parse_args(argv)

    if args.cmd == "auth" and args.backend == "youtube":
        return _cmd_auth_youtube(args)

    if args.cmd == "publicar":
        return _cmd_publicar(args)

    if args.cmd == "auth":
        from forge.services.codex_auth import OAuthCredentials, CodexAuthError
        credentials = OAuthCredentials(get_settings().codex_auth_file)
        try:
            if args.action == "login":
                print("Autorize sua conta ChatGPT no navegador. Callback local: porta 1455.")
                credentials.login(show_url=lambda url: print("Login OAuth: " + url))
            else:
                credentials.access_token()
            print("Sessão ChatGPT disponível; nenhum token exibido.")
            return 0
        except CodexAuthError as error:
            print(str(error), file=sys.stderr)
            return 1

    if args.cmd == "temas":
        return _cmd_temas(args)

    return _cmd_roteiro(args)


def _cmd_auth_youtube(args) -> int:
    import secrets

    from forge.services.youtube import YouTubeError
    from forge.services.youtube_auth import GoogleCredentials
    from forge.services.youtube_canais import CanaisYouTube
    settings = get_settings()
    canais = CanaisYouTube(settings)
    try:
        if args.action == "login":
            print("Autorize sua conta Google no navegador e escolha o canal do YouTube.")
            canais.dir.mkdir(parents=True, exist_ok=True)
            temporario = canais.dir / f".login-{secrets.token_hex(8)}.json"
            try:
                GoogleCredentials(temporario, settings.youtube_client_secrets).login(
                    show_url=lambda url: print("Login OAuth: " + url))
                canal = canais.registrar(temporario)
            finally:
                temporario.unlink(missing_ok=True)
            print(f"Canal conectado e definido como padrão: {canal.titulo} ({canal.id})")
            return 0
        conectados = canais.listar()
        if not conectados:
            raise YouTubeError("Nenhum canal do YouTube conectado; execute forge auth youtube login")
        for canal in conectados:
            canais.credenciais(canal.id).access_token()  # renova ou acusa login vencido
            print(f"{canal.titulo} ({canal.id})" + (" [padrão]" if canal.padrao else ""))
        return 0
    except YouTubeError as erro:
        print(str(erro), file=sys.stderr)
        return 1


def _titulo_pedido(run_dir: Path, valor: str | None) -> str | None:
    if valor is None or not valor.strip().isdigit():
        return valor
    from forge.domain.embalagem import Embalagem
    from forge.services.youtube import YouTubeError
    try:
        embalagem = Embalagem.model_validate_json(
            (run_dir / "video" / "embalagem.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as erro:
        raise YouTubeError("Run sem embalagem válida para escolher o título") from erro
    indice = int(valor)
    if not 1 <= indice <= len(embalagem.titulos):
        raise YouTubeError(
            f"Título {indice} não existe; a embalagem tem {len(embalagem.titulos)}")
    return embalagem.titulos[indice - 1].texto


def _cmd_publicar(args) -> int:
    from datetime import datetime

    from forge.services import publicacao
    from forge.services.youtube import YouTubeClient, YouTubeError
    settings = get_settings()
    run_dir = Path(args.run_dir)
    try:
        titulo = _titulo_pedido(run_dir, args.titulo)
        try:
            quando = datetime.fromisoformat(args.agendar) if args.agendar else None
        except ValueError as erro:
            raise YouTubeError(f"Data de agendamento inválida: {args.agendar}") from erro
        from forge.services.youtube_canais import CanaisYouTube
        canais = CanaisYouTube(settings)
        if not canais.listar():
            raise YouTubeError("Nenhum canal do YouTube conectado; execute forge auth youtube login")
        # O que já subiu pertence ao canal gravado; o pedido só vale do zero.
        canal = publicacao.canal_da_retomada(run_dir) or args.canal or canais.padrao()
        try:
            cliente = YouTubeClient(canais.credenciais(canal).access_token)
        except KeyError:
            raise YouTubeError(f"Canal {canal} não está conectado; rode forge auth youtube status") from None

        def progresso(estado):
            if estado.etapa == "enviando" and estado.total_bytes:
                pct = 100 * estado.bytes_enviados / estado.total_bytes
                print(f"[publicar] enviando {pct:.0f}%", file=sys.stderr)
            else:
                print(f"[publicar] {estado.etapa}", file=sys.stderr)

        estado = publicacao.publicar(run_dir, cliente=cliente, settings=settings,
                                     titulo=titulo, publicar_em=quando, ao_progredir=progresso,
                                     canal_id=canal, canal_titulo=canais.titulo(canal))
    except YouTubeError as erro:
        print(str(erro), file=sys.stderr)
        return 1
    for aviso in estado.avisos:
        print(f"aviso: {aviso}", file=sys.stderr)
    print(estado.url)
    return 0


def _cmd_temas(args) -> int:
    """Lista temas sustentados pelo acervo, do mais atraente para o menos.

    Os temas vão para stdout (dá para colar no dashboard ou encadear num
    script); os eixos sem cobertura vão para stderr — são um recado sobre o
    acervo, não parte da lista.
    """
    from forge.agents import tema as tema_stage
    from forge.services.acervo import Acervo, AcervoIndisponivel

    settings = get_settings()
    if args.provider is not None:
        settings = settings.model_copy(update={"provider": args.provider})
    setup_logging(settings.log_level)
    model = build_chat_model(settings)
    acervo = Acervo(settings.acervo_url, timeout=settings.acervo_timeout)
    try:
        sugestoes = tema_stage.sugerir_temas(model, acervo, settings, n=args.n)
    except AcervoIndisponivel as erro:
        print(str(erro), file=sys.stderr)
        return 1

    for posicao, tema in enumerate(sugestoes.temas, start=1):
        print(
            f"{posicao}. {tema.tema} [{tema.eixo}] apelo {tema.apelo}/5 — "
            + "; ".join(tema.livros)
        )
    if sugestoes.eixos_sem_cobertura:
        print(
            "Eixos sem cobertura no acervo: " + ", ".join(sugestoes.eixos_sem_cobertura),
            file=sys.stderr,
        )
    if not sugestoes.temas:
        print("Nenhum tema sustentado pelo acervo.", file=sys.stderr)
        return 1
    return 0


def _selecionar_fluxo(settings, fluxo_id: str | None) -> FluxoGeracao | None:
    if fluxo_id is None or fluxo_id == FLUXO_PADRAO:
        return None
    for fluxo in FLUXOS_INICIAIS:
        if fluxo.id == fluxo_id:
            return fluxo
    if settings.studio_db_path.is_file():
        from forge.repositories.schema import init_db

        db = Database(settings.studio_db_path)
        init_db(db)
        fluxo = FluxosGeracaoRepository(db).obter(fluxo_id)
        if fluxo is not None:
            return fluxo
    raise ValueError(f"Fluxo de geração desconhecido: {fluxo_id}")


def _cmd_roteiro(args) -> int:
    logger.info("Starting", command="roteiro", provider=args.provider, tema=args.tema)

    settings = get_settings()
    if args.provider is not None:
        settings = settings.model_copy(update={"provider": args.provider})
    setup_logging(settings.log_level)
    from forge.services.artefatos import carregar_run, criar_run_dir

    fluxo = None
    if args.retomar:
        run_dir = Path(args.retomar)
        if not run_dir.is_dir():
            logger.error("Run directory not found", run_dir=str(run_dir))
            sys.exit(1)
        try:
            fluxo_path = run_dir / ARQUIVO_FLUXO
            if fluxo_path.is_file():
                fluxo = carregar_modelo(fluxo_path, FluxoGeracao)
            fluxo_salvo = fluxo.id if fluxo is not None else FLUXO_PADRAO
            if args.fluxo is not None and args.fluxo != fluxo_salvo:
                raise ValueError(f"Esta execução usa o fluxo '{fluxo_salvo}'.")
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
        try:
            fluxo = _selecionar_fluxo(settings, args.fluxo)
        except ValueError as e:
            logger.error("Fluxo de geração inválido", error=str(e))
            return 1

    model = build_chat_model(settings)
    logger.info("Model built", model=settings.resolved_model, provider=settings.provider)

    if not args.retomar:
        run_dir = criar_run_dir(settings, args.tema or "roteiro")
        if fluxo is not None:
            gravar_modelo(run_dir / ARQUIVO_FLUXO, fluxo)
        conteudo, inicio = {"tema": args.tema}, "tema"

    revisor = build_review_model(settings)
    extra = {"revisor": revisor} if revisor is not None else {}
    if fluxo is not None:
        extra["fluxo_geracao"] = fluxo
    graph = build_graph(model, settings, inicio=inicio, **extra)
    estado_inicial = {**conteudo, "rounds": 0, "passos": 0, "run_dir": run_dir}

    # O slot cobre o grafo E o plano de mídia: o plano é emitido de propósito
    # com o modelo ainda residente. Sair do `with` é o que descarrega o LLM
    # antes de o TTS ou o SDXL pedirem a placa — sem isso o Qwen fica com ~6 GB
    # ocupados e a fase seguinte aloca numa placa cheia, que é exatamente a OOM
    # que o broker existe para evitar. Com provider na nuvem o LLM não usa VRAM
    # e `montar_broker` já o tira da disputa, então aqui vira no-op.
    #
    # Com lm-studio local: o LLM também não usa VRAM diretamente — roda via HTTP.
    # O broker faz retry sobre um FileLock POSIX que, no Windows, vira ghost
    # lock quando o processo morre (crash do LM Studio). Pular o broker para
    # lm-studio elimina a fonte desse ghost lock.
    try:
        if settings.provider == "lm-studio":
            logger.info("GPU lock skipped: lm-studio provider runs LLM via HTTP, not VRAM")
            slot_llm = nullcontext()
        else:
            slot_llm = montar_broker(settings).exclusivo("llm")

        with slot_llm:
            result = _executar_grafo(model, settings, graph, estado_inicial)
            aprovado = (
                result["review"].aprovado if result.get("review") is not None else None
            )
            path = gravar_roteiro(
                result["roteiro"], settings, rounds=result.get("rounds"), aprovado=aprovado
            )
            logger.info("Completed", output_path=str(path), aprovados=aprovado)

            _plano_de_midia(model, settings, run_dir, result, aprovado)
            _embalagem(model, settings, run_dir, result, aprovado)
    except GPUOcupada as e:
        # Outro forge segurando a placa é o caso NORMAL que o lock existe para
        # produzir, não um bug: sai como os demais erros previstos deste comando
        # (diretório de --retomar inexistente, artefato ilegível, grafo que
        # estoura) em vez de traceback. Só GPUOcupada — bug de verdade continua
        # aparecendo inteiro.
        logger.error("GPU ocupada por outro processo", error=str(e))
        sys.exit(1)
    except SystemExit:
        raise
    except Exception as e:
        logger.error("Pipeline failed", error=str(e), exc_info=True)
        sys.exit(1)

    print(str(path))
    print(f"run: {run_dir}", file=sys.stderr)
    return 0


def _executar_grafo(model, settings, graph, estado_inicial: dict) -> dict:
    """Executa o grafo LangGraph e retorna o state final."""
    logger.info("Starting graph invocation", tema=estado_inicial.get("tema"), rounds=0)
    state: dict = dict(estado_inicial)
    try:
        for step in graph.stream(estado_inicial):
            node_name = next(iter(step))
            logger.info("Node finished", node=node_name)
            print(f"[{node_name}]", file=sys.stderr)
            state.update(step[node_name])
        return state
    except Exception as e:
        logger.error("Graph invocation failed", error=str(e), exc_info=True)
        # Tenta salvar o que foi produzido ate agora
        _salvar_parcial(state, estado_inicial.get("run_dir"))
        raise


def _salvar_parcial(state: dict, run_dir: Path) -> None:
    """Salva o que foi produzido ate agora em caso de crash."""
    if run_dir is None:
        return
    partial_path = run_dir / "parcial.json"
    dados = {
        "tema": state.get("tema"),
        "research_notes": state.get("research_notes", "")[:2000],
        "fontes_count": len(state.get("fontes", [])),
        "tese": state.get("tese", ""),
        "roteiro_secoes": len(state["roteiro"].secoes) if state.get("roteiro") else 0,
        "review_aprovado": state.get("review", {}).aprovado if state.get("review") else None,
        "rounds": state.get("rounds", 0),
        "passos": state.get("passos", 0),
    }
    try:
        partial_path.write_text(
            json.dumps(dados, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        logger.info("Partial state saved", path=str(partial_path))
    except Exception:
        pass


def _embalagem(model, settings, run_dir: Path, final: dict,
               aprovado: bool | None) -> None:
    """Citações e embalagem de publicação, só de roteiro APROVADO.

    Sai junto do plano de mídia pelo mesmo motivo: é chamada de modelo, e o
    modelo ainda está residente. Como lá, nenhuma falha aqui derruba o comando —
    o roteiro aprovado é o entregável e a embalagem pode ser refeita.
    """
    from forge.agents import embalagem as embalagem_mod
    from forge.services.citacoes import derivar_citacoes, gravar_citacoes

    if aprovado is not True:
        logger.info("Embalagem pulada: roteiro não aprovado", aprovado=aprovado)
        return

    try:
        citacoes = derivar_citacoes(
            final["roteiro"], final.get("research_passages") or []
        )
        gravar_citacoes(run_dir, citacoes)
        embalagem = embalagem_mod.embalar(
            model, final["roteiro"], citacoes,
            aviso_ia=settings.aviso_ia, run_dir=run_dir,
        )
        _, legivel = embalagem_mod.gravar_embalagem(run_dir, embalagem)
        logger.info("Embalagem gravada", path=str(legivel), fontes=len(embalagem.fontes))
    except embalagem_mod.EmbalagemReprovada as e:
        # O modelo errou o formato duas vezes (título longo, capítulo curto) ou
        # o roteiro não tem fonte rastreável. Retentar pode resolver o primeiro
        # caso, nunca o segundo.
        logger.error(
            "Embalagem reprovada no gate", achados=sorted(e.report.codes),
            retentar="descricao_sem_fontes" not in e.report.codes,
        )
    except Exception as e:
        logger.error("Embalagem falhou", error=str(e), exc_info=True, retentar=True)


def _plano_de_midia(model, settings, run_dir: Path, final: dict,
                    aprovado: bool | None) -> None:
    """O plano de mídia sai junto do roteiro porque é a última coisa que exige
    LLM: emiti-lo aqui evita recarregar o modelo na fase de GPU.

    So de roteiro APROVADO (spec D3/S3). O grafo também termina por esgotar
    `max_passos` ou `max_review_rounds`, com `aprovado` False: planejar mídia aí
    gastaria horas de TTS e de SDXL num roteiro que o revisor reprovou.
    """
    from forge.agents.midia import (
        CoberturaInsuficiente,
        PlanoJaExiste,
        gravar_plano,
        planejar_midia,
    )

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
    # Os três braços abaixo existem porque o laço não vigiado precisa distinguir
    # o que adianta retentar do que não adianta. Todos deixam o `forge roteiro`
    # sair 0 com o roteiro entregue: o roteiro aprovado é o entregável desta
    # etapa e falhar o plano de mídia não pode apagá-lo.
    except CoberturaInsuficiente as e:
        # DETERMINISTICO: `fatiar` é puro e o roteiro já está congelado em
        # disco, então a segunda tentativa falha exatamente igual à primeira,
        # para sempre. O retry-com-teto de S9 queimaria o orçamento inteiro
        # aqui. O conserto é no roteiro ou no fatiador, por uma pessoa.
        logger.error(
            "Plano de mídia falhou: cobertura insuficiente",
            error=str(e), deterministico=True, retentar=False,
        )
    except PlanoJaExiste as e:
        # Não é erro: a run já tem plano e sobrescrevê-lo renumeraria os blocos,
        # descartando áudio e imagem já gerados. Em ERROR isso poluiria o log do
        # laço e esconderia as falhas de verdade.
        logger.info("Plano de mídia já existe; o plano em disco foi mantido",
                    detalhe=str(e))
    except Exception as e:
        # Timeout, `Model unloaded by user`, provider fora do ar: TRANSITORIO,
        # vale retentar. `forge video` refaz o plano depois.
        logger.error("Plano de mídia falhou", error=str(e), exc_info=True,
                     retentar=True)
