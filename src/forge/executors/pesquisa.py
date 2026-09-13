"""Research stage executor backed exclusively by the canonical acervo."""

from __future__ import annotations

from contextlib import nullcontext
import os
from pathlib import Path
from typing import Any

from forge.agents.research import ResearchBundle, pesquisar
from forge.domain.execucao import (
    ArtifactOutput,
    FailureDetail,
    FailureClass,
    GateFinding,
    GateResult,
    RunSnapshot,
    StageChildResult,
    StageExecutionResult,
    StagePlan,
)
from forge.domain.operacao import StageName
from forge.executors.base import StageImplementation
from forge.gpu.liberadores import montar_broker
from forge.infrastructure.config import Settings
from forge.llms.model import build_chat_model
from forge.services.acervo import Acervo, AcervoIndisponivel
from forge.services.artefatos import _render
from forge.services.persistencia import gravar_modelo
from forge.services.worker import EventSink


class _NoopBroker:
    def exclusivo(self, recurso: str):
        return nullcontext()


def _gravar_texto_atomico(destino: Path, conteudo: str) -> Path:
    """Replace a markdown artifact atomically in its destination directory."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_suffix(destino.suffix + ".tmp")
    temporario.write_text(conteudo, encoding="utf-8")
    os.replace(temporario, destino)
    return destino


class ResearchExecutor(StageImplementation):
    def __init__(
        self,
        *,
        model: Any | None = None,
        acervo: Any | None = None,
        settings: Settings | None = None,
        broker: Any | None = None,
        minimum_sources: int | None = None,
    ) -> None:
        self.settings = settings or Settings()
        self.model = model
        self.acervo = acervo
        self.broker = broker
        self.minimum_sources = (
            minimum_sources
            if minimum_sources is not None
            else self.settings.research_min_sources
        )
        if self.minimum_sources <= 0:
            raise ValueError("minimum_sources must be positive")
        self._bundle: ResearchBundle | None = None

    def prepare(self, context: RunSnapshot) -> StagePlan:
        if context.stage is not StageName.PESQUISA:
            raise ValueError("context stage does not match research executor")
        # Research is a single stage-level operation. Its input hash still
        # comes from the immutable run snapshot through the parent protocol.
        import hashlib
        import json

        payload = {
            "run_id": context.run_id,
            "video_id": context.video_id,
            "tema": context.tema,
            "tese": context.tese,
            "config_snapshot": context.config_snapshot,
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return StagePlan(
            stage=StageName.PESQUISA,
            input_hash=hashlib.sha256(encoded).hexdigest(),
            items=[],
        )

    def _runtime(self):
        model = self.model if self.model is not None else build_chat_model(self.settings)
        acervo = self.acervo if self.acervo is not None else Acervo(
            self.settings.acervo_url, timeout=self.settings.acervo_timeout
        )
        if self.broker is not None:
            broker = self.broker
        elif self.model is not None or self.acervo is not None:
            # Tests and embedded callers inject the external boundaries. They
            # must not accidentally claim a machine-wide GPU lock.
            broker = _NoopBroker()
        else:
            broker = montar_broker(self.settings)
        return model, acervo, broker

    def execute(
        self, context: RunSnapshot, plan: StagePlan, emit: EventSink
    ) -> StageExecutionResult:
        model, acervo, broker = self._runtime()
        try:
            with broker.exclusivo("llm"):
                bundle = pesquisar(
                    model,
                    context.tema,
                    acervo,
                    top=self.settings.acervo_top,
                    settings=self.settings,
                    run_dir=context.run_dir,
                )
            self._bundle = bundle
            paths = self._write_artifacts(context.run_dir, bundle, emit)
            return StageExecutionResult(
                current_items=1,
                total_items=1,
                artifacts=paths,
            )
        except AcervoIndisponivel:
            return StageExecutionResult(
                current_items=0,
                total_items=1,
                failure=FailureDetail(
                    code="research_unavailable",
                    message="Acervo indisponível para pesquisa",
                    failure_class=FailureClass.TRANSIENT,
                    retriable=True,
                    recommended_action="Verificar o serviço acervo e tentar novamente",
                    adapter="acervo",
                    attempt=context.attempt,
                    stack_trace="",
                    services={"acervo": "unavailable"},
                ),
            )

    @staticmethod
    def _write_artifacts(
        run_dir: Path, bundle: ResearchBundle, emit: EventSink
    ) -> list[ArtifactOutput]:
        human = _gravar_texto_atomico(
            run_dir / "01-research.md",
            _render(
                "research",
                {"fontes": bundle.fontes, "research_notes": bundle.brief},
            ),
        )
        raw = _gravar_texto_atomico(
            run_dir / "01-research.raw.md", bundle.raw_markdown
        )
        structured = gravar_modelo(run_dir / "video" / "research.json", bundle)
        outputs = [
            ArtifactOutput(
                item_key="",
                kind="research",
                relative_path="01-research.md",
                mime_type="text/markdown",
                metadata={
                    "passage_count": bundle.passage_count,
                    "canonical_source_count": len(bundle.canonical_paths),
                    "unanswered_query_count": len(bundle.unanswered_queries),
                },
            ),
            ArtifactOutput(
                item_key="",
                kind="research_raw",
                relative_path="01-research.raw.md",
                mime_type="text/markdown",
                metadata={
                    "passage_count": bundle.passage_count,
                    "canonical_source_count": len(bundle.canonical_paths),
                },
            ),
            ArtifactOutput(
                item_key="",
                kind="research_bundle",
                relative_path="video/research.json",
                mime_type="application/json",
                metadata={
                    "passage_count": bundle.passage_count,
                    "canonical_source_count": len(bundle.canonical_paths),
                    "unanswered_query_count": len(bundle.unanswered_queries),
                },
            ),
        ]
        # Keep the writes above explicit and verify their paths are the exact
        # canonical outputs before announcing them to the parent projector.
        actual = [human, raw, structured]
        expected = [run_dir / p.relative_path for p in outputs]
        if [p.resolve() for p in actual] != [p.resolve() for p in expected]:
            raise RuntimeError("research artifact path escaped canonical layout")
        for output in outputs:
            emit(
                kind="artifact.created",
                level="info",
                message="Artefato criado",
                payload=output.model_dump(mode="json"),
            )
        return outputs

    def validate(
        self,
        context: RunSnapshot,
        plan: StagePlan,
        result: StageExecutionResult,
    ) -> GateResult:
        if result.failure is not None:
            return GateResult(
                approved=False,
                code="research_gate_failed",
                findings=[
                    GateFinding(
                        code=result.failure.code,
                        message=result.failure.message,
                    )
                ],
            )
        bundle = self._bundle
        if bundle is None:
            return GateResult(
                approved=False,
                code="research_gate_failed",
                findings=[
                    GateFinding(
                        code="research_unavailable",
                        message="Pesquisa não produziu resultado",
                    )
                ],
            )
        findings: list[GateFinding] = []
        if any(not fonte.path or not fonte.path.strip() for fonte in bundle.fontes):
            findings.append(
                GateFinding(
                    code="research_source_missing_path",
                    message="Fonte de pesquisa sem caminho canônico",
                )
            )
        evidence_paths = {passage.path for passage in bundle.passages if passage.path}
        if any(fonte.path and fonte.path not in evidence_paths for fonte in bundle.fontes):
            findings.append(
                GateFinding(
                    code="research_source_fabricated",
                    message="Fonte não corresponde à evidência retornada pelo acervo",
                )
            )
        unique_paths = set(bundle.canonical_paths)
        if len(unique_paths) < self.minimum_sources:
            findings.append(
                GateFinding(
                    code="research_minimum_not_met",
                    message="Pesquisa não atingiu o mínimo de fontes canônicas",
                    details={
                        "found": len(unique_paths),
                        "required": self.minimum_sources,
                    },
                )
            )
        metrics = {
            "passage_count": bundle.passage_count,
            "canonical_source_count": len(unique_paths),
            "unanswered_query_count": len(bundle.unanswered_queries),
        }
        if findings:
            return GateResult(
                approved=False,
                code="research_gate_failed",
                findings=findings,
                metrics=metrics,
            )
        return GateResult(approved=True, code="research_ready", metrics=metrics)


__all__ = ["ResearchExecutor"]
