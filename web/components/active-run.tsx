import React from "react";
import { StageName } from "../lib/contracts";
import { stageStatus } from "../lib/stage-map";

export interface ActiveRunProps {
  run: {
    run: { id: string; status: string; tema?: string };
    video: { tema?: string };
    progress: number;
    current_stage: StageName | null;
    artifacts?: { relative_path: string; mime_type: string }[];
  };
  statusLabel?: string;
  progressPercent?: number;
  disabled?: boolean;
  onPause?: () => void;
  onResume?: () => void;
  onRetry?: (stage: StageName) => void;
}

export function ActiveRun({
  run,
  statusLabel,
  progressPercent,
  disabled,
  onPause,
  onResume,
  onRetry,
}: ActiveRunProps) {
  const tema = run.video?.tema || run.run?.tema || "Run ativa";
  const runId = run.run?.id ?? "—";
  const status = statusLabel ?? run.run?.status ?? "—";
  const pct = progressPercent ?? Math.round((run.progress ?? 0) * 100);
  const currentStage = run.current_stage ? stageStatus(run.current_stage) : "—";
  const startedAt = (run.run as { started_at?: unknown }).started_at;
  const startedStr = startedAt ? ` · iniciado ${fmtTime(startedAt)}` : "";

  return (
    <section aria-label="Run ativa" className="active-run-detail">
      <div className="run-top">
        <div>
          <div className="run-kicker">Run em execução · etapa {run.current_stage ? "de 6" : "—"}</div>
          <h2 className="run-title">{tema}</h2>
          <div className="run-meta">
            {runId} · {status}
            {startedStr}
          </div>
          <div className="run-stage">
            Etapa atual: <b>{currentStage}</b>
          </div>
        </div>
        <div className="big-progress">
          <strong>{pct}%</strong>
          <span>{pct}%</span>
        </div>
      </div>
    </section>
  );
}

function fmtTime(t: unknown): string {
  if (typeof t !== "string") return "—";
  const d = new Date(t);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}
