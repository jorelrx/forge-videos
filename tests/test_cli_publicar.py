import json

import pytest

from forge.infrastructure.config import Settings


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        youtube_canais_dir=tmp_path / "yt" / "canais",
        youtube_client_secrets=tmp_path / "yt" / "client_secret.json",
    )
    monkeypatch.setattr("forge.cli.get_settings", lambda: settings)
    return settings


def test_auth_youtube_status_sem_login_falha_com_acao(ambiente, capsys):
    from forge.cli import main
    assert main(["auth", "youtube", "status"]) == 1
    assert "forge auth youtube login" in capsys.readouterr().err


def conectar(settings, canal_id="UC1", titulo="Canal Um", padrao=True):
    import time
    pasta = settings.youtube_canais_dir
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / f"{canal_id}.json").write_text(json.dumps({"tokens": {
        "access_token": "segredo-acesso", "refresh_token": "segredo-refresh",
        "expires_at": time.time() + 3600}}), encoding="utf-8")
    indice_path = pasta / "canais.json"
    indice = json.loads(indice_path.read_text()) if indice_path.exists() else {"padrao": None, "canais": {}}
    indice["canais"][canal_id] = {"titulo": titulo, "thumbnail": None}
    if padrao:
        indice["padrao"] = canal_id
    indice_path.write_text(json.dumps(indice), encoding="utf-8")


def test_auth_youtube_status_lista_canais_sem_mostrar_token(ambiente, capsys):
    from forge.cli import main
    conectar(ambiente)
    conectar(ambiente, "UC2", "Canal Dois", padrao=False)
    assert main(["auth", "youtube", "status"]) == 0
    saida = capsys.readouterr().out
    assert "Canal Um (UC1) [padrão]" in saida and "Canal Dois (UC2)" in saida
    assert "segredo" not in saida


def test_publicar_repassa_titulo_por_indice_e_agenda(ambiente, tmp_path, monkeypatch, capsys):
    from forge.cli import main
    from forge.services.publicacao import EstadoPublicacao
    run = tmp_path / "run"
    (run / "video").mkdir(parents=True)
    (run / "video" / "embalagem.json").write_text(json.dumps({
        "titulos": [{"texto": "A"}, {"texto": "B"}],
        "thumbnail": {"texto": "x", "prompt": "y"}, "descricao": "d",
    }), encoding="utf-8")
    pedidos = {}

    def falso(run_dir, *, cliente, settings, titulo, publicar_em, ao_progredir=None,
              canal_id=None, **_):
        pedidos.update(run=run_dir, titulo=titulo, publicar_em=publicar_em, canal_id=canal_id)
        return EstadoPublicacao(etapa="concluida", titulo=titulo, video_id="vid")

    conectar(ambiente)
    monkeypatch.setattr("forge.services.publicacao.publicar", falso)
    assert main(["publicar", str(run), "--titulo", "2", "--agendar", "2026-11-21T18:00-03:00"]) == 0
    assert pedidos["titulo"] == "B"
    assert pedidos["canal_id"] == "UC1"
    assert pedidos["publicar_em"].isoformat() == "2026-11-21T18:00:00-03:00"
    assert "https://studio.youtube.com/video/vid/edit" in capsys.readouterr().out


def test_publicar_erro_vira_exit_1_com_mensagem(ambiente, tmp_path, monkeypatch, capsys):
    from forge.cli import main
    from forge.services.youtube import YouTubeQuotaError

    def falso(*args, **kwargs):
        raise YouTubeQuotaError("Cota esgotada")

    conectar(ambiente)
    monkeypatch.setattr("forge.services.publicacao.publicar", falso)
    assert main(["publicar", str(tmp_path)]) == 1
    assert "Cota esgotada" in capsys.readouterr().err


def test_publicar_titulo_indice_fora_da_lista(ambiente, tmp_path, capsys):
    from forge.cli import main
    (tmp_path / "video").mkdir()
    (tmp_path / "video" / "embalagem.json").write_text(json.dumps({
        "titulos": [{"texto": "A"}], "thumbnail": {"texto": "x", "prompt": "y"}, "descricao": "d",
    }), encoding="utf-8")
    assert main(["publicar", str(tmp_path), "--titulo", "3"]) == 1
    assert "título" in capsys.readouterr().err.lower()


def test_publicar_sem_canal_conectado_explica(ambiente, tmp_path, capsys):
    from forge.cli import main
    assert main(["publicar", str(tmp_path)]) == 1
    assert "forge auth youtube login" in capsys.readouterr().err


def test_publicar_canal_inexistente(ambiente, tmp_path, capsys):
    from forge.cli import main
    conectar(ambiente)
    assert main(["publicar", str(tmp_path), "--canal", "UC9"]) == 1
    assert "UC9" in capsys.readouterr().err
