"""Rotas do rascunho editorial, sob a sessão e o vínculo do Studio."""
from functools import partial

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from forge.api.errors import validation_error
from forge.api.routes.insights import contexto
from forge.domain.board_criativo import Analise, AprovarPauta, Comando, EscolhaFluxo
from forge.domain.fluxo_geracao import FluxoGeracao
from forge.repositories.fluxos_geracao import FluxosGeracaoRepository
from forge.services.control_plane import ControlPlaneService
from forge.services.episodios_board import episodios
from forge.repositories.board_criativo import BoardRepository, ConflitoBoard
from forge.services.board_contexto import ler_contexto
from forge.services.board_criativo import (
    aplicar_comando, executar_analise, expor_board, fluxos_compativeis, pendencias, preparar_analise, validar_fluxo,
)

board_router = APIRouter(prefix="/canais/{canal_id}/board")


def _conflito(erro, tarefas):
    return JSONResponse(status_code=409, background=tarefas, content={
        "error": {"code": "revisao_board", "message": str(erro)},
    })


@board_router.get("")
def get_board(canal_id: str, request: Request, tarefas: BackgroundTasks):
    ctx = contexto(request, canal_id, tarefas)
    board, operacao = BoardRepository(ctx.db, ctx.conta, ctx.canal).ler()
    return expor_board(board, operacao, ler_contexto(ctx), fluxos_compativeis(ctx.db, ctx.canal), episodios(ctx))


@board_router.put("")
def put_board(canal_id: str, comando: Comando, request: Request, tarefas: BackgroundTasks):
    ctx = contexto(request, canal_id, tarefas)
    repo = BoardRepository(ctx.db, ctx.conta, ctx.canal)
    fluxos = fluxos_compativeis(ctx.db, ctx.canal)
    try:
        if isinstance(comando, EscolhaFluxo):
            validar_fluxo(fluxos, comando.fluxo_id)
        board, operacao = repo.alterar(comando.revisao, partial(aplicar_comando, comando=comando))
    except ConflitoBoard as erro:
        return _conflito(erro, tarefas)
    except ValueError as erro:
        validation_error(str(erro))
    return expor_board(board, operacao, ler_contexto(ctx), fluxos, episodios(ctx))


@board_router.post("/analises", status_code=202)
def analisar_board(canal_id: str, pedido: Analise, request: Request, tarefas: BackgroundTasks):
    ctx = contexto(request, canal_id, tarefas)
    repo = BoardRepository(ctx.db, ctx.conta, ctx.canal)
    editorial = ler_contexto(ctx)
    settings = request.app.state.services.settings
    try:
        reserva = repo.reservar(pedido.revisao, pedido.tipo, 1800 + 2 * settings.llm_timeout,
                               partial(preparar_analise, pedido=pedido, editorial=editorial))
    except ConflitoBoard as erro:
        return _conflito(erro, tarefas)
    except ValueError as erro:
        return JSONResponse(status_code=422, background=tarefas, content={
            "error": {"code": "analise_board", "message": str(erro)},
        })
    if reserva is None and pedido.tipo == "conversa":
        # A conversa sempre reserva; None aqui é outra análise em andamento.
        return JSONResponse(status_code=409, background=tarefas, content={
            "error": {"code": "analise_em_andamento",
                      "message": "Aguarde a análise em andamento antes de enviar a mensagem."},
        })
    if reserva:
        dono, entrada = reserva
        tarefas.add_task(executar_analise, repo, dono, pedido, entrada, ctx, editorial, settings,
                         getattr(request.app.state, "modelo_board", None))
    board, operacao = repo.ler()
    return expor_board(board, operacao, editorial, fluxos_compativeis(ctx.db, ctx.canal), episodios(ctx))


def _snapshot_aprovado(fluxo: FluxoGeracao, board, revisao: int, aprovacao_id: str) -> dict:
    return {
        "preset": "local-recomendado-v1",
        "fluxo_geracao": fluxo.model_dump(mode="json"),
        "pauta_aprovada": {"aprovacao_id": aprovacao_id, "revisao": revisao, **board.pauta.model_dump()},
    }


@board_router.post("/aprovacoes", status_code=201)
def aprovar_pauta(canal_id: str, pedido: AprovarPauta, request: Request, tarefas: BackgroundTasks):
    ctx = contexto(request, canal_id, tarefas)
    services = request.app.state.services
    repo = BoardRepository(ctx.db, ctx.conta, ctx.canal)
    fluxos = fluxos_compativeis(ctx.db, ctx.canal)
    fluxo = FluxosGeracaoRepository(ctx.db).obter(pedido.fluxo_id, canal_id=ctx.canal)

    def validar(board):
        validar_fluxo(fluxos, pedido.fluxo_id)
        board.fluxo_id = pedido.fluxo_id
        faltas = pendencias(board, fluxos)
        if faltas:
            raise ValueError(" ".join(item["mensagem"] for item in faltas))

    def criar_run(conn, board, aprovacao_id):
        _, run = ControlPlaneService.enfileirar(
            conn, tema=board.pauta.tema, tese=board.pauta.promessa, priority=50,
            config_snapshot=_snapshot_aprovado(fluxo, board, pedido.revisao, aprovacao_id),
            workflow_version=services.workflow_version, git_commit=services.git_commit, canal_id=ctx.canal,
        )
        return run.id

    try:
        aprovacao, criada = repo.aprovar(pedido.revisao, validar, criar_run)
    except ConflitoBoard as erro:
        return _conflito(erro, tarefas)
    except ValueError as erro:
        validation_error(str(erro))
    board, operacao = repo.ler()
    corpo = {"aprovacao": aprovacao, "run_id": aprovacao["run_id"],
             "board": expor_board(board, operacao, ler_contexto(ctx), fluxos, episodios(ctx))}
    return JSONResponse(status_code=201 if criada else 200, background=tarefas, content=corpo)
