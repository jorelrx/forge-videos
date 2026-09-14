"""Importa runs legadas como cópias catalogadas e imutáveis.

A origem nunca é movida, alterada nem apagada: catalogar histórico é uma
operação de leitura sobre ela. A run resultante é `COMPLETED` e
`is_read_only=True`, de modo que o control plane recusa comandos mutáveis.
"""
from __future__ import annotations

import mimetypes
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from forge.domain.operacao import (
    ETAPAS,
    Artifact,
    StageName,
    StageStatus,
)
from forge.repositories.connection import Database
from forge.repositories.eventos import EventosRepository
from forge.repositories.operacao import OperacaoRepository
from forge.services.catalogo import sha256_file

# Namespace fixo: o mesmo diretório de origem resolve para o mesmo run-id,
# o que torna a importação idempotente sem expor o path como identidade.
LEGACY_NAMESPACE = uuid.UUID("fd455955-b4e7-4b1d-a816-a30a6bc443e1")

SKIP_SUFFIXES = (".tmp",)
SKIP_EXACT_NAMES = frozenset({"parcial.json"})

# Regra fechada de mapeamento: path relativo -> etapa. Um arquivo fora deste
# mapa e fora de `video/` cai em `preparacao` com kind `legacy.unknown`.
PATH_TO_STAGE: dict[str, StageName] = {
    "00-tema.md": StageName.PREPARACAO,
    "02-plan.md": StageName.PREPARACAO,
    "01-research.md": StageName.PESQUISA,
    "01-research-r1.md": StageName.PESQUISA,
    "03-write-r1.md": StageName.ROTEIRO,
    "04-review-r1.md": StageName.ROTEIRO,
    "roteiro.md": StageName.ROTEIRO,
}

# Subdiretório de `video/` -> etapa. Arquivos diretamente em `video/` são
# resolvidos por nome em `_resolve_video_file_stage`.
VIDEO_DIR_TO_STAGE: dict[str, StageName] = {
    "audio": StageName.AUDIO,
    "images": StageName.IMAGENS,
}

VIDEO_FILE_TO_STAGE: dict[str, StageName] = {
    "final.mp4": StageName.MONTAGEM,
    "validation.json": StageName.VALIDACAO,
    "midia.json": StageName.PLANO_MIDIA,
    "roteiro.md": StageName.ROTEIRO,
}


def legacy_run_id(source: Path) -> str:
    """ID determinístico e não reversível para o diretório de origem."""
    return str(uuid.uuid5(LEGACY_NAMESPACE, str(source.resolve(strict=True)).casefold()))


@dataclass(frozen=True)
class ImportedRun:
    run_id: str
    copied_files: int
    skipped_files: int
    already_imported: bool


class LegacyImportError(Exception):
    pass


class LegacyRunImporter:
    def __init__(
        self,
        db: Database,
        *,
        output_root: Path,
        now: datetime | None = None,
    ) -> None:
        self.db = db
        self.output_root = Path(output_root)
        self.now = now or datetime.now(UTC)

    # ------------------------------------------------------------------
    # Validação da árvore
    # ------------------------------------------------------------------

    def _validate_source_tree(self, source: Path) -> tuple[Path, list[Path]]:
        """Valida a origem inteira antes de qualquer cópia.

        Recusa symlink em qualquer ponto — um link aponta para fora da origem
        e copiaria conteúdo não catalogável por um path que mente sobre sua
        procedência.
        """
        resolved = source.resolve(strict=True)
        if resolved.is_symlink():
            raise LegacyImportError("symlink não permitido como source")
        if not resolved.is_dir():
            raise LegacyImportError(f"source não é diretório: {resolved}")

        files: list[Path] = []
        for path in sorted(resolved.rglob("*")):
            if path.is_symlink():
                raise LegacyImportError(
                    f"symlink encontrado: {path.relative_to(resolved)}"
                )
            if path.is_file():
                files.append(path)
        return resolved, files

    @staticmethod
    def _should_skip(relative: str) -> bool:
        name = Path(relative).name
        return (
            name.startswith(".stage-")
            or name.endswith(SKIP_SUFFIXES)
            or name.endswith(".raw.md")
            or name in SKIP_EXACT_NAMES
        )

    # ------------------------------------------------------------------
    # Mapeamento path -> etapa/kind
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_stage(relative: str) -> StageName:
        parts = Path(relative).parts
        if parts[0] == "video":
            if len(parts) >= 2:
                if parts[1] in VIDEO_DIR_TO_STAGE:
                    return VIDEO_DIR_TO_STAGE[parts[1]]
                if parts[-1] in VIDEO_FILE_TO_STAGE and len(parts) == 2:
                    return VIDEO_FILE_TO_STAGE[parts[-1]]
            return StageName.PREPARACAO
        return PATH_TO_STAGE.get(parts[0], StageName.PREPARACAO)

    # ------------------------------------------------------------------
    # Importação
    # ------------------------------------------------------------------

    def import_one(self, source: Path) -> ImportedRun:
        resolved, files = self._validate_source_tree(source)
        run_id = legacy_run_id(resolved)

        with self.db.connection() as conn:
            if OperacaoRepository(conn).get_run(run_id) is not None:
                return ImportedRun(
                    run_id=run_id,
                    copied_files=0,
                    skipped_files=0,
                    already_imported=True,
                )

        to_copy: list[tuple[Path, str]] = []
        skipped = 0
        for file_path in files:
            relative = file_path.relative_to(resolved).as_posix()
            if self._should_skip(relative):
                skipped += 1
                continue
            to_copy.append((file_path, relative))

        run_dir = self.output_root / run_id
        try:
            for src, relative in to_copy:
                dest = run_dir / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)

            copied = self._catalogue(run_id, run_dir, resolved, to_copy, skipped)
        except Exception:
            # A transação já reverteu o banco; a cópia parcial é nossa e nova.
            shutil.rmtree(run_dir, ignore_errors=True)
            raise

        return ImportedRun(
            run_id=run_id,
            copied_files=copied,
            skipped_files=skipped,
            already_imported=False,
        )

    def _catalogue(
        self,
        run_id: str,
        run_dir: Path,
        source: Path,
        to_copy: list[tuple[Path, str]],
        skipped: int,
    ) -> int:
        with self.db.transaction(immediate=True) as conn:
            operacao = OperacaoRepository(conn)
            eventos = EventosRepository(conn)

            operations = operacao.create_imported_video_and_run(
                tema=source.name,
                tese=None,
                config_snapshot={
                    "legacy_import": True,
                    "legacy_source_name": source.name,
                    "imported_at": self.now.isoformat(),
                    "workflow_version": 1,
                },
                git_commit="legacy-import",
                run_id=run_id,
            )
            run = operations[1]

            stages_by_name = {s.stage: s for s in operacao.current_stages(run.id)}
            stages_with_files: set[StageName] = set()

            for _, relative in to_copy:
                stage = self._resolve_stage(relative)
                stage_run = stages_by_name.get(stage)
                dest = run_dir / relative
                mime_type = mimetypes.guess_type(relative)[0] or "application/octet-stream"

                operacao.register_artifact(
                    Artifact(
                        id=str(uuid.uuid4()),
                        run_id=run.id,
                        stage_run_id=stage_run.id if stage_run else None,
                        work_item_id=None,
                        kind=_kind_for(relative),
                        relative_path=relative,
                        sha256=sha256_file(dest),
                        size_bytes=dest.stat().st_size,
                        mime_type=mime_type,
                        metadata={"legacy_import": True},
                        is_current=True,
                        created_at=self.now,
                    )
                )

                if stage_run is not None:
                    stages_with_files.add(stage)
                    operacao.save_stage(
                        stage_run.model_copy(
                            update={
                                "status": StageStatus.SUCCEEDED,
                                "gate_status": "imported_unverified",
                                "progress": 1.0,
                                "current_items": 1,
                                "total_items": 1,
                                "finished_at": self.now,
                            }
                        )
                    )

            # Etapa sem arquivo importado não atesta nada: fica inválida, não
            # pendente, para que nenhum leitor a interprete como trabalho a fazer.
            for stage_name in ETAPAS:
                if stage_name in stages_with_files:
                    continue
                stage_run = stages_by_name.get(stage_name)
                if stage_run is not None:
                    operacao.save_stage(
                        stage_run.model_copy(
                            update={"status": StageStatus.INVALIDATED}
                        )
                    )

            eventos.append(
                kind="run.imported",
                level="info",
                message="Run legada importada como histórico",
                payload={"copied_files": len(to_copy), "skipped_files": skipped},
                run_id=run.id,
            )

        return len(to_copy)


def _kind_for(relative: str) -> str:
    path = Path(relative)
    suffix = path.suffix.lower()
    name = path.name.lower()

    if suffix == ".md":
        return "roteiro_markdown" if "roteiro" in name else "legacy.markdown"
    if suffix == ".json":
        if "validation" in name:
            return "validation.report"
        if "midia" in name:
            return "media_plan"
        if "research" in name:
            return "research"
        return "legacy.json"
    if suffix == ".wav":
        return "audio.wav"
    if suffix == ".mp4":
        return "video/final.mp4"
    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        return f"image.{suffix.lstrip('.')}"
    return f"legacy.{suffix.lstrip('.')}" if suffix else "legacy.unknown"


__all__ = [
    "LEGACY_NAMESPACE",
    "ImportedRun",
    "LegacyImportError",
    "LegacyRunImporter",
    "legacy_run_id",
]
