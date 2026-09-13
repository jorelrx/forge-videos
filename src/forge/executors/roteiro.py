"""Studio executor that resumes the narrative graph after typed research."""

from __future__ import annotations

import hashlib
import json
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from forge.agents.research import ResearchBundle
from forge.domain.execucao import (
    ArtifactOutput, GateFinding, GateResult, RunSnapshot, StageExecutionResult,
    StagePlan,
)
from forge.domain.models import Roteiro
from forge.domain.operacao import StageName
from forge.executors.base import StageImplementation
from forge.executors.lm_studio import LMStudioManager
from forge.gpu.liberadores import montar_broker
from forge.infrastructure.config import Settings
from forge.llms.model import build_chat_model
from forge.orchestration.graph import build_graph
from forge.services.persistencia import carregar_modelo, gravar_modelo
from forge.services.qualidade_roteiro import conferir_roteiro
from forge.services.storage import _render
from forge.services.worker import EventSink


class _NoopBroker:
    def exclusivo(self, recurso: str):
        return nullcontext()


class ScriptExecutor(StageImplementation):
    def __init__(
        self,
        *,
        model: Any | None = None,
        settings: Settings | None = None,
        broker: Any | None = None,
        lm_manager: LMStudioManager | None = None,
    ) -> None:
        self.settings = settings or Settings()
        self.model = model
        self.broker = broker
        self.lm_manager = lm_manager
        self._roteiro: Roteiro | dict[str, Any] | None = None
        self._passages_by_section: dict[str, list[Any]] = {}

    def prepare(self, context: RunSnapshot) -> StagePlan:
        if context.stage is not StageName.ROTEIRO:
            raise ValueError("context stage does not match script executor")
        research_artifacts = []
        for artifact in context.artifacts:
            value = artifact.model_dump(mode="json") if hasattr(artifact, "model_dump") else dict(artifact)
            if value.get("is_current") and (
                str(value.get("kind", "")).startswith("research")
                or str(value.get("relative_path", "")).startswith("video/research")
            ):
                research_artifacts.append(value)
        bundle_path = context.run_dir / "video" / "research.json"
        if bundle_path.is_file() and not research_artifacts:
            research_artifacts.append({
                "relative_path": "video/research.json",
                "sha256": hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
            })
        payload = {
            "research": research_artifacts,
            "model": self.settings.resolved_model,
            "preset": context.config_snapshot,
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return StagePlan(
            stage=StageName.ROTEIRO,
            input_hash=hashlib.sha256(encoded).hexdigest(),
            items=[],
        )

    def _runtime(self):
        model = self.model if self.model is not None else build_chat_model(self.settings)
        if self.broker is not None:
            broker = self.broker
        elif self.model is not None:
            broker = _NoopBroker()
        else:
            broker = montar_broker(self.settings)
        return model, broker

    @staticmethod
    def _load_bundle(run_dir: Path) -> ResearchBundle:
        return carregar_modelo(run_dir / "video" / "research.json", ResearchBundle)

    @staticmethod
    def _write_artifacts(
        run_dir: Path, roteiro: Roteiro, settings: Settings, emit: EventSink,
    ) -> list[ArtifactOutput]:
        structured = gravar_modelo(run_dir / "video" / "roteiro.json", roteiro)
        markdown = run_dir / "roteiro.md"
        markdown.parent.mkdir(parents=True, exist_ok=True)
        markdown.write_text(
            _render(roteiro, settings, rounds=None, aprovado=None, ts="studio"),
            encoding="utf-8",
        )
        outputs = [
            ArtifactOutput(
                item_key="", kind="roteiro", relative_path="video/roteiro.json",
                mime_type="application/json", metadata={"sections": len(roteiro.secoes)},
            ),
            ArtifactOutput(
                item_key="", kind="roteiro_markdown", relative_path="roteiro.md",
                mime_type="text/markdown", metadata={"sections": len(roteiro.secoes)},
            ),
        ]
        for output in outputs:
            emit(
                kind="artifact.created", level="info", message="Artefato criado",
                payload=output.model_dump(mode="json"),
            )
        if structured.resolve() != (run_dir / "video" / "roteiro.json").resolve():
            raise RuntimeError("script artifact path escaped canonical layout")
        return outputs

    def execute(
        self, context: RunSnapshot, plan: StagePlan, emit: EventSink
    ) -> StageExecutionResult:
        model, broker = self._runtime()
        bundle = self._load_bundle(context.run_dir)
        with broker.exclusivo("llm"):
            if self.settings.provider == "lm-studio":
                (self.lm_manager or LMStudioManager(self.settings)).ensure_loaded()
            graph = build_graph(model, self.settings, inicio="plan")
            state = graph.invoke({
                "tema": context.tema,
                "tese": context.tese or "",
                "research_notes": bundle.brief,
                "fontes": bundle.fontes,
                "run_dir": context.run_dir,
                "rounds": 0,
                "passos": 0,
                "review": None,
                "pedido": None,
            })
        roteiro = state.get("roteiro")
        if roteiro is None:
            raise RuntimeError("graph did not produce roteiro")
        self._roteiro = roteiro
        self._passages_by_section = {
            section.nome: list(bundle.passages) for section in roteiro.secoes
        }
        outputs = self._write_artifacts(context.run_dir, roteiro, self.settings, emit)
        return StageExecutionResult(
            current_items=1, total_items=1, artifacts=outputs,
        )

    def validate(
        self, context: RunSnapshot, plan: StagePlan, result: StageExecutionResult
    ) -> GateResult:
        if result.failure is not None:
            return GateResult(
                approved=False, code="script_gate_failed",
                findings=[GateFinding(code=result.failure.code, message=result.failure.message)],
            )
        if self._roteiro is None:
            return GateResult(
                approved=False, code="script_gate_failed",
                findings=[GateFinding(code="script_missing", message="Roteiro não produzido")],
            )
        report = conferir_roteiro(self._roteiro, self._passages_by_section)
        findings = [
            GateFinding(
                code=finding.code,
                message=finding.message,
                item_key=finding.section,
                details={**finding.details, "severity": finding.severity},
            )
            for finding in report.findings
            if finding.serious
        ]
        if not report.approved:
            return GateResult(
                approved=False, code="script_gate_failed", findings=findings,
                metrics=report.metrics,
            )
        return GateResult(
            approved=True, code="script_approved", metrics=report.metrics,
        )


__all__ = ["ScriptExecutor"]
