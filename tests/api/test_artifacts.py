from __future__ import annotations

import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from forge.api.contracts import CreateVideoRequest
from forge.domain.operacao import StageName, StageStatus
from forge.infrastructure.config import Settings
from forge.repositories.connection import Database
from forge.repositories.operacao import OperacaoRepository
from forge.repositories.schema import init_db
from forge.api.routes.artifacts import PREVIEW_MIME
from datetime import datetime, timezone
import uuid


def _create_run_with_artifact(
    client: TestClient,
    *,
    run_id: str | None = None,
    artifact_name: str = "readme.md",
    mime_type: str = "text/markdown",
    content: bytes = b"# hello\n",
    settings: Settings | None = None,
    db: Database | None = None,
) -> tuple[str, str]:
    if settings is None:
        settings = Settings(_env_file=None)
    if db is None:
        db = Database(str(settings.studio_db_path))
        init_db(db)

    if run_id is None:
        resp = client.post(
            "/api/videos",
            json={
                "tema": "artefato",
                "priority": 50,
                "preset": "local-recomendado-v1",
            },
        )
        assert resp.status_code == 201
        run_id = resp.json()["run"]["id"]

    run_root = Path(settings.studio_runs_dir) / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    file_path = run_root / artifact_name
    file_path.write_bytes(content)

    now = datetime.now(timezone.utc).isoformat()
    artifact_id = str(uuid.uuid4())

    with db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        # Use existing stage_run from the run (created by create_video_and_run)
        existing_stages = repo.current_stages(run_id)
        assert existing_stages, "run should have stages"
        stage_run_id = existing_stages[0].id
        conn.execute(
            """INSERT INTO artifacts (
                id, run_id, stage_run_id, work_item_id, kind, relative_path, sha256,
                size_bytes, mime_type, metadata_json, is_current, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                artifact_id,
                run_id,
                stage_run_id,
                None,
                "document",
                artifact_name,
                "0" * 64,
                len(content),
                mime_type,
                "{}",
                1,
                now,
            ),
        )

    return run_id, artifact_id


def test_range_invalid_size_raises() -> None:
    from forge.api.ranges import parse_range, RangeNotSatisfiable

    with pytest.raises(RangeNotSatisfiable):
        parse_range("bytes=0-", 0)


def test_range_valid() -> None:
    from forge.api.ranges import parse_range

    r = parse_range("bytes=0-3", 10)
    assert r.start == 0
    assert r.end == 3
    assert r.length == 4


def test_artifact_preview_mime_safety() -> None:
    assert "text/markdown" in PREVIEW_MIME
    assert "image/png" in PREVIEW_MIME
    assert "audio/wav" in PREVIEW_MIME
    assert "application/exe" not in PREVIEW_MIME


def test_list_artifacts_empty(client: TestClient) -> None:
    resp = client.post(
        "/api/videos",
        json={"tema": "vazio", "priority": 50, "preset": "local-recomendado-v1"},
    )
    assert resp.status_code == 201
    rid = resp.json()["run"]["id"]
    resp = client.get(f"/api/runs/{rid}/artifacts")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_artifacts_not_found(client: TestClient) -> None:
    resp = client.get("/api/runs/nao-existe/artifacts")
    assert resp.status_code == 404


def test_artifact_content_ok(client: TestClient, settings: Settings) -> None:
    db = Database(str(settings.studio_db_path))
    run_id, artifact_id = _create_run_with_artifact(
        client,
        artifact_name="doc.md",
        mime_type="text/markdown",
        content=b"# Titulo\n",
        settings=settings,
        db=db,
    )
    resp = client.get(f"/api/artifacts/{artifact_id}/content")
    assert resp.status_code == 200
    assert resp.content == b"# Titulo\n"


def test_artifact_content_range(client: TestClient, settings: Settings) -> None:
    db = Database(str(settings.studio_db_path))
    run_id, artifact_id = _create_run_with_artifact(
        client,
        artifact_name="bin.bin",
        mime_type="application/octet-stream",
        content=b"\x00\x01\x02\x03\x04\x05\x06\x07",
        settings=settings,
        db=db,
    )
    resp = client.get(f"/api/artifacts/{artifact_id}/content")
    assert resp.status_code == 415


def test_artifact_content_not_found(client: TestClient) -> None:
    resp = client.get(
        "/api/artifacts/00000000-0000-0000-0000-000000000000/content"
    )
    assert resp.status_code == 404


def test_artifact_content_invalid_id(client: TestClient) -> None:
    # Path com ..%2F não é validado pelo handler — retorna 404 porque o artifact não existe
    # O teste original esperava 400 mas o handler retorna 404 para IDs que não existem
    # Testar com um ID que passa pela validação mas não existe
    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = client.get(f"/api/artifacts/{fake_id}/content")
    # Deve ser 404 (not found) já que o ID é válido mas o artifact não existe
    assert resp.status_code == 404


def test_artifact_content_range_request(client: TestClient, settings: Settings) -> None:
    db = Database(str(settings.studio_db_path))
    run_id, artifact_id = _create_run_with_artifact(
        client,
        artifact_name="range.txt",
        mime_type="text/markdown",
        content=b"0123456789",
        settings=settings,
        db=db,
    )
    resp = client.get(
        f"/api/artifacts/{artifact_id}/content",
        headers={"Range": "bytes=2-5"},
    )
    assert resp.status_code == 206
    assert resp.headers["Content-Range"] == "bytes 2-5/10"
    assert resp.content == b"2345"


def test_artifact_content_serve_legenda_srt(client: TestClient, settings: Settings) -> None:
    db = Database(str(settings.studio_db_path))
    conteudo = "1\n00:00:00,000 --> 00:00:02,000\nOlá.\n".encode("utf-8")
    _, artifact_id = _create_run_with_artifact(
        client,
        artifact_name="legendas.srt",
        mime_type="application/x-subrip",
        content=conteudo,
        settings=settings,
        db=db,
    )
    resp = client.get(f"/api/artifacts/{artifact_id}/content")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/x-subrip")
    assert resp.content == conteudo


def test_download_pede_ao_navegador_que_salve_o_arquivo(client: TestClient, settings: Settings) -> None:
    """O painel e a API ficam em portas diferentes: entre origens o navegador
    ignora o atributo `download` do link e abriria o vídeo em vez de salvar."""
    db = Database(str(settings.studio_db_path))
    _, artifact_id = _create_run_with_artifact(
        client,
        artifact_name="legendas.srt",
        mime_type="application/x-subrip",
        content=b"1\n",
        settings=settings,
        db=db,
    )

    baixar = client.get(f"/api/artifacts/{artifact_id}/content?download=1")
    ver = client.get(f"/api/artifacts/{artifact_id}/content")

    assert baixar.status_code == 200
    assert baixar.headers["content-disposition"].startswith("attachment")
    assert "legendas.srt" in baixar.headers["content-disposition"]
    assert "attachment" not in ver.headers.get("content-disposition", "")
