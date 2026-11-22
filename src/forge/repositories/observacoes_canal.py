"""Cache SQLite com posse temporária e troca atômica da última leitura válida."""
import json
import secrets
import time
from datetime import UTC, datetime

from forge.infrastructure.logging import get_logger
from forge.services.youtube import YouTubeApiDesativada, YouTubeAuthError

log = get_logger(__name__)
DIA = 86400


def _chave(canal, tipo, identidade):
    return json.dumps([canal, tipo, *identidade], separators=(",", ":"))


def _resultado(row, estado):
    data = datetime.fromtimestamp(row["sucesso"], UTC).isoformat() if row["sucesso"] else None
    return estado, data, json.loads(row["dados"]) if row["dados"] else None


def consultar_cache(db, canal, tipo, identidade):
    with db.connection() as conn:
        row = conn.execute("SELECT * FROM leituras_canal WHERE chave=?", (_chave(canal, tipo, identidade),)).fetchone()
    return _resultado(row, row["erro"] or "atualizado") if row else ("sem_dados", None, None)


def leitura(db, canal, tipo, identidade, buscar, agendar, *, forcar=False, publicar=None,
            credencial=None):
    chave = _chave(canal, tipo, identidade)
    agora = time.time()
    dono = secrets.token_hex(16)
    with db.transaction(immediate=True) as conn:
        conn.execute("""INSERT OR IGNORE INTO leituras_canal(chave,canal_id,tipo)
                        VALUES(?,?,?)""", (chave, canal, tipo))
        row = conn.execute("SELECT * FROM leituras_canal WHERE chave=?", (chave,)).fetchone()
        ativa = row["dono"] and row["expira"] > agora
        iniciar = not ativa and (forcar or row["proxima"] <= agora)
        if iniciar:
            conn.execute("UPDATE leituras_canal SET dono=?, expira=? WHERE chave=?",
                         (dono, agora + 900, chave))

    def executar():
        try:
            dados = buscar()
            with db.transaction(immediate=True) as conn:
                # Um processo interrompido pode voltar após outro assumir a leitura.
                if not conn.execute("SELECT 1 FROM leituras_canal WHERE chave=? AND dono=?",
                                    (chave, dono)).fetchone():
                    return
                if publicar:
                    publicar(conn, dados)
                    dados = None
                fim = time.time()
                conn.execute("""UPDATE leituras_canal SET dados=?, sucesso=?, proxima=?,
                                erro=NULL, dono=NULL WHERE chave=?""",
                             (json.dumps(dados), fim, fim + DIA, chave))
        except Exception as exc:
            auth = isinstance(exc, YouTubeAuthError)
            estado = "api_desativada" if isinstance(exc, YouTubeApiDesativada) else (
                "reconectar" if auth else "falha_temporaria")
            log.warning("leitura_youtube_falhou", canal=canal, tipo=tipo, erro=type(exc).__name__)
            with db.transaction(immediate=True) as conn:
                atualizado = conn.execute("""UPDATE leituras_canal SET erro=?, dono=NULL, proxima=?,
                                dados=CASE WHEN ? THEN NULL ELSE dados END WHERE chave=? AND dono=?""",
                             (estado, time.time()+60, auth, chave, dono))
                if auth and atualizado.rowcount and credencial:
                    # Outra janela/episódio da mesma autorização também perde acesso.
                    conn.execute("""UPDATE leituras_canal SET dados=NULL, sucesso=NULL, erro=?,
                                 dono=NULL, proxima=? WHERE canal_id=? AND tipo='relatorio'
                                 AND json_extract(chave,'$[2]')=? AND json_extract(chave,'$[3]')=?""",
                                 (estado, time.time()+60, canal, *credencial))

    if iniciar:
        agendar(executar)
    estado = "sincronizando" if iniciar or ativa else row["erro"] or "atualizado"
    return _resultado(row, estado)


def invalidar_catalogo(db, canal):
    with db.transaction(immediate=True) as conn:
        conn.execute("""UPDATE leituras_canal SET proxima=0, dono=NULL
                        WHERE canal_id=? AND tipo='catalogo'""", (canal,))
