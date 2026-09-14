"""Studio doctor CLI: preflight checks and database health report."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from forge.infrastructure.config import get_settings
from forge.repositories.connection import Database
from forge.repositories.schema import init_db
from forge.services.preflight import check_preflight
from forge.services.redacao import Redactor


def _report_to_dict(report: object) -> dict:
    checks = []
    for c in report.checks:
        checks.append(
            {
                "name": c.name,
                "state": c.state,
                "message": c.message,
                "action": c.action,
            }
        )
    return {"ok": report.ok, "checks": checks}


def _serialize_for_json(report: object, redactor: Redactor) -> str:
    data = _report_to_dict(report)
    # Redact any secrets that may have leaked into stdout/stderr output
    serialized = json.dumps(data, indent=2, ensure_ascii=False)
    return redactor._redact_string(serialized)


def _serialize_for_human(report: object, redactor: Redactor) -> str:
    lines = []
    for check in report.checks:
        icon = {"passed": "PASS", "warning": "WARN", "failed": "FAIL"}.get(check.state, "???")  # noqa: E501
        line = f"[{icon}] {check.name}: {check.message}"
        if check.action and check.state != "passed":
            line += f"\n       -> {check.action}"
        lines.append(line)
    lines.append("")
    lines.append(f"Preflight {'OK' if report.ok else 'FAILED'}")
    raw = "\n".join(lines)
    return redactor._redact_string(raw)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="forge-studio-doctor",
        description="Studio health checks and preflight report",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="Initialize/migrate the SQLite schema before running checks",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    redactor = Redactor(secrets=settings.secret_values())

    if args.migrate:
        db = Database(settings.studio_db_path)
        init_db(db)
        print("SQLite schema 2 applied")

    report = check_preflight(settings)

    if args.json:
        output = _serialize_for_json(report, redactor)
    else:
        output = _serialize_for_human(report, redactor)

    print(output)
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
