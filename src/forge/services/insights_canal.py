from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from forge.services.desempenho import ler_desempenho
from forge.services.publicacao import ler_estado
from forge.services.youtube import YouTubeError
from forge.services.youtube_analytics import UNIDADES

FUSO = ZoneInfo("America/Los_Angeles")
BASE = ("views", "estimatedMinutesWatched")


def periodo(inicio=None, fim=None):
    fim = fim or datetime.now(FUSO).date() - timedelta(days=1)
    inicio = inicio or fim - timedelta(days=27)
    if inicio > fim:
        raise ValueError("Início posterior ao fim")
    return inicio, fim


def observacao(canal, video, medida, unidade, valor, inicio, fim, dias, instante,
               origem="YouTube Analytics", denominador=None):
    recurso = f"/canais/{canal}" + (f"/videos/{video}" if video else "")
    evidencia = recurso + "?" + urlencode({"inicio": inicio, "fim": fim}) + "#" + medida
    return dict(canal_id=canal, video_id=video, medida=medida, valor=valor, unidade=unidade,
                denominador=denominador, origem=origem, inicio=str(inicio), fim=str(fim),
                inicio_efetivo=min(dias, default=None), fim_efetivo=max(dias, default=None),
                cobertura=len(dias), lido_em=instante, evidencia=evidencia)


def atividade(api, canal, inicio, fim, video=None):
    totais = api.consultar(canal, inicio, fim, BASE, video=video)
    if len(totais) > 1:
        raise ValueError("Mais de uma linha para o total")
    total = next(iter(totais), {})
    serie = sorted(api.consultar(canal, inicio, fim, BASE, dimensao="day", video=video),
                   key=lambda r: r["dia"])
    dias = {r["dia"] for r in serie if all(r[m] is not None for m in ("views", "minutos"))}
    if len({r["dia"] for r in serie}) != len(serie):
        raise ValueError("Dia duplicado no relatório")
    completo = len(dias) == (fim-inicio).days+1
    instante = datetime.now(UTC).isoformat()
    obs = [observacao(canal, video, *UNIDADES[m], total.get(UNIDADES[m][0]),
                      inicio, fim, dias, instante) for m in BASE]
    estado = "atualizado" if completo else ("atrasado" if serie or total else "sem_dados")
    return dict(views=total.get("views"), minutos=total.get("minutos"), serie=serie,
                observacoes=obs, completo=completo, estado=estado)


def resumo(api, canal, inicio, fim):
    atual = atividade(api, canal, inicio, fim)
    anterior = None
    if atual["completo"]:
        n = fim - inicio + timedelta(days=1)
        anterior = atividade(api, canal, inicio-n, inicio-timedelta(days=1))
    atual["comparacao"] = ({k: anterior[k] for k in ("views", "minutos")}
                           if anterior and anterior["completo"] else None)
    contribuicoes = api.consultar(canal, inicio, fim, ("views",), dimensao="video")
    instante = datetime.now(UTC).isoformat()
    for contribuicao in contribuicoes:
        evid = observacao(canal, contribuicao["video_id"], *UNIDADES["views"], contribuicao["views"],
                          inicio, fim, [], instante)
        # Top videos informa o agregado por episódio, sem dimensão diária.
        evid["cobertura"] = None
        contribuicao["observacao"] = evid
    atual.update(contribuicoes=contribuicoes, amostra=len(contribuicoes), limite_amostra=200)
    return atual


def detalhe(api, canal, video, inicio, fim):
    vid = video["video_id"]
    atual = atividade(api, canal, inicio, fim, vid)
    for metrica in ("averageViewDuration", "averageViewPercentage"):
        try:
            rows = api.consultar(canal, inicio, fim, (metrica,), video=vid, dimensao="day")
            total = api.consultar(canal, inicio, fim, (metrica,), video=vid)
        except YouTubeError as erro:
            if erro.status != 400:
                raise
            rows, total = [], []
        nome, unidade = UNIDADES[metrica]
        dias = {r["dia"] for r in rows if r[nome] is not None}
        atual["observacoes"].append(observacao(
            canal, vid, nome, unidade, next(iter(total), {}).get(nome), inicio, fim,
            dias, datetime.now(UTC).isoformat()))
    try:
        atual["retencao"] = api.consultar(canal, inicio, fim, ("audienceWatchRatio",),
                                           video=vid, dimensao="elapsedVideoTimeRatio")
    except YouTubeError as erro:
        if erro.status != 400:
            raise
        atual["retencao"] = []
    instante = datetime.now(UTC).isoformat()
    for ponto in atual["retencao"]:
        evid = observacao(canal, vid, "audienceWatchRatio", "proporção", ponto["proporcao"],
                          inicio, fim, [], instante, denominador="visualizações do vídeo")
        evid["cobertura"] = None
        ponto["observacao"] = evid
    primeiro = datetime.fromisoformat(video["publicado_em"]).astimezone(FUSO).date()
    atual["janelas"] = {}
    for n in (7, 28):
        ultimo = primeiro + timedelta(days=n-1)
        obs = []
        if ultimo < datetime.now(FUSO).date():
            janela = atividade(api, canal, primeiro, ultimo, vid)
            if janela["completo"]:
                obs = janela["observacoes"]
        atual["janelas"][f"d{n}"] = obs
    return atual


def incluir_manuais(dados, video, raiz, canal):
    run_id = video["run_id"]
    if not run_id:
        return
    run = raiz / run_id
    estado = ler_estado(run)
    if not estado or estado.video_id != video["video_id"] or estado.canal_id not in (canal, None):
        return
    unidades = {"visualizacoes": ("views", "visualizações"), "percentual_assistido": ("percentual_assistido", "%"),
                "impressoes": ("impressoes", "impressões"), "ctr": ("ctr", "%"),
                "retencao_30s": ("retencao_30s", "%"), "comentarios": ("comentarios", "comentários"),
                "respostas_lidas": ("respostas_lidas", "respostas"),
                "respostas_substantivas": ("respostas_substantivas", "respostas"),
                "cliques_tela_final": ("cliques_tela_final", "cliques")}
    inicio = datetime.fromisoformat(video["publicado_em"]).astimezone(FUSO).date()
    for registro in ler_desempenho(run, estado).medicoes:
        fim = inicio + timedelta(days=registro.janela-1)
        janela = dados["janelas"][f"d{registro.janela}"]
        for campo, (medida, unidade) in unidades.items():
            valor = getattr(registro, campo)
            if valor is None:
                continue
            obs = observacao(canal, video["video_id"], medida, unidade, valor, inicio, fim, [],
                             registro.registrado_em, origem="Medição manual")
            obs["cobertura"] = None  # O formulário anterior não coletava os dias efetivos.
            obs["denominador"] = registro.respostas_lidas if campo == "respostas_substantivas" else None
            obs["preferida"] = not any(o["medida"] == medida and o["valor"] is not None for o in janela)
            janela.append(obs)
