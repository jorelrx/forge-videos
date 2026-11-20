"""Publicação de uma run no YouTube: estado e disparo.

O upload roda em segundo plano (`Publicador`); o painel acompanha pelo GET.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from forge.api.errors import not_found
from forge.services.publicacao import Publicador, ler_estado
from forge.services.youtube import YouTubeAuthError, YouTubeError

publication_router = APIRouter()

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


def _visao(publicador: Publicador, run_dir: Path) -> dict:
    estado = ler_estado(run_dir)
    return {
        "estado": estado.para_api() if estado is not None else None,
        "em_andamento": publicador.em_andamento(run_dir),
        "conectado": publicador.conectado(),
    }


@publication_router.get("/runs/{run_id}/publication")
async def get_publication(run_id: str, request: Request) -> dict:
    return _visao(_publicador(request), _run_dir(request, run_id))


@publication_router.post("/runs/{run_id}/publication", status_code=202)
async def publish(run_id: str, payload: PublishRequest, request: Request):
    publicador = _publicador(request)
    run_dir = _run_dir(request, run_id)
    try:
        publicador.iniciar(run_dir, titulo=payload.titulo, publicar_em=payload.publicar_em,
                           canal_id=payload.canal_id)
    except YouTubeError as erro:
        # Envelope no topo, como os handlers de app.py; o painel decide pelo código.
        codigo = "youtube_auth_missing" if isinstance(erro, YouTubeAuthError) else erro.codigo
        return JSONResponse(status_code=409, content={
            "error": {"code": codigo, "message": str(erro)}})
    return JSONResponse(status_code=202, content=_visao(publicador, run_dir))
