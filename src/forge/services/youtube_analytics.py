"""Leitura tipada de reports.query do proprietário de um canal."""
import math
from datetime import date

import httpx

from forge.services.youtube import YouTubeAuthError, YouTubeError, YouTubeQuotaError

URL = "https://youtubeanalytics.googleapis.com/v2/reports"
UNIDADES = {
    "views": ("views", "visualizações"), "estimatedMinutesWatched": ("minutos", "minutos"),
    "averageViewDuration": ("duracao_media", "segundos"),
    "averageViewPercentage": ("percentual_assistido", "%"),
    "audienceWatchRatio": ("proporcao", "proporção"),
}
DIMENSOES = {"day": "dia", "video": "video_id", "elapsedVideoTimeRatio": "posicao"}


class YouTubeAnalytics:
    def __init__(self, token, *, client=None):
        self.token = token
        self.client = client

    def consultar(self, canal, inicio, fim, metricas, *, dimensao=None, video=None):
        params = {"ids": f"channel=={canal}", "startDate": str(inicio), "endDate": str(fim),
                  "metrics": ",".join(metricas)}
        if video:
            params["filters"] = f"video=={video}"
        if dimensao:
            params["dimensions"] = dimensao
        if dimensao == "video":
            params.update(maxResults=200, sort="-views")
        get = self.client.get if self.client else httpx.get
        resposta = get(URL, params=params, headers={"Authorization": f"Bearer {self.token()}"}, timeout=30)
        if resposta.status_code in (401, 403):
            motivos = resposta.json().get("error", {}).get("errors", [])
            if any(m.get("reason") in {"quotaExceeded", "rateLimitExceeded", "dailyLimitExceeded"}
                   for m in motivos):
                raise YouTubeQuotaError("Cota excedida")
            raise YouTubeAuthError("Permissão do relatório recusada")
        if resposta.status_code != 200:
            raise YouTubeError("Falha ao consultar relatório", status=resposta.status_code)
        resposta = resposta.json()
        campos = ([dimensao] if dimensao else []) + list(metricas)
        headers = resposta["columnHeaders"]
        if [h["name"] for h in headers] != campos:
            raise ValueError("Colunas inesperadas no relatório")
        for h in headers:
            metrica = h["name"] in UNIDADES
            tipo = "METRIC" if metrica else "DIMENSION"
            dados = {"INTEGER", "FLOAT"} if metrica else {"STRING"}
            if h["name"] == "averageViewPercentage":
                dados.add("PERCENT")
            if h["name"] == "averageViewDuration":
                dados.add("TIME")
            if h["name"] == "elapsedVideoTimeRatio":
                dados = {"FLOAT"}
            if h["columnType"] != tipo or h["dataType"] not in dados:
                raise ValueError("Tipo de coluna incompatível")
        linhas = []
        for row in resposta.get("rows", []):
            linha = {}
            for campo, val in zip(campos, row, strict=True):
                if campo in UNIDADES or campo == "elapsedVideoTimeRatio":
                    if val is not None and (type(val) not in (float, int) or not math.isfinite(val) or val < 0):
                        raise ValueError("Valor de medida inválido")
                elif not isinstance(val, str):
                    raise ValueError("Dimensão inválida")
                if campo == "day" and not inicio <= date.fromisoformat(val) <= fim:
                    raise ValueError("Dia fora do intervalo")
                nome = UNIDADES[campo][0] if campo in UNIDADES else DIMENSOES[campo]
                linha[nome] = val
            linhas.append(linha)
        return linhas
