from datetime import date, timedelta

import httpx
import pytest

from forge.services.insights_canal import atividade, detalhe, resumo
from forge.services.youtube_analytics import YouTubeAnalytics


class Relatorios:
    def __init__(self, dias=28):
        self.dias = dias

    def consultar(self, canal, inicio, fim, metricas, *, dimensao=None, video=None):
        if dimensao == "video":
            return [dict(video_id="externo", views=70), dict(video_id="antigo", views=50)]
        if dimensao == "elapsedVideoTimeRatio":
            return [dict(posicao=0.5, proporcao=0.82)]
        if metricas[0].startswith("average"):
            return []
        if dimensao == "day":
            return [dict(dia=str(inicio+timedelta(days=i)), views=0, minutos=0)
                    for i in range(min((fim-inicio).days+1, self.dias))]
        return [dict(views=120 if not video else 0, minutos=80)] if self.dias else []


def test_total_independente_comparacao_e_cobertura():
    inicio, fim = date(2026, 1, 1), date(2026, 1, 28)
    dados = resumo(Relatorios(), "A", inicio, fim)
    assert dados["views"] == 120 and dados["contribuicoes"][0]["views"] == 70
    assert dados["comparacao"]["views"] == 120
    parcial = resumo(Relatorios(20), "A", inicio, fim)
    assert parcial["comparacao"] is None
    assert parcial["estado"] == "atrasado"
    assert parcial["observacoes"][0]["cobertura"] == 20
    sem_dados = atividade(Relatorios(0), "A", inicio, fim)
    assert sem_dados["estado"] == "sem_dados" and sem_dados["views"] is None


def test_dia_civil_e_janelas_confirmadas():
    video = {"video_id": "externo", "publicado_em": "2026-01-02T01:00:00+00:00"}
    dados = detalhe(Relatorios(20), "A", video, date(2026, 1, 1), date(2026, 1, 28))
    d7 = dados["janelas"]["d7"][0]
    assert (d7["inicio"], d7["fim"], d7["cobertura"], d7["valor"]) == ("2026-01-01", "2026-01-07", 7, 0)
    assert dados["janelas"]["d28"] == []
    assert dados["retencao"][0]["proporcao"] == 0.82
    assert dados["observacoes"][2]["valor"] is None


def test_query_valida_contrato_e_unidades():
    headers = [dict(name="day", columnType="DIMENSION", dataType="STRING"),
               dict(name="views", columnType="METRIC", dataType="INTEGER")]
    def responder(request):
        assert request.url.params["ids"] == "channel==A"
        assert request.url.params["filters"] == "video==externo"
        assert request.headers["Authorization"] == "Bearer teste"
        return httpx.Response(200, json={"columnHeaders": headers, "rows": [["2026-01-01", 0]]})
    with httpx.Client(transport=httpx.MockTransport(responder)) as client:
        api = YouTubeAnalytics(lambda: "teste", client=client)
        args = ("A", date(2026, 1, 1), date(2026, 1, 2), ("views",))
        assert api.consultar(*args, video="externo", dimensao="day")[0]["views"] == 0
        headers[1]["name"] = "likes"
        with pytest.raises(ValueError, match="Colunas"):
            api.consultar(*args, video="externo", dimensao="day")
