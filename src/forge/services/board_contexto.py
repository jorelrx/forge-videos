"""Contexto editorial derivado das leituras autorizadas da Fase 0."""
from dataclasses import dataclass
from urllib.parse import quote, urlencode

from forge.domain.board_criativo import FonteBoard
from forge.infrastructure.logging import get_logger
from forge.repositories.catalogo_canal import obter
from forge.services.insights_canal import periodo
from forge.services.youtube import YouTubeError

log = get_logger(__name__)
LIMITE_CATALOGO = 12
LIMITE_EPISODIOS = 3


@dataclass(frozen=True)
class ContextoEditorial:
    estado_catalogo: str
    estado_analytics: str
    atualizado_em: str | None
    aguardando: bool
    videos: list[FonteBoard]
    observacoes: list[FonteBoard]

    @property
    def pode_exibir_analytics(self):
        return self.estado_analytics not in {"sem_autorizacao", "reconectar"}

    def para_api(self):
        return {
            "precisa_posicionamento": not self.videos,
            "aguardando": self.aguardando,
            "estado_catalogo": self.estado_catalogo,
            "estado_analytics": self.estado_analytics,
            "atualizado_em": self.atualizado_em,
            "observacoes": [fonte.model_dump() for fonte in self.observacoes],
        }


def ler_contexto(ctx) -> ContextoEditorial:
    estado, atualizado = ctx.catalogo()
    inicio, fim = periodo()
    resumo = ctx.relatorio(inicio, fim)
    raiz = f"/canais/{quote(ctx.canal, safe='')}/videos/"
    consulta = urlencode({"inicio": inicio, "fim": fim})
    videos, desempenho = [], []
    if estado not in {"sem_autorizacao", "reconectar"}:
        with ctx.db.connection() as conn:
            rows = conn.execute("""SELECT video_id,titulo,publicado_em FROM catalogo_canal
                WHERE canal_id=? ORDER BY publicado_em DESC,video_id LIMIT ?""",
                                (ctx.canal, LIMITE_CATALOGO)).fetchall()
        videos = [
            FonteBoard(id=f"video:{r['video_id']}", tipo="catalogo", titulo=r["titulo"],
                       url=raiz + quote(r["video_id"], safe="") + "?" + consulta, publicado_em=r["publicado_em"])
            for r in rows
        ]
        for item in resumo["contribuicoes"]:
            obs = item.get("observacao")
            if not obs or obs["valor"] is None:
                continue
            video = obter(ctx.db, ctx.canal, item["video_id"])
            if not video:
                continue
            desempenho.append(FonteBoard(
                id=f"desempenho:{item['video_id']}", tipo="desempenho", titulo=video["titulo"],
                url=raiz + quote(item["video_id"], safe="") + "?" + consulta + "#views",
                observacao=obs, amostra=resumo["amostra"],
            ))
            if len(desempenho) == 3:
                break
    aguardando = (estado == "sincronizando" and not atualizado) or bool(
        videos and resumo["estado"] == "sincronizando" and not resumo["ultima_atualizacao"])
    atuais = _atencao_observada(ctx, videos, inicio, fim)
    observacoes = [*desempenho[:1], *atuais, *desempenho[1:]][:3]
    return ContextoEditorial(estado, resumo["estado"], atualizado, aguardando, videos, observacoes)


def _atencao_observada(ctx, videos, inicio, fim):
    fontes = []
    for video in videos[:LIMITE_EPISODIOS]:
        video_id = video.id.removeprefix("video:")
        detalhe = ctx.relatorio(inicio, fim, video={"video_id": video_id, "publicado_em": video.publicado_em},
                                somente_cache=True)
        if detalhe["estado"] in {"sem_autorizacao", "reconectar"}:
            break
        medida = next((obs for obs in detalhe["observacoes"]
                       if obs["medida"] in {"duracao_media", "percentual_assistido"} and obs["valor"] is not None), None)
        if medida:
            fontes.append(FonteBoard(id=f"{medida['medida']}:{video_id}", tipo="desempenho", titulo=video.titulo,
                                    url=video.url + "#" + medida["medida"], observacao=medida))
        if len(fontes) == 2:
            break
    return fontes


def perguntas_publicas(ctx, contexto: ContextoEditorial) -> list[FonteBoard]:
    fontes = {}
    for video in contexto.videos[:LIMITE_EPISODIOS]:
        video_id = video.id.removeprefix("video:")
        try:
            comentarios = ctx.youtube.comentarios_publicos(video_id)
        except (YouTubeError, ValueError, KeyError, TypeError) as erro:
            log.info("comentarios_board_indisponiveis", canal=ctx.canal, erro=type(erro).__name__)
            continue
        for item in comentarios:
            chave = f"comentario:{item['id']}"
            fontes[chave] = FonteBoard(
                id=chave, tipo="comentario", titulo=video.titulo,
                url="https://www.youtube.com/watch?" + urlencode({"v": video_id, "lc": item["id"]}),
                texto=item["texto"], publicado_em=item["publicado_em"],
            )
    return list(fontes.values())
