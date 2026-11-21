import React from "react";
import type { JsonObject, StageName } from "../lib/contracts";
import { stageStatus } from "../lib/stage-map";
import { formatClock, formatDateTime, formatDuration, parseInstant, shortId } from "../lib/format";
import { StatusBadge, runTone } from "./status-badge";

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
    run: { id: string; status: string; tema?: string; config_snapshot?: JsonObject };
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

/** Estados em que a run ainda corre: só nelas a duração conta até agora. */
const LIVE_STATUSES = ["preparing", "running", "validating", "pausing"];

/** Estados parados: a etapa mostrada é onde a run parou, não a corrente. */
const STOPPED_STATUSES = ["failed", "interrupted", "paused", "cancelled"];

function isToday(value: unknown): boolean {
  const date = parseInstant(value);
  return date != null && date.toDateString() === new Date().toDateString();
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
}: ActiveRunProps) {
  const tema = run.video?.tema || run.run?.tema || "Run ativa";
  const runId = run.run?.id ?? "—";
  const runStatus = run.run?.status;
  const pct = progressPercent ?? Math.round((run.progress ?? 0) * 100);
  const stageKey = run.current_stage ?? lastStageWithData(run.stages);
  const currentStage = stageKey ? stageStatus(stageKey) : "—";
  const meta = run.run as { started_at?: unknown; finished_at?: unknown };
  const started = meta.started_at;
  const fluxo = run.run?.config_snapshot?.fluxo_geracao;
  const nomeFluxo = fluxo && typeof fluxo === "object" && "nome" in fluxo
    && typeof fluxo.nome === "string" ? fluxo.nome : "Padrão";

  return (
    <div className="active-run-detail">
      <div className="run-top">
        <div className="run-heading">
          <div className="run-kicker">
            <StatusBadge tone={runTone(runStatus)}>{runKicker(runStatus)}</StatusBadge>
            {statusLabel && <span className="sr-only">Status: {statusLabel}</span>}
          </div>
          <h2 className="run-title">{tema}</h2>
          <dl className="run-meta">
            <div>
              <dt>Fluxo</dt>
              <dd>{nomeFluxo}</dd>
            </div>
            <div>
              <dt>{STOPPED_STATUSES.includes(runStatus ?? "") ? "Parou em" : "Etapa atual"}</dt>
              <dd><b>{currentStage}</b></dd>
            </div>
            <div>
              <dt>Início</dt>
              <dd>{isToday(started) ? formatClock(started) : formatDateTime(started)}</dd>
            </div>
            {parseInstant(started) && (parseInstant(meta.finished_at) || LIVE_STATUSES.includes(runStatus ?? "")) && (
              <div>
                <dt>Duração</dt>
                <dd>{formatDuration(started, meta.finished_at)}</dd>
              </div>
            )}
            <div>
              <dt>ID</dt>
              <dd className="mono" title={runId}>{shortId(runId)}</dd>
            </div>
          </dl>
        </div>
        <div className="big-progress">
          <strong>{pct}%</strong>
          <span>concluído</span>
        </div>
      </div>
    </div>
  );
}
