"""Publicação de uma run no YouTube: estado e disparo.

O upload roda em segundo plano (`Publicador`); o painel acompanha pelo GET.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from forge.api.acesso import autorizar_producao, canal_da_run
from fastapi import Depends, APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from forge.api.errors import not_found, transition_error
from forge.domain.operacao import RunStatus
from forge.services.desempenho import Medicao, ler_desempenho, salvar_medicao
from forge.services.publicacao import Publicador, ler_estado
from forge.services.youtube import YouTubeAuthError, YouTubeError

publication_router = APIRouter(dependencies=[Depends(autorizar_producao)])

# Id de run vira caminho em disco: só o alfabeto dos ids, nunca ".." ou "/".
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class PublishRequest(BaseModel):
    titulo: str | None = None
    publicar_em: datetime | None = None
    canal_id: str | None = None


def _publicador(request: Request) -> Publicador:
    services = request.app.state.services
    if services.publicador is not None:
        return services.publicador
    publicador = getattr(request.app.state, "publicador_padrao", None)
    if publicador is None:
        from forge.api.routes.youtube import conta_youtube
        publicador = Publicador(services.settings, canais=conta_youtube(request).canais)
        request.app.state.publicador_padrao = publicador
    return publicador


def _run_dir(request: Request, run_id: str) -> Path:
    raiz = Path(request.app.state.services.settings.studio_runs_dir)
    if not _RUN_ID.match(run_id) or run_id.strip(".") == "":
        not_found("run", run_id)
    run_dir = raiz / run_id
    if not run_dir.is_dir():
        not_found("run", run_id)
    return run_dir


def _canais(request: Request):
    if request.app.state.services.publicador is not None:
        return request.app.state.services.publicador.canais
    from forge.api.routes.youtube import canais_da_conta
    return canais_da_conta(request)


def _visao(request: Request, publicador: Publicador, run_dir: Path) -> dict:
    estado = ler_estado(run_dir)
    canal = canal_da_run(request, run_dir.name)
    if estado and estado.canal_id and estado.canal_id != canal:
        not_found("run", run_dir.name)
    canais = _canais(request)
    return {
        "estado": estado.para_api() if estado is not None else None,
        "em_andamento": publicador.em_andamento(run_dir),
        "conectado": any(getattr(item, "id", item) == canal for item in canais.listar()),
    }


@publication_router.get("/runs/{run_id}/publication")
async def get_publication(run_id: str, request: Request) -> dict:
    return _visao(request, _publicador(request), _run_dir(request, run_id))


@publication_router.post("/runs/{run_id}/publication", status_code=202)
async def publish(run_id: str, payload: PublishRequest, request: Request):
    run_dir = _run_dir(request, run_id)
    canal = canal_da_run(request, run_id)
    estado = ler_estado(run_dir)
    if (payload.canal_id and payload.canal_id != canal) or (estado and estado.canal_id and estado.canal_id != canal):
        not_found("canal", payload.canal_id or canal)
    try:
        run = request.app.state.services.commands.get_run(run_id).run
    except KeyError:
        run = None
    if run and run.config_snapshot.get("revisao_editorial") and run.status is not RunStatus.COMPLETED:
        transition_error("Conclua a revisão editorial e a validação antes de publicar")
    publicador = _publicador(request)
    try:
        publicador.iniciar(run_dir, titulo=payload.titulo, publicar_em=payload.publicar_em,
                           canal_id=canal, canais=_canais(request))
    except YouTubeError as erro:
        # Envelope no topo, como os handlers de app.py; o painel decide pelo código.
        codigo = "youtube_auth_missing" if isinstance(erro, YouTubeAuthError) else erro.codigo
        return JSONResponse(status_code=409, content={
            "error": {"code": codigo, "message": str(erro)}})
    return JSONResponse(status_code=202, content=_visao(request, publicador, run_dir))


def _publicacao_concluida(run_dir):
    estado = ler_estado(run_dir)
    if estado is None or estado.etapa != "concluida" or not estado.video_id:
        transition_error("A execução ainda não tem um vídeo enviado ao YouTube")
    return estado


@publication_router.get("/runs/{run_id}/desempenho")
def get_performance(run_id: str, request: Request) -> dict:
    run_dir = _run_dir(request, run_id)
    return ler_desempenho(run_dir, _publicacao_concluida(run_dir)).para_api()


@publication_router.put("/runs/{run_id}/desempenho")
def save_performance(run_id: str, payload: Medicao, request: Request) -> dict:
    run_dir = _run_dir(request, run_id)
    return salvar_medicao(run_dir, _publicacao_concluida(run_dir), payload).para_api()
