import json
from datetime import datetime, timedelta, timezone

import pytest

from forge.infrastructure.config import Settings

AGORA = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def run_aprovada(tmp_path, aprovado=True):
    video = tmp_path / "run" / "video"
    video.mkdir(parents=True)
    (video / "final.mp4").write_bytes(b"x" * 10)
    (video / "thumbnail.jpg").write_bytes(b"\xff\xd8")
    (video / "legendas.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nOi\n", encoding="utf-8")
    (video / "validation.json").write_text(json.dumps({"approved": aprovado}), encoding="utf-8")
    (video / "embalagem.json").write_text(json.dumps({
        "titulos": [{"texto": "Primeiro título", "angulo": "pergunta"},
                    {"texto": "Segundo título", "angulo": "benefício"}],
        "thumbnail": {"texto": "x", "prompt": "y"},
        "descricao": "Descrição completa",
        "tags": ["a", "b"],
        "comentario_fixado": "Pergunta?",
    }), encoding="utf-8")
    return tmp_path / "run"


class FakeCliente:
    def __init__(self, falhar_em=None, erro=None):
        self.chamadas = []
        self.falhar_em = falhar_em
        self.erro = erro

    def _talvez_falhar(self, nome):
        if self.falhar_em == nome:
            self.falhar_em = None
            raise self.erro

    def iniciar_upload(self, metadados, tamanho):
        self.chamadas.append(("iniciar", metadados, tamanho))
        self._talvez_falhar("iniciar")
        return "https://sessao"

    def enviar_arquivo(self, sessao, arquivo, *, inicio, ao_avancar=None):
        self.chamadas.append(("enviar", sessao, inicio))
        if ao_avancar:
            ao_avancar(4)
        self._talvez_falhar("enviar")
        return {"id": "vid123"}

    def definir_thumbnail(self, video_id, caminho):
        self.chamadas.append(("thumbnail", video_id))
        self._talvez_falhar("thumbnail")

    def enviar_legenda(self, video_id, caminho, *, idioma, nome):
        self.chamadas.append(("legenda", video_id, idioma))
        self._talvez_falhar("legenda")


def settings():
    return Settings(_env_file=None)


def publicar(run, cliente, **kwargs):
    from forge.services.publicacao import publicar as alvo
    kwargs.setdefault("titulo", None)
    kwargs.setdefault("publicar_em", None)
    return alvo(run, cliente=cliente, settings=settings(), agora=lambda: AGORA, **kwargs)


def test_publica_privado_com_metadados_thumbnail_e_legenda(tmp_path):
    run = run_aprovada(tmp_path)
    cliente = FakeCliente()
    estado = publicar(run, cliente)
    assert estado.etapa == "concluida"
    assert estado.video_id == "vid123"
    assert estado.url == "https://studio.youtube.com/video/vid123/edit"
    metadados = cliente.chamadas[0][1]
    assert metadados["snippet"] == {
        "title": "Primeiro título", "description": "Descrição completa",
        "tags": ["a", "b"], "categoryId": "27",
        "defaultLanguage": "pt-BR", "defaultAudioLanguage": "pt-BR",
    }
    assert metadados["status"] == {
        "privacyStatus": "private", "selfDeclaredMadeForKids": False,
        "containsSyntheticMedia": True, "embeddable": True, "license": "youtube",
    }
    assert [c[0] for c in cliente.chamadas] == ["iniciar", "enviar", "thumbnail", "legenda"]
    gravado = json.loads((run / "video" / "publicacao.json").read_text(encoding="utf-8"))
    assert gravado["etapa"] == "concluida" and gravado["thumbnail"] == "ok"


def test_titulo_escolhido_e_agendamento_em_utc(tmp_path):
    run = run_aprovada(tmp_path)
    cliente = FakeCliente()
    quando = datetime(2026, 11, 21, 18, 0, tzinfo=timezone(timedelta(hours=-3)))
    publicar(run, cliente, titulo="Segundo título", publicar_em=quando)
    metadados = cliente.chamadas[0][1]
    assert metadados["snippet"]["title"] == "Segundo título"
    assert metadados["status"]["privacyStatus"] == "private"
    assert metadados["status"]["publishAt"] == "2026-11-21T21:00:00Z"


@pytest.mark.parametrize("quando", [
    AGORA + timedelta(minutes=5), AGORA - timedelta(days=1), datetime(2026, 11, 21, 18, 0),
])
def test_agendamento_invalido_e_recusado_sem_chamar_api(tmp_path, quando):
    from forge.services.publicacao import PublicacaoRecusada
    cliente = FakeCliente()
    with pytest.raises(PublicacaoRecusada):
        publicar(run_aprovada(tmp_path), cliente, publicar_em=quando)
    assert cliente.chamadas == []


@pytest.mark.parametrize("titulo", ["", "a" * 101, "Título com <tag>"])
def test_titulo_invalido_e_recusado(tmp_path, titulo):
    from forge.services.publicacao import PublicacaoRecusada
    with pytest.raises(PublicacaoRecusada):
        publicar(run_aprovada(tmp_path), FakeCliente(), titulo=titulo)


def test_run_nao_aprovada_e_recusada(tmp_path):
    from forge.services.publicacao import PublicacaoRecusada
    cliente = FakeCliente()
    with pytest.raises(PublicacaoRecusada, match="validação"):
        publicar(run_aprovada(tmp_path, aprovado=False), cliente)
    assert cliente.chamadas == []
    assert not (tmp_path / "run" / "video" / "publicacao.json").exists()


def test_queda_no_envio_retoma_a_mesma_sessao_sem_novo_upload(tmp_path):
    from forge.services.youtube import YouTubeError
    run = run_aprovada(tmp_path)
    cliente = FakeCliente(falhar_em="enviar", erro=YouTubeError("caiu"))
    with pytest.raises(YouTubeError):
        publicar(run, cliente)
    from forge.services.publicacao import ler_estado
    falho = ler_estado(run)
    assert falho.etapa == "falhou" and falho.erro == "caiu"
    assert falho.upload_uri == "https://sessao" and falho.bytes_enviados == 4

    estado = publicar(run, cliente)
    assert estado.etapa == "concluida"
    assert [c[0] for c in cliente.chamadas].count("iniciar") == 1
    assert ("enviar", "https://sessao", 4) in cliente.chamadas


def test_sessao_expirada_recomeca_o_upload_uma_vez(tmp_path):
    from forge.services.youtube import YouTubeSessaoExpirada
    run = run_aprovada(tmp_path)
    cliente = FakeCliente(falhar_em="enviar", erro=YouTubeSessaoExpirada("expirou"))
    estado = publicar(run, cliente)
    assert estado.etapa == "concluida"
    assert [c[0] for c in cliente.chamadas].count("iniciar") == 2


def test_thumbnail_recusada_vira_aviso_e_conclui(tmp_path):
    from forge.services.youtube import YouTubeError
    run = run_aprovada(tmp_path)
    estado = publicar(run, FakeCliente(falhar_em="thumbnail", erro=YouTubeError("canal não verificado")))
    assert estado.etapa == "concluida"
    assert estado.thumbnail == "recusada"
    assert any("thumbnail_recusada" in aviso for aviso in estado.avisos)


def test_cota_na_legenda_falha_e_retomada_so_refaz_a_legenda(tmp_path):
    from forge.services.youtube import YouTubeQuotaError
    run = run_aprovada(tmp_path)
    cliente = FakeCliente(falhar_em="legenda", erro=YouTubeQuotaError("cota"))
    with pytest.raises(YouTubeQuotaError):
        publicar(run, cliente)
    cliente.chamadas.clear()
    estado = publicar(run, cliente)
    assert estado.etapa == "concluida"
    assert [c[0] for c in cliente.chamadas] == ["legenda"]


def test_publicacao_concluida_nao_sobe_de_novo(tmp_path):
    from forge.services.publicacao import JaPublicado
    run = run_aprovada(tmp_path)
    publicar(run, FakeCliente())
    cliente = FakeCliente()
    with pytest.raises(JaPublicado):
        publicar(run, cliente)
    assert cliente.chamadas == []


def test_estado_sem_publicacao_e_none(tmp_path):
    from forge.services.publicacao import ler_estado
    assert ler_estado(run_aprovada(tmp_path)) is None
