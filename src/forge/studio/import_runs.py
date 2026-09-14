"""CLI forge-import-runs: cataloga runs legadas como histórico somente-leitura."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from forge.infrastructure.config import get_settings
from forge.repositories.connection import Database
from forge.repositories.schema import init_db
from forge.services.importador import LegacyImportError, LegacyRunImporter


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="forge-import-runs",
        description="Importa runs legadas como cópias catalogadas e imutáveis.",
    )
    parser.add_argument(
        "path",
        help="Diretório de uma run legada, ou o diretório pai com --children.",
    )
    parser.add_argument(
        "--children",
        action="store_true",
        help="Importa cada filho direto (diretório) em ordem de nome.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    settings = get_settings()
    db = Database(settings.studio_db_path)
    init_db(db)
    importer = LegacyRunImporter(db, output_root=settings.studio_runs_dir)

    target = Path(args.path)

    if args.children:
        children = sorted(path for path in target.iterdir() if path.is_dir())
        failed = False
        for child in children:
            try:
                result = importer.import_one(child)
            except (LegacyImportError, OSError) as error:
                print(f"ERRO {child.name}: {error}", file=sys.stderr)
                failed = True
                continue
            print(
                f"{result.run_id} {result.copied_files} "
                f"{result.skipped_files} {result.already_imported}"
            )
        return 1 if failed else 0

    result = importer.import_one(target)
    print(
        f"{result.run_id} {result.copied_files} "
        f"{result.skipped_files} {result.already_imported}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
