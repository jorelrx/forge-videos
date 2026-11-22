"""Vínculos confirmados pela API do YouTube. O índice legado é exclusivo do operador."""
from pathlib import Path
import os
import shutil
import tempfile
import time
import weakref

from forge.services.youtube import YouTubeAuthError
from forge.services.youtube_auth import GoogleCredentials
from forge.services.youtube_canais import Canal


class AcessoCanais:
    def __init__(self, db, conta_id, settings):
        self.db = db
        self.conta_id = conta_id
        self.settings = settings

    def painel(self):
        with self.db.connection() as conn:
            rows = conn.execute("""SELECT a.*,c.ultimo_canal_id FROM acesso_canais a
                JOIN contas c ON c.id=a.conta_id WHERE conta_id=? ORDER BY titulo,canal_id""",
                (self.conta_id,)).fetchall()
        canais = [{"id": r["canal_id"], "titulo": r["titulo"], "thumbnail": r["thumbnail"],
                   "conectado": bool(r["credencial"] and Path(r["credencial"]).is_file()),
                   "padrao": r["ultimo_canal_id"] == r["canal_id"]} for r in rows]
        return {"canais": canais, "ultimo_canal_id": next((c["id"] for c in canais if c["padrao"]), None)}

    def listar(self):
        return [Canal(c["id"], c["titulo"], c["thumbnail"], c["padrao"])
                for c in self.painel()["canais"] if c["conectado"]]

    def padrao(self):
        return self.painel()["ultimo_canal_id"]

    def titulo(self, canal_id):
        return next((c["titulo"] for c in self.painel()["canais"] if c["id"] == canal_id), None)

    def credenciais(self, canal_id):
        # O upload possui seu snapshot até a thread terminar, inclusive após desconexão.
        with self.db.transaction(immediate=True) as conn:
            row = conn.execute("SELECT credencial FROM acesso_canais WHERE conta_id=? AND canal_id=?",
                               (self.conta_id, canal_id)).fetchone()
            if not row or not row[0] or not Path(row[0]).is_file():
                raise KeyError(canal_id)
            pasta = tempfile.TemporaryDirectory(prefix="forge-upload-")
            path = Path(pasta.name) / "token.json"
            try:
                shutil.copyfile(row[0], path)
                path.chmod(0o600)
            except BaseException:
                pasta.cleanup()
                raise
        credenciais = GoogleCredentials(path, self.settings.youtube_client_secrets)
        credenciais.liberar = weakref.finalize(credenciais, pasta.cleanup)
        return credenciais

    def _descartar(self, conn, anterior):
        if anterior and not conn.execute("SELECT 1 FROM acesso_canais WHERE credencial=?", (anterior,)).fetchone():
            path = Path(anterior)
            if path.parent == Path(self.settings.youtube_canais_dir).resolve() / "vinculos":
                path.unlink(missing_ok=True)

    def vincular(self, tmp, canal, escopos, sessao_digest, esperado, prazo):
        pasta = Path(self.settings.youtube_canais_dir).resolve() / "vinculos"
        pasta.mkdir(parents=True, exist_ok=True)
        destino = pasta / tmp.name
        with self.db.transaction(immediate=True) as conn:
            agora = time.time()
            sessao = conn.execute("""SELECT 1 FROM sessoes WHERE digest=? AND conta_id=?
                AND expira>? AND revogada=0""", (sessao_digest, self.conta_id, agora)).fetchone()
            anterior = conn.execute("SELECT credencial,escopos FROM acesso_canais WHERE conta_id=? AND canal_id=?",
                                    (self.conta_id, canal.id)).fetchone()
            if (not sessao or agora >= prazo or esperado and (canal.id != esperado or not anterior)):
                raise YouTubeAuthError("Autorização expirada ou canal diferente")
            if anterior and not set(anterior["escopos"].split()).issubset(escopos):
                raise YouTubeAuthError("Permissões anteriores não concedidas. A conexão anterior foi preservada.")
            os.replace(tmp, destino)
            try:
                conn.execute("""INSERT INTO acesso_canais(conta_id,canal_id,titulo,thumbnail,credencial,escopos)
                    VALUES(?,?,?,?,?,?) ON CONFLICT(conta_id,canal_id) DO UPDATE SET titulo=excluded.titulo,
                    thumbnail=excluded.thumbnail,credencial=excluded.credencial,escopos=excluded.escopos""",
                    (self.conta_id, canal.id, canal.titulo, canal.thumbnail, str(destino), " ".join(sorted(escopos))))
                conn.execute("UPDATE contas SET ultimo_canal_id=coalesce(ultimo_canal_id,?) WHERE id=?",
                             (canal.id, self.conta_id))
            except BaseException:
                destino.unlink(missing_ok=True)
                raise
        if anterior:
            with self.db.transaction(immediate=True) as conn:
                self._descartar(conn, anterior["credencial"])

    def desconectar(self, canal_id):
        with self.db.transaction(immediate=True) as conn:
            row = conn.execute("DELETE FROM acesso_canais WHERE conta_id=? AND canal_id=? RETURNING credencial",
                               (self.conta_id, canal_id)).fetchone()
            if row is None:
                raise KeyError(canal_id)
            conn.execute("UPDATE contas SET ultimo_canal_id=NULL WHERE id=? AND ultimo_canal_id=?",
                         (self.conta_id, canal_id))
        with self.db.transaction(immediate=True) as conn:
            self._descartar(conn, row[0])
