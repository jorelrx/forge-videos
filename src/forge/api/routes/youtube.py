"""Conta do YouTube pelo painel: cliente OAuth, login e canais conectados."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from forge.api.errors import not_found
from forge.services.youtube import YouTubeError
from forge.services.youtube_canais import ContaYouTube

youtube_router = APIRouter()


class ClienteRequest(BaseModel):
    conteudo: str


def conta_youtube(request: Request) -> ContaYouTube:
    services = request.app.state.services
    if services.youtube is not None:
        return services.youtube
    conta = getattr(request.app.state, "youtube_padrao", None)
    if conta is None:
        conta = ContaYouTube.padrao(services.settings)
        request.app.state.youtube_padrao = conta
    return conta


def _erro(status: int, codigo: str, erro: Exception) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": codigo, "message": str(erro)}})


@youtube_router.get("/youtube")
async def get_youtube(request: Request) -> dict:
    return conta_youtube(request).para_api()


@youtube_router.post("/youtube/client")
async def upload_client(payload: ClienteRequest, request: Request):
    conta = conta_youtube(request)
    try:
        conta.canais.salvar_cliente(payload.conteudo)
    except YouTubeError as erro:
        return _erro(422, "youtube_client_invalid", erro)
    return conta.para_api()


@youtube_router.post("/youtube/login", status_code=202)
async def start_login(request: Request):
    conta = conta_youtube(request)
    try:
        conta.login.iniciar()
    except YouTubeError as erro:
        return _erro(409, erro.codigo, erro)
    return JSONResponse(status_code=202, content=conta.para_api())


@youtube_router.post("/youtube/channels/{canal_id}/default")
async def set_default(canal_id: str, request: Request) -> dict:
    conta = conta_youtube(request)
    try:
        conta.canais.definir_padrao(canal_id)
    except KeyError:
        not_found("canal", canal_id)
    return conta.para_api()


@youtube_router.post("/youtube/channels/{canal_id}/disconnect")
async def disconnect(canal_id: str, request: Request) -> dict:
    conta = conta_youtube(request)
    try:
        conta.canais.desconectar(canal_id)
    except KeyError:
        not_found("canal", canal_id)
    return conta.para_api()
