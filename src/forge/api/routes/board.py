"""Rotas do rascunho editorial, sob a sessão e o vínculo do Studio."""
from functools import partial

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from forge.api.errors import validation_error
from forge.api.routes.insights import contexto
from forge.domain.board_criativo import Analise, Comando
from forge.repositories.board_criativo import BoardRepository, ConflitoBoard
from forge.services.board_contexto import ler_contexto
from forge.services.board_criativo import aplicar_comando, executar_analise, expor_board, preparar_analise

board_router = APIRouter(prefix="/canais/{canal_id}/board")


def _conflito(erro, tarefas):
    return JSONResponse(status_code=409, background=tarefas, content={
        "error": {"code": "revisao_board", "message": str(erro)},
    })


@board_router.get("")
def get_board(canal_id: str, request: Request, tarefas: BackgroundTasks):
    ctx = contexto(request, canal_id, tarefas)
    board, operacao = BoardRepository(ctx.db, ctx.conta, ctx.canal).ler()
    return expor_board(board, operacao, ler_contexto(ctx))


@board_router.put("")
def put_board(canal_id: str, comando: Comando, request: Request, tarefas: BackgroundTasks):
    ctx = contexto(request, canal_id, tarefas)
    repo = BoardRepository(ctx.db, ctx.conta, ctx.canal)
    try:
        board, operacao = repo.alterar(comando.revisao, partial(aplicar_comando, comando=comando))
    except ConflitoBoard as erro:
        return _conflito(erro, tarefas)
    except ValueError as erro:
        validation_error(str(erro))
    return expor_board(board, operacao, ler_contexto(ctx))


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
    if reserva:
        dono, entrada = reserva
        tarefas.add_task(executar_analise, repo, dono, pedido, entrada, ctx, editorial, settings,
                         getattr(request.app.state, "modelo_board", None))
    board, operacao = repo.ler()
    return expor_board(board, operacao, editorial)
