"""Executor do plano de mídia do Studio.

O roteiro é a única fonte da narração. O fatiamento é determinístico e o
modelo só propõe a imagem que acompanha cada bloco, antes de a fase de GPU
começar. ``midia.json`` é um snapshot legível; o estado de execução pertence
às work items persistidas pelo plano operacional.
"""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from forge.agents.midia import (
    CoberturaInsuficiente,
    _conferir_cobertura_relativa,
    _conferir_narracao_absoluta,
    gravar_plano,
    planejar_midia,
)
from forge.domain.execucao import (
    ArtifactOutput,
    FailureClass,
    FailureDetail,
    GateFinding,
    GateResult,
    RunSnapshot,
    StageExecutionResult,
    StagePlan,
    WorkItemPlan,
)
from forge.domain.midia import PlanoMidia
from forge.domain.models import Roteiro, Secao
from forge.domain.roteiro import SECOES_NOMES
from forge.domain.operacao import StageName
from forge.executors.base import StageImplementation
from forge.executors.lm_studio import LMStudioManager
from forge.gpu.liberadores import montar_broker
from forge.infrastructure.config import Settings
from forge.llms.model import build_chat_model
from forge.services.artefatos import _parse_blocos
from forge.services.persistencia import carregar_modelo
from forge.services.worker import EventSink


class _NoopBroker:
    def exclusivo(self, recurso: str):
        return nullcontext()


_ID = re.compile(r"^[bi][0-9]+$")


def hash_json(value: Any) -> str:
    """Hash a JSON-compatible value using the canonical media encoding."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


_hash_json = hash_json


def _artifact_value(artifact: Any) -> dict[str, Any]:
    if hasattr(artifact, "model_dump"):
        return artifact.model_dump(mode="json")
    return dict(artifact)


def _script_artifacts(context: RunSnapshot) -> list[dict[str, Any]]:
    result = []
    for artifact in context.artifacts:
        value = _artifact_value(artifact)
        kind = str(value.get("kind", ""))
        path = str(value.get("relative_path", ""))
        if value.get("is_current") and (
            kind.startswith("roteiro")
            or path in {"roteiro.md", "video/roteiro.json"}
        ):
            result.append(value)
    if result:
        return result
    # Embedded callers and old snapshots may not have registered artifacts yet.
    # Hash the bytes so a changed approved script cannot reuse the old plan.
    for relative in ("video/roteiro.json", "roteiro.md"):
        path = context.run_dir / relative
        if path.is_file():
            result.append({
                "relative_path": relative,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            })
    return result


def _plan_work_items(plan: PlanoMidia) -> list[WorkItemPlan]:
    """Derive downstream item inputs from the exact persisted media objects."""
    return [
        WorkItemPlan(
            item_key=block.id,
            input=block.model_dump(mode="json"),
            input_hash=hash_json(block),
        )
        for block in plan.blocos
    ] + [
        WorkItemPlan(
            item_key=beat.id,
            input=beat.model_dump(mode="json"),
            input_hash=hash_json(beat),
        )
        for beat in plan.beats
    ]


class MediaPlanExecutor(StageImplementation):
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
        self._plano: PlanoMidia | None = None
        self._work_item_plans: list[WorkItemPlan] = []

    @property
    def work_item_plans(self) -> list[WorkItemPlan]:
        """The audio/image inputs derived from the current media snapshot."""
        return list(self._work_item_plans)

    def prepare(self, context: RunSnapshot) -> StagePlan:
        if context.stage is not StageName.PLANO_MIDIA:
            raise ValueError("context stage does not match media-plan executor")
        payload = {
            "script": _script_artifacts(context),
            "model": self.settings.resolved_model,
            "media_settings": {
                "midia_alvo_segundos": self.settings.midia_alvo_segundos,
                # Visual/image knobs live in the immutable preset snapshot;
                # keeping it in ``preset`` above makes any future knob hash
                # visible without depending on a Settings field that does not
                # exist in the legacy CLI.
            },
            "preset": context.config_snapshot,
        }
        return StagePlan(
            stage=StageName.PLANO_MIDIA,
            input_hash=hash_json(payload),
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
    def _load_roteiro(context: RunSnapshot) -> Roteiro:
        structured = context.run_dir / "video" / "roteiro.json"
        if structured.is_file():
            return carregar_modelo(structured, Roteiro)

        markdown = context.run_dir / "roteiro.md"
        if not markdown.is_file():
            raise FileNotFoundError(
                "roteiro aprovado ausente (video/roteiro.json ou roteiro.md)"
            )
        text = markdown.read_text(encoding="utf-8")
        parts = text.split("---", 2)
        if len(parts) == 3:
            frontmatter, body = parts[1], parts[2]
        else:
            frontmatter, body = "", text
        tese = context.tese or ""
        match = re.search(r"^tese:\s*(.*?)\s*$", frontmatter, re.MULTILINE)
        if match:
            tese = match.group(1)
        secoes = _parse_blocos(body, set(SECOES_NOMES))
        if not secoes:
            raise ValueError("roteiro.md não contém seções reconhecíveis")
        return Roteiro(
            tema=context.tema,
            tese=tese,
            secoes=[Secao(nome=nome, conteudo=conteudo) for nome, conteudo in secoes.items()],
        )

    def execute(
        self, context: RunSnapshot, plan: StagePlan, emit: EventSink
    ) -> StageExecutionResult:
        model, broker = self._runtime()
        roteiro = self._load_roteiro(context)
        try:
            with broker.exclusivo("llm"):
                if self.settings.provider == "lm-studio":
                    (self.lm_manager or LMStudioManager(self.settings)).ensure_loaded()
                plano = planejar_midia(
                    model,
                    roteiro,
                    alvo_segundos=self.settings.midia_alvo_segundos,
                    run_dir=context.run_dir,
                )
        except CoberturaInsuficiente as error:
            return StageExecutionResult(
                current_items=0,
                total_items=1,
                failure=FailureDetail(
                    code="media_plan_coverage_failed",
                    message=str(error),
                    failure_class=FailureClass.DETERMINISTIC,
                    retriable=False,
                    recommended_action="Corrigir o roteiro ou o fatiador e tentar novamente",
                    adapter="media_plan",
                    attempt=context.attempt,
                ),
            )

        gravar_plano(context.run_dir, plano, forcar=True)
        self._plano = plano
        self._work_item_plans = _plan_work_items(plano)
        for item in self._work_item_plans:
            emit(
                kind="item.planned",
                level="info",
                message="Item de mídia planejado",
                payload={
                    **item.model_dump(mode="json"),
                    "kind": "audio" if item.item_key.startswith("b") else "imagem",
                },
            )
        output = ArtifactOutput(
            item_key="",
            kind="media_plan",
            relative_path="video/midia.json",
            mime_type="application/json",
            metadata={"block_count": len(plano.blocos), "beat_count": len(plano.beats)},
        )
        emit(
            kind="artifact.created",
            level="info",
            message="Plano de mídia criado",
            payload=output.model_dump(mode="json"),
        )
        return StageExecutionResult(
            current_items=1,
            total_items=1,
            artifacts=[output],
        )

    def validate(
        self, context: RunSnapshot, plan: StagePlan, result: StageExecutionResult
    ) -> GateResult:
        if result.failure is not None:
            return GateResult(
                approved=False,
                code="media_plan_gate_failed",
                findings=[
                    GateFinding(code=result.failure.code, message=result.failure.message)
                ],
            )
        plano = self._plano
        if plano is None:
            return GateResult(
                approved=False,
                code="media_plan_gate_failed",
                findings=[
                    GateFinding(code="media_plan_missing", message="Plano de mídia não produzido")
                ],
            )

        findings: list[GateFinding] = []
        roteiro = self._load_roteiro(context)
        for checker in (_conferir_narracao_absoluta, _conferir_cobertura_relativa):
            try:
                checker(roteiro, plano.blocos)
            except CoberturaInsuficiente as error:
                findings.append(
                    GateFinding(
                        code="narration_coverage_failed",
                        message=str(error),
                    )
                )
                break

        block_ids = [block.id for block in plano.blocos]
        beat_ids = [beat.id for beat in plano.beats]
        if len(block_ids) != len(set(block_ids)):
            findings.append(
                GateFinding(code="block_id_duplicate", message="Ids de bloco não são únicos")
            )
        if len(beat_ids) != len(set(beat_ids)):
            findings.append(
                GateFinding(code="beat_id_duplicate", message="Ids de beat não são únicos")
            )
        if any(not _ID.fullmatch(item_id) for item_id in block_ids):
            findings.append(
                GateFinding(code="block_id_invalid", message="Id de bloco não é estável")
            )
        if any(not _ID.fullmatch(item_id) for item_id in beat_ids):
            findings.append(
                GateFinding(code="beat_id_invalid", message="Id de beat não é estável")
            )

        blocks_by_id = {block.id: block for block in plano.blocos}
        for beat in plano.beats:
            if beat.bloco_id not in blocks_by_id:
                findings.append(
                    GateFinding(
                        code="beat_block_missing",
                        message=f"Beat {beat.id} aponta para bloco inexistente",
                        item_key=beat.id,
                        details={"bloco_id": beat.bloco_id},
                    )
                )

        sections_with_beats = {
            blocks_by_id[beat.bloco_id].secao
            for beat in plano.beats
            if beat.bloco_id in blocks_by_id
        }
        for section in roteiro.secoes:
            if section.nome not in sections_with_beats:
                findings.append(
                    GateFinding(
                        code="section_without_beat",
                        message=f"Seção {section.nome!r} não tem beat visual",
                        item_key=section.nome,
                    )
                )

        if findings:
            return GateResult(
                approved=False,
                code="media_plan_gate_failed",
                findings=findings,
                metrics={"blocks": len(plano.blocos), "beats": len(plano.beats)},
            )
        return GateResult(
            approved=True,
            code="media_plan_approved",
            metrics={"blocks": len(plano.blocos), "beats": len(plano.beats)},
        )


__all__ = ["MediaPlanExecutor", "hash_json"]
