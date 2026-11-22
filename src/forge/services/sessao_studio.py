"""Identidade Google e sessões opacas do Studio."""
import hashlib
import secrets
import time

from authlib.integrations.starlette_client import OAuth

DURACAO = 7 * 86400
TENTATIVA = 600


def digest(valor: str) -> str:
    return hashlib.sha256(valor.encode()).hexdigest()


class GoogleOIDC:
    def __init__(self, settings):
        self.cliente = OAuth().register(
            "google", client_id=settings.studio_google_client_id,
            client_secret=settings.studio_google_client_secret.get_secret_value(),
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid profile"},
        )

    async def iniciar(self, callback, state, nonce):
        if not self.cliente.client_id or not self.cliente.client_secret:
            raise ValueError("Cliente web ausente")
        dados = await self.cliente.create_authorization_url(callback, state=state, nonce=nonce)
        return dados["url"]

    async def identificar(self, callback, code, nonce):
        token = await self.cliente.fetch_access_token(redirect_uri=callback, code=code)
        return await self.cliente.parse_id_token(
            token, nonce, claims_options={
                "iss": {"essential": True, "value": "https://accounts.google.com"},
                "aud": {"essential": True, "value": self.cliente.client_id},
            },
        )


class SessaoStudio:
    def __init__(self, db):
        self.db = db

    def tentar(self, retorno):
        state, navegador, nonce = (secrets.token_urlsafe(32) for _ in range(3))
        with self.db.transaction(immediate=True) as conn:
            conn.execute("DELETE FROM tentativas_oidc WHERE expira<=?", (time.time(),))
            conn.execute("INSERT INTO tentativas_oidc VALUES(?,?,?,?,?)",
                         (digest(state), digest(navegador), nonce, retorno, time.time() + TENTATIVA))
        return state, navegador, nonce

    def consumir(self, state, navegador):
        with self.db.transaction(immediate=True) as conn:
            return conn.execute("""DELETE FROM tentativas_oidc
                WHERE state=? AND navegador=? AND expira>? RETURNING nonce,retorno""",
                (digest(state), digest(navegador), time.time())).fetchone()

    def criar(self, conta_id, nome, avatar=None, *, anterior=""):
        chave = secrets.token_urlsafe(32)
        with self.db.transaction(immediate=True) as conn:
            conn.execute("""INSERT INTO contas(id,nome,avatar) VALUES(?,?,?)
                ON CONFLICT(id) DO UPDATE SET nome=excluded.nome, avatar=excluded.avatar""",
                (conta_id, nome, avatar))
            conn.execute("UPDATE sessoes SET revogada=1 WHERE digest=?", (digest(anterior),))
            conn.execute("INSERT INTO sessoes(digest,conta_id,expira) VALUES(?,?,?)",
                         (digest(chave), conta_id, time.time() + DURACAO))
        return chave

    def pessoa(self, chave):
        with self.db.connection() as conn:
            row = conn.execute("""SELECT c.id,c.nome,c.avatar FROM sessoes s
                JOIN contas c ON c.id=s.conta_id WHERE digest=? AND expira>? AND revogada=0""",
                (digest(chave), time.time())).fetchone()
            return dict(row) if row else None

    def sair(self, chave):
        with self.db.transaction(immediate=True) as conn:
            conn.execute("UPDATE sessoes SET revogada=1 WHERE digest=?", (digest(chave),))
