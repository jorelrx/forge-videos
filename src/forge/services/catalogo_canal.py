from functools import partial
from pathlib import Path

from forge.repositories.catalogo_canal import confirmar
from forge.repositories.observacoes_canal import leitura
from forge.services import insights_canal
from forge.services.youtube import YouTubeAuthError, YouTubeClient
from forge.services.youtube_analytics import YouTubeAnalytics
from forge.services.youtube_auth import GoogleCredentials

PREFIXO = "https://www.googleapis.com/auth/"
LEITURA = PREFIXO + "youtube.readonly"
ANALYTICS = PREFIXO + "yt-analytics.readonly"


class ContextoCanal:
    def __init__(self, db, settings, conta, canal, agendar, *, clientes=None):
        self.db, self.conta, self.canal = db, conta, canal
        self.agendar, self.raiz = agendar, Path(settings.studio_runs_dir)
        with db.connection() as conn:
            row = conn.execute("""SELECT credencial,escopos FROM acesso_canais
                                  WHERE conta_id=? AND canal_id=?""", (conta, canal)).fetchone()
        if row is None:
            raise KeyError("Canal")
        self.escopos = set(row["escopos"].split())
        credencial = row["credencial"]
        self.conectado = bool(credencial and Path(credencial).is_file())
        if self.conectado:
            cred = GoogleCredentials(Path(credencial), settings.youtube_client_secrets)
            try:
                self.escopos.intersection_update(cred.escopos())
            except YouTubeAuthError:
                self.conectado = False
            self.identidade = [conta, credencial, sorted(self.escopos)]
            if clientes:
                self.youtube, self.analytics = clientes(cred)
            else:
                self.youtube = YouTubeClient(cred.access_token)
                self.analytics = YouTubeAnalytics(cred.access_token)

    def pode_ler(self):
        return self.conectado and bool(self.escopos & {LEITURA, PREFIXO+"youtube.force-ssl", PREFIXO+"youtube"})

    def catalogo(self, forcar=False):
        if not self.pode_ler():
            return ("sem_autorizacao" if self.conectado else "reconectar"), None
        estado, data, _ = leitura(
            self.db, self.canal, "catalogo", [sorted(self.escopos)],
            lambda: list(self.youtube.catalogo_publico(self.canal)), self.agendar,
            forcar=forcar, credencial=self.identidade[:2],
            publicar=lambda conn, dados: confirmar(conn, self.raiz, self.canal, dados))
        return estado, data

    def relatorio(self, inicio, fim, video=None, forcar=False):
        dados = dict(views=None, minutos=None, serie=[], observacoes=[], contribuicoes=[], amostra=0,
                     comparacao=None, retencao=[], janelas={"d7": [], "d28": []})
        data = None
        if not self.conectado:
            estado = "reconectar"
        elif not {LEITURA, ANALYTICS} <= self.escopos:
            estado = "sem_autorizacao"
        else:
            if video:
                recurso = [video["video_id"], video["publicado_em"]]
                buscar = partial(insights_canal.detalhe, self.analytics, self.canal, video, inicio, fim)
            else:
                recurso = "resumo"
                buscar = partial(insights_canal.resumo, self.analytics, self.canal, inicio, fim)
            chave = [*self.identidade, str(inicio), str(fim), recurso]
            estado, data, ultimo = leitura(self.db, self.canal, "relatorio", chave, buscar,
                                           self.agendar, forcar=forcar, credencial=self.identidade[:2])
            if ultimo:
                dados.update(ultimo)
                if estado == "atualizado":
                    estado = ultimo["estado"]
        dados.update(estado=estado, ultima_atualizacao=data, inicio=str(inicio), fim=str(fim))
        return dados
