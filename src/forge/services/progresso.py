"""Salvamento de progresso e raciocínio do agente durante a geração de roteiros.

Inspirado no state.db do agente do research: cada chamada ao modelo é
registrada como uma linha JSONL, permitindo inspeção pós-fato e retomada
parcial do pipeline caso o processo morra entre fases.

O thinking (reasoning_content) do modelo é salvo junto, assim como o prompt
enviado e o resultado bruto.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)

ORDEM_ETAPAS = ["tema", "research", "plan", "write", "review"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ProgressoLogger:
    """Registra cada chamada ao LLM como uma linha JSONL no run dir.

    Cada linha contém:
    - etapa: qual fase do pipeline (tema, research, plan, write, review)
    - subfase: qual sub-step dentro da fase (queries, busca, síntese, etc.)
    - prompt: o prompt enviado (truncado a 2000 chars)
    - thinking: o reasoning_content do modelo (se houver)
    - resultado: o conteúdo da resposta (truncado a 2000 chars)
    - timestamp: ISO 8601

    O arquivo é progresso.jsonl no run_dir. Cada linha é append-only e
    atomicamente escrita (flush após cada call), entao se o processo morrer
    a qualquer momento o progresso esta preservado ate o ultimo call.
    """

    def __init__(self, run_dir: Path):
        self.path = run_dir / "progresso.jsonl"
        run_dir.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        etapa: str,
        subfase: str,
        *,
        prompt: str = "",
        thinking: str = "",
        resultado: str = "",
        metadados: dict | None = None,
    ) -> None:
        entry = {
            "timestamp": _now(),
            "etapa": etapa,
            "subfase": subfase,
            "prompt": _truncar(prompt, 2000),
            "thinking": thinking,
            "resultado": _truncar(resultado, 4000),
            "metadados": metadados or {},
        }
        line = json.dumps(entry, ensure_ascii=False)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
        logger.debug(
            "Progresso registrado",
            etapa=etapa,
            subfase=subfase,
        )

    def ultimas(self, n: int = 10) -> list[dict]:
        """Le as ultimas n entradas do JSONL."""
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").strip().splitlines()
        return [json.loads(l) for l in lines[-n:]]

    def etapas_completadas(self) -> set[str]:
        """Retorna o set de etapas que ja tiveram pelo menos um log."""
        if not self.path.exists():
            return set()
        fases = set()
        for linha in self.path.read_text(encoding="utf-8").splitlines():
            if not linha.strip():
                continue
            entry = json.loads(linha)
            fases.add(entry["etapa"])
        return fases

    def esta_completo(self) -> bool:
        return set(ORDEM_ETAPAS).issubset(self.etapas_completadas())


def _truncar(texto: str, max_chars: int) -> str:
    if not texto:
        return ""
    if len(texto) <= max_chars:
        return texto
    return texto[:max_chars] + f"\n...[truncado em {len(texto) - max_chars} chars]\n"
