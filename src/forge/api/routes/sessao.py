from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from forge.services.sessao_studio import DURACAO, TENTATIVA

sessao_router = APIRouter()
COOKIE = "forge_sessao"
COOKIE_LOGIN = "forge_tentativa"
CALLBACK = "/api/sessao/google/callback"


class Selecao(BaseModel):
    canal_id: str


def _pessoa(request):
    chave = request.cookies.get(COOKIE)
    pessoa = request.app.state.sessoes.pessoa(chave) if chave else None
    if pessoa is None:
        raise HTTPException(401, "Sessão expirada ou ausente")
    return pessoa


def conta_atual(request: Request) -> str:
    return _pessoa(request)["id"]


def exigir_canal(request: Request, canal_id: str) -> str:
    conta_id = conta_atual(request)
    with request.app.state.sessoes.db.connection() as conn:
        row = conn.execute("SELECT 1 FROM acesso_canais WHERE conta_id=? AND canal_id=?",
                           (conta_id, canal_id)).fetchone()
    if not row:
        raise HTTPException(404, "Canal indisponível")
    return canal_id


def canal_unico(request: Request) -> str:
    conta_id = conta_atual(request)
    with request.app.state.sessoes.db.connection() as conn:
        canais = conn.execute("SELECT canal_id FROM acesso_canais WHERE conta_id=? LIMIT 2",
                              (conta_id,)).fetchall()
    if len(canais) != 1:
        raise HTTPException(409, "Selecione o canal da operação")
    return canais[0]["canal_id"]


def _retorno_interno(valor):
    caminho = unquote(valor)
    if (not caminho.startswith("/") or caminho.startswith("//") or "\\" in caminho
            or any(ord(c) < 32 for c in caminho)):
        return "/"
    return valor


def _cookie(resposta, origem, nome, valor, duracao, path="/"):
    resposta.set_cookie(nome, valor, max_age=duracao, httponly=True, samesite="lax",
                        secure=origem.startswith("https://"), path=path)


@sessao_router.get("/sessao")
def sessao(request: Request):
    return _pessoa(request)


@sessao_router.get("/sessao/google")
async def login(request: Request, retorno: str = "/"):
    origem = request.app.state.services.settings.studio_public_origin
    state, navegador, nonce = request.app.state.sessoes.tentar(_retorno_interno(retorno))
    try:
        destino = await request.app.state.oidc.iniciar(origem + CALLBACK, state, nonce)
    except Exception:
        raise HTTPException(503, "Login Google indisponível. Verifique o cliente web do Studio.") from None
    resposta = RedirectResponse(destino, 302)
    _cookie(resposta, origem, COOKIE_LOGIN, navegador, TENTATIVA, CALLBACK)
    return resposta


@sessao_router.get("/sessao/google/callback")
async def callback(request: Request):
    origem = request.app.state.services.settings.studio_public_origin
    params = request.query_params
    estados = params.getlist("state")
    tentativa = (request.app.state.sessoes.consumir(estados[0], request.cookies.get(COOKIE_LOGIN, ""))
                 if len(estados) == 1 else None)
    if not tentativa or "error" in params or len(params.getlist("code")) != 1:
        raise HTTPException(400, "Tentativa de login inválida ou expirada")
    try:
        info = await request.app.state.oidc.identificar(origem + CALLBACK, params["code"], tentativa["nonce"])
        sub = info["sub"]
        if not isinstance(sub, str) or not sub:
            raise ValueError
        token = request.app.state.sessoes.criar(sub, info.get("name") or "Conta Google",
                                                info.get("picture"), anterior=request.cookies.get(COOKIE, ""))
    except Exception:
        raise HTTPException(400, "Falha na validação do login Google") from None
    resposta = RedirectResponse(origem + tentativa["retorno"], 303)
    resposta.delete_cookie(COOKIE_LOGIN, path=CALLBACK)
    _cookie(resposta, origem, COOKIE, token, DURACAO)
    return resposta


@sessao_router.post("/sessao/sair", status_code=204)
def sair(request: Request):
    conta_atual(request)
    request.app.state.sessoes.sair(request.cookies[COOKIE])
    resposta = Response(status_code=204)
    resposta.delete_cookie(COOKIE)
    return resposta


@sessao_router.put("/sessao/canal", status_code=204)
def selecionar(request: Request, payload: Selecao):
    exigir_canal(request, payload.canal_id)
    with request.app.state.sessoes.db.transaction(immediate=True) as conn:
        conn.execute("UPDATE contas SET ultimo_canal_id=? WHERE id=?",
                     (payload.canal_id, conta_atual(request)))
    return Response(status_code=204)
