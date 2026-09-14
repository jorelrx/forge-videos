import React from "react";
import { StageName } from "../lib/contracts";
import { stageStatus } from "../lib/stage-map";

const STAGE_ORDER: StageName[] = [
  "preparacao",
  "pesquisa",
  "roteiro",
  "plano_midia",
  "audio",
  "imagens",
  "montagem",
  "validacao",
];

const KICKER_BY_STATUS: Record<string, string> = {
  queued: "Na fila",
  preparing: "Run em execução",
  running: "Run em execução",
  validating: "Run em execução",
  pausing: "Run pausada",
  paused: "Run pausada",
  interrupted: "Run interrompida",
  failed: "Run falhou",
  completed: "Run concluída",
  cancelled: "Run cancelada",
};

type StageProbe = {
  stage_run?: { status?: string; started_at?: unknown } | null;
} | null;

export interface ActiveRunProps {
  run: {
    run: { id: string; status: string; tema?: string };
    video: { tema?: string };
    progress: number;
    current_stage: StageName | null;
    stages?: Partial<Record<StageName, StageProbe>>;
    artifacts?: { relative_path: string; mime_type: string }[];
  };
  statusLabel?: string;
  progressPercent?: number;
  disabled?: boolean;
  onPause?: () => void;
  onResume?: () => void;
  onRetry?: (stage: StageName) => void;
}

export function runKicker(status: string | undefined | null): string {
  const key = status ?? "";
  return KICKER_BY_STATUS[key] ?? "Run";
}

/** Última etapa com atividade registrada — usada quando current_stage é null. */
export function lastStageWithData(
  stages: Partial<Record<StageName, StageProbe>> | undefined,
): StageName | null {
  if (!stages) return null;
  let last: StageName | null = null;
  for (const stage of STAGE_ORDER) {
    const stageRun = stages[stage]?.stage_run;
    if (!stageRun) continue;
    const status = stageRun.status;
    const hasActivity =
      status != null && status !== "pending"
        ? true
        : stageRun.started_at != null;
    if (hasActivity) last = stage;
  }
  return last;
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
  const runStatus = run.run?.status;
  const status = statusLabel ?? runStatus ?? "—";
  const pct = progressPercent ?? Math.round((run.progress ?? 0) * 100);
  const stageKey = run.current_stage ?? lastStageWithData(run.stages);
  const currentStage = stageKey ? stageStatus(stageKey) : "—";
  const startedAt = (run.run as { started_at?: unknown }).started_at;
  const startedStr = startedAt ? ` · iniciado ${fmtTime(startedAt)}` : "";

  return (
    <section aria-label="Run ativa" className="active-run-detail">
      <div className="run-top">
        <div>
          <div className="run-kicker">{runKicker(runStatus)}</div>
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
          <span>concluído</span>
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
