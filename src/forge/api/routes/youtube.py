"""Autorização de um canal do YouTube pela pessoa que iniciou a tentativa."""
import secrets
import time
from dataclasses import dataclass, field
from threading import Event

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from forge.api.routes.sessao import COOKIE, Selecao, conta_atual, exigir_canal, selecionar
from forge.repositories.acesso_canais import AcessoCanais
from forge.services.sessao_studio import digest
from forge.services.youtube import YouTubeAuthError
from forge.services.youtube_auth import ESCOPOS, GoogleCredentials
from forge.services.youtube_canais import ContaYouTube, LoginGoogle

youtube_router = APIRouter()
LEITURA = "https://www.googleapis.com/auth/youtube.readonly"
ANALYTICS = "https://www.googleapis.com/auth/yt-analytics.readonly"


class LoginRequest(BaseModel):
    canal_id: str | None = None
    analytics: bool = False


@dataclass
class Tentativa:
    sessao: str
    prazo: float
    login: LoginGoogle
    prova: str
    navegador: Event = field(default_factory=Event)


def conta_youtube(request: Request) -> ContaYouTube:
    services = request.app.state.services
    if services.youtube is not None:
        return services.youtube
    conta = getattr(request.app.state, "youtube_padrao", None)
    if conta is None:
        conta = ContaYouTube.padrao(services.settings)
        request.app.state.youtube_padrao = conta
    return conta


def canais_da_conta(request: Request):
    services = request.app.state.services
    return AcessoCanais(services.commands.db, conta_atual(request), services.settings)


@youtube_router.get("/canais")
@youtube_router.get("/youtube")
def get_youtube(request: Request):
    return canais_da_conta(request).painel()


@youtube_router.post("/youtube/login", status_code=202)
async def start_login(request: Request, payload: LoginRequest | None = None):
    from starlette.concurrency import run_in_threadpool

    payload = payload or LoginRequest()
    if payload.canal_id:
        exigir_canal(request, payload.canal_id)
    if payload.analytics and not payload.canal_id:
        raise HTTPException(422, "Selecione um canal para habilitar indicadores")
    acesso = canais_da_conta(request)
    conta = conta_youtube(request)
    login = conta.login.nova_tentativa()
    sessao = digest(request.cookies[COOKIE])
    prazo = time.time() + login.PRAZO
    tentativa_id = secrets.token_urlsafe(24)
    prova = secrets.token_urlsafe(32)
    tentativa = Tentativa(sessao, prazo, login, digest(prova))
    retorno = (acesso.settings.studio_public_origin + "/api/youtube/login/" + tentativa_id
               + "/confirmar?prova=" + prova)
    escopos = (*ESCOPOS, LEITURA, *((ANALYTICS,) if payload.analytics else ()))

    def registrar(tmp):
        if not tentativa.navegador.wait(max(0, prazo - time.time())):
            raise YouTubeAuthError("Navegador da sessão não confirmou o retorno")
        canal = conta.canais.identificar(tmp)
        concedidos = GoogleCredentials(tmp, acesso.settings.youtube_client_secrets).escopos()
        if not set(escopos).issubset(concedidos):
            raise YouTubeAuthError("Permissões recusadas")
        acesso.vincular(tmp, canal, concedidos, sessao, payload.canal_id, prazo)
        return canal

    tentativas = request.app.state.tentativas_youtube
    agora = time.time()
    for antiga, item in list(tentativas.items()):
        if item.prazo + 300 <= agora:
            del tentativas[antiga]
    tentativas[tentativa_id] = tentativa
    try:
        estado = await run_in_threadpool(login.iniciar, registrar=registrar, escopos=escopos,
                                         retorno_studio=retorno)
    except YouTubeAuthError as erro:
        tentativas.pop(tentativa_id, None)
        return JSONResponse(status_code=409, content={"error": {"code": erro.codigo,
                            "message": "Cliente OAuth de canal indisponível. Consulte o operador."}})
    return {"tentativa_id": tentativa_id, "login": estado.para_api()}


def _tentativa(request, tentativa_id):
    item = request.app.state.tentativas_youtube.get(tentativa_id)
    if not item or item.sessao != digest(request.cookies[COOKIE]) or item.prazo + 300 <= time.time():
        raise HTTPException(404, "Tentativa indisponível")
    return item


@youtube_router.get("/youtube/login/{tentativa_id}")
async def get_login(request: Request, tentativa_id: str):
    return {"tentativa_id": tentativa_id, "login": _tentativa(request, tentativa_id).login.estado().para_api()}


@youtube_router.get("/youtube/login/{tentativa_id}/confirmar")
async def confirmar(request: Request, tentativa_id: str, prova: str = ""):
    item = _tentativa(request, tentativa_id)
    if (item.prazo <= time.time() or item.navegador.is_set()
            or not secrets.compare_digest(item.prova, digest(prova))):
        raise HTTPException(400, "Retorno de autorização inválido")
    item.navegador.set()
    return PlainTextResponse("Retorno recebido. Feche esta aba e acompanhe o resultado no Studio.")


@youtube_router.post("/youtube/channels/{canal_id}/default")
def set_default(canal_id: str, request: Request):
    selecionar(request, Selecao(canal_id=canal_id))
    return get_youtube(request)


@youtube_router.post("/youtube/channels/{canal_id}/disconnect")
def disconnect(canal_id: str, request: Request):
    acesso = canais_da_conta(request)
    acesso.desconectar(canal_id)
    return acesso.painel()
