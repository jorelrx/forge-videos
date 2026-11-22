import base64
import hashlib
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from forge.services.publicacao import ler_estado


class CursorDesatualizado(ValueError):
    """A página anterior pertencia a uma versão diferente dos resultados."""


def confirmar(conn, raiz, canal, videos):
    por_id = {v["video_id"]: v for v in videos}
    runs = {}
    # Só arquivos de runs registradas com publicação para o vídeo podem estabelecer posse.
    for row in conn.execute("SELECT id FROM runs WHERE canal_id IS NULL OR canal_id=?", (canal,)):
        run_id = row["id"]
        caminho = raiz / run_id
        if caminho.resolve().parent != raiz.resolve():
            continue
        try:
            estado = ler_estado(caminho)
        except (ValueError, OSError):
            # Um sidecar legado ilegível não identifica o vídeo desta run.
            continue
        if (estado and estado.etapa == "concluida" and estado.video_id in por_id
                and estado.canal_id in (None, canal)):
            runs[estado.video_id] = run_id
            conn.execute("UPDATE runs SET canal_id=? WHERE id=? AND canal_id IS NULL", (canal, run_id))
    conn.execute("DELETE FROM catalogo_canal WHERE canal_id=?", (canal,))
    conn.executemany("""INSERT INTO catalogo_canal
        (canal_id,video_id,titulo,thumbnail,publicado_em,run_id,views_total,comentarios_total,curtidas_total)
        VALUES (:canal,:video_id,:titulo,:thumbnail,:publicado_em,:run_id,
                :views_total,:comentarios_total,:curtidas_total)""",
        ({"views_total": None, "comentarios_total": None, "curtidas_total": None,
          **v, "canal": canal, "run_id": runs.get(v["video_id"])} for v in por_id.values()))


def obter(db, canal, video):
    with db.connection() as conn:
        row = conn.execute("SELECT * FROM catalogo_canal WHERE canal_id=? AND video_id=?",
                           (canal, video)).fetchone()
        return dict(row) if row else None


def pagina(db, canal, periodo, views, busca, de, ate, ordem, cursor, limite):
    assinatura = hashlib.sha256(json.dumps([canal, periodo, busca.casefold(), str(de),
                                            str(ate), ordem]).encode()).hexdigest()
    ultima = None
    versao_cursor = None
    if cursor:
        try:
            partes = json.loads(base64.urlsafe_b64decode(cursor))
            if not isinstance(partes, list) or len(partes) not in (2, 3):
                raise ValueError()
            identidade, ultima = partes[:2]
            if len(partes) == 3:
                versao_cursor = partes[2]
            if (identidade != assinatura or not isinstance(ultima, list) or len(ultima) != 2
                    or not isinstance(ultima[1], str)):
                raise ValueError()
            if ordem == "titulo" and not isinstance(ultima[0], str):
                raise ValueError()
            if ordem != "titulo" and type(ultima[0]) not in (float, int):
                raise ValueError()
        except (ValueError, TypeError, UnicodeError) as exc:
            raise ValueError("Cursor inválido para esta consulta") from exc

    fuso = ZoneInfo("America/Los_Angeles")
    def dia_civil(valor):
        return str(datetime.fromisoformat(valor).astimezone(fuso).date())

    # Todos os critérios crescem; views ausentes vêm depois do zero explícito.
    chave = {"titulo": "casefold(titulo)", "resultado": "-coalesce(m.value,-1)",
             "data": "-julianday(publicado_em)"}[ordem]
    views_json = json.dumps(views, sort_keys=True)
    params = dict(canal=canal, views=views_json, busca=busca.casefold(),
                  de=str(de) if de else None, ate=str(ate) if ate else None, limite=limite+1,
                  chave=ultima[0] if ultima else None, id=ultima[1] if ultima else None)
    with db.transaction() as conn:
        # Qualquer conjunto de escopos pode publicar o catálogo do canal.
        leituras = dict(conn.execute("""SELECT chave, sucesso FROM leituras_canal
                                       WHERE canal_id=? AND tipo='catalogo' AND sucesso IS NOT NULL""", (canal,)))
        ranking = views_json if ordem == "resultado" else None
        versao = hashlib.sha256(json.dumps([leituras, ranking], sort_keys=True).encode()).hexdigest()
        if cursor and versao_cursor != versao:
            raise CursorDesatualizado()
        conn.create_function("casefold", 1, str.casefold, deterministic=True)
        conn.create_function("dia_civil", 1, dia_civil, deterministic=True)
        rows = conn.execute(f"""
            SELECT c.*, m.value AS views, {chave} AS criterio
              FROM catalogo_canal c LEFT JOIN json_each(:views) m ON m.key=c.video_id
             WHERE c.canal_id=:canal AND instr(casefold(titulo),:busca)>0
               AND (:de IS NULL OR dia_civil(publicado_em)>=:de)
               AND (:ate IS NULL OR dia_civil(publicado_em)<=:ate)
               AND (:chave IS NULL OR ({chave},video_id)>(:chave,:id))
             ORDER BY criterio, video_id LIMIT :limite""", params).fetchall()
    proximo = None
    if len(rows) > limite:
        anterior = rows[limite-1]
        marca = json.dumps([assinatura, [anterior["criterio"], anterior["video_id"]], versao]).encode()
        proximo = base64.urlsafe_b64encode(marca).decode()
    return {"videos": [{k: r[k] for k in r.keys() if k != "criterio"} for r in rows[:limite]],
            "proximo_cursor": proximo}
