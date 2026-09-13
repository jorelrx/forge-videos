"""Allowlisted child-process dispatcher for Studio stages."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any

from forge.domain.execucao import RunSnapshot, StageChildResult
from forge.domain.operacao import StageName

IMPLEMENTATIONS = {
    StageName.PREPARACAO: "forge.executors.preparacao:PreparationExecutor",
    StageName.PESQUISA: "forge.executors.pesquisa:ResearchExecutor",
    StageName.ROTEIRO: "forge.executors.roteiro:ScriptExecutor",
    StageName.PLANO_MIDIA: "forge.executors.plano_midia:MediaPlanExecutor",
    StageName.AUDIO: "forge.executors.audio:AudioExecutor",
    StageName.IMAGENS: "forge.executors.imagens:ImageExecutor",
    StageName.MONTAGEM: "forge.executors.montagem:ComposeExecutor",
    StageName.VALIDACAO: "forge.executors.validacao:ValidationExecutor",
}


def emit(*, kind: str, level: str, message: str, payload: dict) -> None:
    line = {"kind": kind, "level": level, "message": message, "payload": payload}
    print(json.dumps(line, ensure_ascii=False), flush=True)


def _absolute_context(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("context must be an absolute path")
    return path


def _implementation(stage: StageName) -> Any:
    target = IMPLEMENTATIONS[stage]
    module_name, class_name = target.split(":", 1)
    return getattr(importlib.import_module(module_name), class_name)()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="forge-stage")
    parser.add_argument("--context", required=True, type=_absolute_context)
    parser.add_argument(
        "--stage",
        required=True,
        choices=[stage.value for stage in IMPLEMENTATIONS],
    )
    args = parser.parse_args(argv)
    stage = StageName(args.stage)

    try:
        snapshot = RunSnapshot.model_validate_json(args.context.read_text(encoding="utf-8"))
        if snapshot.stage is not stage:
            raise ValueError(
                f"stage flag {stage.value!r} does not match context stage "
                f"{snapshot.stage.value!r}"
            )
        implementation = _implementation(stage)
        result = implementation.run(snapshot, emit)
        child_result = StageChildResult.model_validate(result)
        emit(
            kind="stage.result",
            level="info",
            message="Etapa concluída",
            payload=child_result.model_dump(mode="json"),
        )
        return 0
    except Exception as error:  # noqa: BLE001 - child reports diagnostics on stderr
        print(f"stage executor failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["IMPLEMENTATIONS", "emit", "main"]
