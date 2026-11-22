"""Percurso de cada episódio aprovado no Board: execução, publicação e janelas de medição.

Nada aqui é persistido. O percurso é lido de onde cada fato já mora: a aprovação,
a execução, o `publicacao.json` da run, o catálogo público e o cache do detalhe.
"""
import json
from datetime import date, datetime, timedelta
from urllib.parse import quote, urlencode

from forge.domain.board_criativo import FonteBoard
from forge.infrastructure.logging import get_logger
from forge.repositories.board_criativo import aprovacoes_do_canal
from forge.repositories.catalogo_canal import obter
from forge.services.insights_canal import FUSO, periodo
from forge.services.publicacao import ler_estado

log = get_logger(__name__)
JANELAS = (7, 28)


def _publicacao(raiz, run_id):
    try:
        return ler_estado(raiz / run_id)
    except (ValueError, OSError) as erro:
        log.info("publicacao_ilegivel_no_board", run=run_id, erro=type(erro).__name__)
        return None


def _run(db, run_id):
    with db.connection() as conn:
        row = conn.execute("SELECT status, config_snapshot_json FROM runs WHERE id=?", (run_id,)).fetchone()
    if not row:
        return None, {}
    snapshot = row["config_snapshot_json"]
    return row["status"], json.loads(snapshot) if isinstance(snapshot, str) else dict(snapshot or {})


def _url_video(canal, video_id):
    inicio, fim = periodo()
    return (f"/canais/{quote(canal, safe='')}/videos/{quote(video_id, safe='')}?"
            + urlencode({"inicio": inicio, "fim": fim}))


def _janelas(ctx, video, publicado_em, hoje):
    primeiro = datetime.fromisoformat(publicado_em).astimezone(FUSO).date()
    detalhe = {}
    try:
        inicio, fim = periodo()
        # Leitura normal, não só cache: a chave do detalhe muda com o período do dia, então
        # só o cache quase nunca acertava. A leitura é deduplicada e renovada uma vez por dia.
        detalhe = ctx.relatorio(inicio, fim, video={"video_id": video, "publicado_em": publicado_em}
                                ).get("janelas") or {}
    except Exception as erro:  # o cache do detalhe é opcional; o percurso não depende dele
        log.info("janelas_board_indisponiveis", video=video, erro=type(erro).__name__)
    return {f"d{n}": {"completa": primeiro + timedelta(days=n - 1) < hoje,
                      "fim": (primeiro + timedelta(days=n - 1)).isoformat(),
                      "observacoes": detalhe.get(f"d{n}") or []} for n in JANELAS}


def episodio_da_aprovacao(ctx, aprovacao, hoje: date) -> dict:
    status, snapshot = _run(ctx.db, aprovacao["run_id"])
    pauta = snapshot.get("pauta_decidida") or aprovacao["pauta"]
    estado = _publicacao(ctx.raiz, aprovacao["run_id"])
    catalogo = obter(ctx.db, ctx.canal, estado.video_id) if estado and estado.etapa == "concluida" and estado.video_id else None
    episodio = {
        "aprovacao_id": aprovacao["id"], "revisao": aprovacao["revisao"],
        "titulo": aprovacao["pauta"].get("titulo") or aprovacao["pauta"].get("tema", ""),
        "run_id": aprovacao["run_id"], "run_status": status,
        "promessa": pauta.get("promessa", ""), "recorte": pauta.get("recorte", ""),
        "abertura": aprovacao["pauta"].get("abertura", ""),
        "abertura_sha256": (estado.abertura_sha256 if estado else None) or snapshot.get("previa_aprovada_sha256"),
        "decisao": (snapshot.get("decisao_pauta") or {}).get("acao"),
        "publicar_em": estado.publicar_em if estado else None,
        "video_id": estado.video_id if estado and estado.etapa == "concluida" else None,
        "publicado_em": None, "janelas": None, "url": None,
    }
    if status == "cancelled":
        episodio["momento"] = "cancelado"
    elif catalogo:
        janelas = _janelas(ctx, catalogo["video_id"], catalogo["publicado_em"], hoje)
        episodio.update(publicado_em=catalogo["publicado_em"], janelas=janelas,
                        url=_url_video(ctx.canal, catalogo["video_id"]),
                        momento="janela_completa" if janelas["d7"]["completa"] else "publico")
    elif episodio["video_id"]:
        episodio["momento"] = "agendado" if estado.publicar_em else "enviado"
    else:
        episodio["momento"] = "em_producao"
    return episodio


def episodios(ctx, *, limite: int = 10, hoje: date | None = None) -> list[dict]:
    dia = hoje or datetime.now(FUSO).date()
    return [episodio_da_aprovacao(ctx, aprovacao, dia)
            for aprovacao in aprovacoes_do_canal(ctx.db, ctx.conta, ctx.canal, limite)]


def fontes_de_episodios(lista: list[dict], pode_exibir_analytics: bool) -> list[FonteBoard]:
    """Episódios públicos viram fonte da próxima análise, com janela e abertura registradas."""
    fontes = []
    for item in lista:
        if not item["publicado_em"]:
            continue
        observacao = None
        if pode_exibir_analytics:
            for janela in ("d28", "d7"):
                dados = item["janelas"][janela]
                medida = next((o for o in dados["observacoes"] if o.get("medida") == "views"
                               and o.get("valor") is not None), None) if dados["completa"] else None
                if medida:
                    observacao = medida
                    break
        texto = "; ".join(parte for parte in (
            f"Promessa: {item['promessa']}" if item["promessa"] else "",
            f"Abertura aprovada: {item['abertura']}" if item["abertura"] else "",
        ) if parte)
        fontes.append(FonteBoard(
            id=f"episodio:{item['video_id']}", tipo="episodio", titulo=item["titulo"],
            url=item["url"] + "#janelas", texto=texto or None, publicado_em=item["publicado_em"],
            observacao=observacao,
        ))
    return fontes


def pauta_de_origem(ctx, run_id: str | None) -> dict | None:
    """Pauta aprovada que originou o vídeo, com a decisão posterior e a versão da abertura."""
    if not run_id:
        return None
    with ctx.db.connection() as conn:
        row = conn.execute("""SELECT * FROM aprovacoes_pauta WHERE run_id=? AND conta_id=? AND canal_id=?""",
                           (run_id, ctx.conta, ctx.canal)).fetchone()
    if not row:
        return None
    _, snapshot = _run(ctx.db, run_id)
    aprovada = json.loads(row["pauta"])
    decidida = snapshot.get("pauta_decidida") or aprovada
    estado = _publicacao(ctx.raiz, run_id)
    return {
        "aprovacao_id": row["id"], "revisao": row["revisao"], "titulo": aprovada.get("titulo", ""),
        "promessa": decidida.get("promessa", ""), "recorte": decidida.get("recorte", ""),
        "abertura": aprovada.get("abertura", ""), "decisao": (snapshot.get("decisao_pauta") or {}).get("acao"),
        "abertura_sha256": (estado.abertura_sha256 if estado else None) or snapshot.get("previa_aprovada_sha256"),
    }
