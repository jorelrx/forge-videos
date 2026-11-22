from datetime import date
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Query, Request
from fastapi.responses import JSONResponse

from forge.api.errors import not_found, validation_error
from forge.api.routes.sessao import conta_atual, exigir_canal
from forge.repositories.catalogo_canal import CursorDesatualizado, obter, pagina
from forge.services.catalogo_canal import ContextoCanal
from forge.services.episodios_board import pauta_de_origem
from forge.services.insights_canal import incluir_manuais, periodo

insights_router = APIRouter(prefix="/canais/{canal_id}")


def contexto(request, canal_id, tarefas):
    exigir_canal(request, canal_id)
    services = request.app.state.services
    return ContextoCanal(services.commands.db, services.settings, conta_atual(request),
                         canal_id, tarefas.add_task, clientes=getattr(request.app.state, "clientes_insights", None))


def intervalo(inicio, fim):
    try:
        return periodo(inicio, fim)
    except ValueError as erro:
        validation_error(str(erro))


@insights_router.post("/sincronizacoes", status_code=202)
def sincronizar(request: Request, canal_id: str, tarefas: BackgroundTasks,
                inicio: date | None = None, fim: date | None = None, video_id: str | None = None):
    ctx = contexto(request, canal_id, tarefas)
    datas = intervalo(inicio, fim)
    video = obter(ctx.db, canal_id, video_id) if video_id and ctx.pode_ler() else None
    if video_id and not video:
        not_found("vídeo", video_id)
    estado, _ = ctx.catalogo(forcar=True)
    resultado = ctx.relatorio(*datas, video=video, forcar=True)
    return {"estado_catalogo": estado, "estado": resultado["estado"]}


@insights_router.get("/resumo")
def resumo(request: Request, canal_id: str, tarefas: BackgroundTasks,
           inicio: date | None = None, fim: date | None = None):
    ctx = contexto(request, canal_id, tarefas)
    datas = intervalo(inicio, fim)
    estado, data = ctx.catalogo()
    resultado = ctx.relatorio(*datas)
    with ctx.db.connection() as conn:
        titulos = dict(conn.execute("SELECT video_id, titulo FROM catalogo_canal WHERE canal_id=?", (canal_id,)))
    if estado == "atualizado" and not titulos:
        estado = "canal_vazio"
    resultado["estado_catalogo"] = estado
    resultado["ultima_atualizacao_catalogo"] = data
    resultado["contribuicoes"] = [
        {**item, "titulo": titulos[item["video_id"]]}
        for item in resultado["contribuicoes"] if item["video_id"] in titulos
    ]
    if estado == "canal_vazio" and resultado["estado"] == "sem_dados":
        resultado["estado"] = estado
    return resultado


@insights_router.get("/videos")
def videos(request: Request, canal_id: str, tarefas: BackgroundTasks,
           inicio: date | None = None, fim: date | None = None, busca: str = "",
           publicado_de: date | None = None, publicado_ate: date | None = None,
           ordem: Literal["data", "titulo", "resultado"] = "data", cursor: str | None = None,
           limite: int = Query(default=20, ge=1, le=100)):
    ctx = contexto(request, canal_id, tarefas)
    datas = intervalo(inicio, fim)
    if publicado_de and publicado_ate and publicado_de > publicado_ate:
        validation_error("Intervalo de publicação inválido")
    estado, _ = ctx.catalogo()
    if estado in {"sem_autorizacao", "reconectar"}:
        return {"videos": [], "proximo_cursor": None}
    resultado = ctx.relatorio(*datas)
    views = {r["video_id"]: r["views"] for r in resultado["contribuicoes"]}
    try:
        return pagina(ctx.db, canal_id, list(map(str, datas)), views, busca, publicado_de,
                      publicado_ate, ordem, cursor, limite)
    except CursorDesatualizado:
        return JSONResponse(status_code=409, background=tarefas, content={
            "error": {"code": "cursor_desatualizado", "message": "Os resultados foram atualizados."},
        })
    except ValueError as erro:
        validation_error(str(erro))


@insights_router.get("/videos/{video_id}")
def video(request: Request, canal_id: str, video_id: str, tarefas: BackgroundTasks,
          inicio: date | None = None, fim: date | None = None):
    ctx = contexto(request, canal_id, tarefas)
    datas = intervalo(inicio, fim)
    estado, data = ctx.catalogo()
    item = obter(ctx.db, canal_id, video_id) if estado not in {"sem_autorizacao", "reconectar"} else None
    if not item and data is None and estado == "sincronizando":
        return JSONResponse(status_code=503, headers={"Retry-After": "3"}, background=tarefas,
                            content={"error": {"code": "catalogo_pendente",
                                               "message": "Aguardando a primeira leitura do catálogo."}})
    if not item:
        not_found("vídeo", video_id)
    resultado = ctx.relatorio(*datas, video=item)
    item["views"] = resultado["views"]
    incluir_manuais(resultado, item, ctx.raiz, canal_id)
    return {**resultado, "video": item, "episodio_board": pauta_de_origem(ctx, item.get("run_id"))}
