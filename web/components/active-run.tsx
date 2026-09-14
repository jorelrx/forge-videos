import React from "react";
import { RunStatus, StageName } from "../lib/contracts";

export interface ActiveRunProps {
  run: {
    run: { id: string; status: RunStatus; tema?: string };
    video: { tema?: string };
    progress: number;
    current_stage: StageName | null;
  };
  disabled?: boolean;
  onPause?: () => void;
  onResume?: () => void;
  onRetry?: (stage: string) => void;
}

export function ActiveRun({ run, disabled, onPause, onResume, onRetry }: ActiveRunProps) {
  return (
    <section aria-label="Run ativa">
      <h2>{run.video?.tema || run.run?.tema || "Run ativa"}</h2>
      <p>Status: {run.run?.status}</p>
      <p>Progresso: {Math.round(run.progress * 100)}%</p>
      <p>Etapa: {run.current_stage || "—"}</p>
      {onPause && (
        <button onClick={onPause} disabled={disabled} aria-label="Solicitar pausa">
          Solicitar pausa
        </button>
      )}
      {onResume && (
        <button onClick={onResume} disabled={disabled} aria-label="Retomar">
          Retomar
        </button>
      )}
    </section>
  );
}
