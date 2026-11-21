"""Studio executor that resumes the narrative graph after typed research."""

from __future__ import annotations

import hashlib
import json
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from forge.agents.research import PassageEvidence, ResearchBundle
from forge.domain.execucao import (
    ArtifactOutput, GateFinding, GateResult, RunSnapshot, StageExecutionResult,
    StagePlan,
)
from forge.domain.models import Fonte, Roteiro, Secao
from forge.domain.roteiro import SECOES_NOMES
from forge.domain.operacao import StageName
from forge.executors.base import StageImplementation
from forge.executors.lm_studio import LMStudioManager
from forge.gpu.liberadores import montar_broker
from forge.infrastructure.config import Settings
from forge.llms.model import build_chat_model, build_review_model
from forge.orchestration.graph import build_graph
from forge.services.citacoes import derivar_citacoes, gravar_citacoes
from forge.services.persistencia import carregar_modelo, gravar_modelo
from forge.services.qualidade_roteiro import conferir_roteiro
from forge.services.storage import _render
from forge.services.artefatos import _ultimo, _corpo, _parse_blocos, ler_eixo
from forge.services.worker import EventSink
from pydantic import BaseModel, Field


class _ResearchEvidence(BaseModel):
    passages: list[PassageEvidence] = Field(default_factory=list)


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

    @staticmethod
    def _resume_content(context: RunSnapshot, bundle: ResearchBundle) -> dict:
        """Uma falha de transporte na revisão não deve descartar o texto salvo.

        Pesquisa refeita invalida a retomada do rascunho anterior. Arquivos
        incompletos também voltam ao planejamento normal.
        """
        if context.attempt <= 1:
            return {}
        draft = _ultimo(context.run_dir, "write")
        plan = _ultimo(context.run_dir, "plan")
        research = context.run_dir / "video/research.json"
        if draft is None or plan is None or not research.is_file():
            return {}
        research_markdown = _ultimo(context.run_dir, "research")
        research_time = research.stat().st_mtime_ns
        if research_markdown is not None:
            research_time = max(research_time, research_markdown.stat().st_mtime_ns)
        # Uma pesquisa posterior ao plano/rascunho invalida a retomada.
        # Um plano novo já gerado após essa pesquisa pode ser retomado.
        if min(draft.stat().st_mtime_ns, plan.stat().st_mtime_ns) < research_time:
            return {}
        sections = _parse_blocos(_corpo(draft.read_text(encoding="utf-8")), set(SECOES_NOMES))
        plan_text = plan.read_text(encoding="utf-8")
        planning = _parse_blocos(_corpo(plan_text), {"Tese", "Esboço"})
        if set(sections) != set(SECOES_NOMES) or not all(sections.values()) or not all(planning.get(k) for k in ("Tese", "Esboço")):
            return {}
        draft_json = draft.with_suffix(".json")
        if draft_json.is_file():
            roteiro_salvo = Roteiro.model_validate_json(draft_json.read_text(encoding="utf-8"))
            roteiro_salvo = roteiro_salvo.model_copy(update={
                "tema": context.tema, "tese": planning["Tese"],
            })
        else:
            # Explicit legacy load: no references are inferred from prose.
            roteiro_salvo = Roteiro(
                tema=context.tema, tese=planning["Tese"], fontes=bundle.fontes,
                secoes=[Secao(nome=name, conteudo=text) for name, text in sections.items()],
            )
        return {
            "tese": planning["Tese"], "esboco": planning["Esboço"],
            "eixo": ler_eixo(plan_text),
            "roteiro": roteiro_salvo,
        }

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
        # Trocar o revisor muda o roteiro aprovado: não pode reaproveitar. Só
        # entra quando existe de fato, para não mudar o hash das runs antigas.
        if self.settings.review_provider not in (None, self.settings.provider):
            payload["revisor"] = [self.settings.review_provider, self.settings.review_model]
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
        bundle = carregar_modelo(run_dir / "video" / "research.json", ResearchBundle)
        evidencia_path = run_dir / "video" / "research-evidence.json"
        if evidencia_path.is_file():
            passages = carregar_modelo(evidencia_path, _ResearchEvidence).passages
            fontes = [
                Fonte(titulo=p.title, autor=", ".join(p.authors) or None,
                      frase=p.text, path=p.path, book_id=p.book_id)
                for p in passages if p.path
            ]
            bundle = bundle.model_copy(update={
                "passages": passages, "fontes": fontes,
                "passage_count": len(passages),
                "canonical_paths": [p.path for p in passages if p.path],
            })
        return bundle

    @staticmethod
    def _write_artifacts(
        run_dir: Path, roteiro: Roteiro, settings: Settings, emit: EventSink,
        evidencias: list[PassageEvidence] | None = None,
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
        if evidencias is not None:
            gravar_modelo(
                run_dir / "video" / "research-evidence.json",
                _ResearchEvidence(passages=evidencias),
            )
            outputs.append(ArtifactOutput(
                item_key="", kind="research_evidence",
                relative_path="video/research-evidence.json",
                mime_type="application/json", metadata={"passages": len(evidencias)},
            ))
            # Auditoria de fontes: derivada dos blocos e das evidências, sem
            # modelo. A embalagem (descrição do vídeo) lê este arquivo.
            citacoes = derivar_citacoes(
                roteiro, [e for e in evidencias if isinstance(e, PassageEvidence)],
            )
            gravar_citacoes(run_dir, citacoes)
            outputs.append(ArtifactOutput(
                item_key="", kind="citacoes",
                relative_path="video/citacoes.json",
                mime_type="application/json", metadata={"citations": len(citacoes)},
            ))
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
        fluxo = context.fluxo_geracao
        model, broker = self._runtime()
        bundle = self._load_bundle(context.run_dir)
        resumed = self._resume_content(context, bundle)
        with broker.exclusivo("llm"):
            if self.settings.provider == "lm-studio":
                (self.lm_manager or LMStudioManager(self.settings)).ensure_loaded()
            graph = build_graph(
                model, self.settings, inicio="review" if resumed else "plan",
                revisor=build_review_model(self.settings),
                fluxo_geracao=fluxo,
            )
            state = graph.invoke({
                "tema": context.tema,
                "tese": context.tese or "",
                "research_notes": bundle.brief,
                "fontes": bundle.fontes,
                "research_passages": bundle.passages,
                "run_dir": context.run_dir,
                "rounds": 0,
                "passos": 0,
                "review": None,
                "pedido": None,
                **resumed,
            })
        roteiro = state.get("roteiro")
        if roteiro is None:
            raise RuntimeError("graph did not produce roteiro")
        self._roteiro = roteiro
        evidencias = list(state.get("research_passages", bundle.passages) or [])
        # A graph implementation from before the typed evidence field may only
        # expose refreshed ``fontes`` after a directed research loop.  Retain
        # those anchors as a compatibility bridge while the canonical path
        # evidence remains the preferred input.
        por_caminho = {
            getattr(item, "path", None): item for item in evidencias
            if getattr(item, "path", None)
        }
        for fonte in state.get("fontes", []) or []:
            caminho = getattr(fonte, "path", None)
            if caminho and caminho not in por_caminho:
                evidencias.append(fonte)
                por_caminho[caminho] = fonte
        evidencias = [
            item if isinstance(item, PassageEvidence) else (
                PassageEvidence.model_validate(item)
                if isinstance(item, dict) else item
            )
            for item in evidencias
        ]
        self._passages_by_section = {
            section.nome: list(evidencias) for section in roteiro.secoes
        }
        outputs = self._write_artifacts(context.run_dir, roteiro, self.settings, emit, evidencias)
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
