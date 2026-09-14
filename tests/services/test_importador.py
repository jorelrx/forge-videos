from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.domain.operacao import Artifact, ETAPAS, RunStatus, StageName, StageStatus
from forge.repositories.connection import Database
from forge.repositories.operacao import OperacaoRepository
from forge.repositories.schema import init_db
from forge.services.importador import (
    LEGACY_NAMESPACE,
    ImportedRun,
    LegacyImportError,
    LegacyRunImporter,
    legacy_run_id,
)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "forge.db")
    init_db(database)
    return database


@pytest.fixture
def legacy_run(tmp_path):
    legacy = tmp_path / "legacy" / "20260913-liberdade"
    legacy.mkdir(parents=True)

    (legacy / "00-tema.md").write_text("# Tema\n\nConteudo do tema.")
    (legacy / "01-research.md").write_text("# Research\n\nFontes...")
    (legacy / "03-write-r1.md").write_text("# Roteiro v1\n\nCena 1...")
    (legacy / "04-review-r1.md").write_text("# Review v1\n\nAprovado.")

    video = legacy / "video"
    video.mkdir()
    (video / "midia.json").write_text(json.dumps({"beats": []}))
    (video / "roteiro.md").write_text("# Roteiro final\n\nCena 1...")

    audio = video / "audio"
    audio.mkdir()
    (audio / "b001.wav").write_bytes(b"\x00" * 100)

    images = video / "images"
    images.mkdir()
    (images / "beat-001.png").write_bytes(b"\x00" * 100)

    (video / "final.mp4").write_bytes(b"\x00" * 1000)
    (video / "validation.json").write_text(json.dumps({"approved": True, "findings": []}))

    return legacy


class TestLegacyRunId:
    def test_same_source_produces_same_id(self, legacy_run):
        assert legacy_run_id(legacy_run) == legacy_run_id(legacy_run)

    def test_different_sources_produce_different_ids(self, tmp_path):
        a = tmp_path / "a"
        a.mkdir()
        b = tmp_path / "b"
        b.mkdir()
        assert legacy_run_id(a) != legacy_run_id(b)

    def test_id_is_uuid_string(self, legacy_run):
        rid = legacy_run_id(legacy_run)
        assert isinstance(rid, str)
        assert len(rid) == 36


class TestImportOne:
    def test_import_copies_known_files_and_registers_history(self, db, legacy_run, tmp_path):
        importer = LegacyRunImporter(db, output_root=tmp_path / "runs")
        imported = importer.import_one(legacy_run)

        assert imported.copied_files > 0
        assert imported.skipped_files == 0
        assert imported.already_imported is False

        run_dir = tmp_path / "runs" / imported.run_id
        assert (run_dir / "video" / "midia.json").is_file()
        assert (run_dir / "video" / "final.mp4").is_file()
        assert (run_dir / "00-tema.md").is_file()

        # Source is preserved
        assert (legacy_run / "video" / "final.mp4").is_file()

    def test_imported_run_is_read_only_and_completed(self, db, legacy_run, tmp_path):
        importer = LegacyRunImporter(db, output_root=tmp_path / "runs")
        imported = importer.import_one(legacy_run)

        with db.connection() as conn:
            run = OperacaoRepository(conn).get_run(imported.run_id)

        assert run is not None
        assert run.status is RunStatus.COMPLETED
        assert run.is_read_only is True
        assert run.finished_at is not None

    def test_imported_run_has_artifacts_for_known_files(self, db, legacy_run, tmp_path):
        importer = LegacyRunImporter(db, output_root=tmp_path / "runs")
        imported = importer.import_one(legacy_run)

        with db.connection() as conn:
            artifacts = OperacaoRepository(conn).list_artifacts(imported.run_id, current_only=False)

        paths = {a.relative_path for a in artifacts}
        assert "00-tema.md" in paths
        assert "video/midia.json" in paths
        assert "video/final.mp4" in paths

    def test_imported_stages_have_correct_statuses(self, db, legacy_run, tmp_path):
        importer = LegacyRunImporter(db, output_root=tmp_path / "runs")
        imported = importer.import_one(legacy_run)

        with db.connection() as conn:
            stages = OperacaoRepository(conn).current_stages(imported.run_id)

        stages_by_name = {s.stage: s for s in stages}
        assert stages_by_name[StageName.PREPARACAO].status is StageStatus.SUCCEEDED
        assert stages_by_name[StageName.PESQUISA].status is StageStatus.SUCCEEDED
        assert stages_by_name[StageName.ROTEIRO].status is StageStatus.SUCCEEDED
        assert stages_by_name[StageName.PLANO_MIDIA].status is StageStatus.SUCCEEDED
        assert stages_by_name[StageName.AUDIO].status is StageStatus.SUCCEEDED
        assert stages_by_name[StageName.IMAGENS].status is StageStatus.SUCCEEDED
        assert stages_by_name[StageName.MONTAGEM].status is StageStatus.SUCCEEDED
        assert stages_by_name[StageName.VALIDACAO].status is StageStatus.SUCCEEDED

    def test_import_same_source_is_idempotent(self, db, legacy_run, tmp_path):
        importer = LegacyRunImporter(db, output_root=tmp_path / "runs")
        first = importer.import_one(legacy_run)
        second = importer.import_one(legacy_run)

        assert first.run_id == second.run_id
        assert second.already_imported is True

        with db.connection() as conn:
            count = OperacaoRepository(conn).count_runs()
        assert count == 1

    def test_import_rejects_symlink_and_leaves_database_and_output_unchanged(
        self, db, legacy_run, tmp_path
    ):
        outside = tmp_path / "outside.mp4"
        outside.write_bytes(b"outside content")
        try:
            (legacy_run / "video" / "escape.mp4").symlink_to(outside)
        except OSError as error:
            pytest.skip(f"symlink exige privilégio neste host: {error}")

        importer = LegacyRunImporter(db, output_root=tmp_path / "runs")

        with pytest.raises(LegacyImportError, match="symlink"):
            importer.import_one(legacy_run)

        assert not list((tmp_path / "runs").glob("*"))
        with db.connection() as conn:
            assert OperacaoRepository(conn).count_runs() == 0

    def test_import_rejects_symlink_even_when_host_cannot_create_one(
        self, db, legacy_run, tmp_path, monkeypatch
    ):
        """A varredura recusa symlink mesmo onde o SO nega criá-lo (Windows sem privilégio)."""
        from pathlib import Path as _Path

        real_is_symlink = _Path.is_symlink

        def fake_is_symlink(self: _Path) -> bool:
            if self.name == "b001.wav":
                return True
            return real_is_symlink(self)

        monkeypatch.setattr(_Path, "is_symlink", fake_is_symlink)

        importer = LegacyRunImporter(db, output_root=tmp_path / "runs")
        with pytest.raises(LegacyImportError, match="symlink"):
            importer.import_one(legacy_run)

        assert not list((tmp_path / "runs").glob("*"))
        with db.connection() as conn:
            assert OperacaoRepository(conn).count_runs() == 0

    def test_import_skips_unwanted_files(self, db, legacy_run, tmp_path):
        (legacy_run / "video" / "parcial.json").write_text("{}")
        (legacy_run / "video" / "something.tmp").write_text("temp")
        (legacy_run / "00-tema.raw.md").write_text("raw")

        importer = LegacyRunImporter(db, output_root=tmp_path / "runs")
        imported = importer.import_one(legacy_run)

        assert imported.skipped_files == 3
        run_dir = tmp_path / "runs" / imported.run_id
        assert not (run_dir / "video" / "parcial.json").exists()
        assert not (run_dir / "video" / "something.tmp").exists()
        assert not (run_dir / "00-tema.raw.md").exists()

    def test_import_creates_stages_for_foreign_keys(self, db, legacy_run, tmp_path):
        importer = LegacyRunImporter(db, output_root=tmp_path / "runs")
        imported = importer.import_one(legacy_run)

        with db.connection() as conn:
            stages = OperacaoRepository(conn).current_stages(imported.run_id)

        assert len(stages) == len(ETAPAS)
