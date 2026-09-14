import React from "react";
import { RunStatus, StageName } from "../lib/contracts";

export interface RunActionsProps {
  run: { status: RunStatus };
  disabled?: boolean;
  onPause?: () => void;
  onResume?: () => void;
  onRetry?: (stage: StageName) => void;
}

const canPause = (s: RunStatus) => ["preparing", "running", "validating"].includes(s);
const canResume = (s: RunStatus) => ["paused", "failed", "interrupted"].includes(s);
const canRetry = (s: RunStatus) => ["paused", "failed", "completed"].includes(s);

export function RunActions({ run, disabled, onPause, onResume, onRetry }: RunActionsProps) {
  const status = run.status;
  return (
    <div aria-label="Ações da run">
      {canPause(status) && onPause && (
        <button onClick={onPause} disabled={disabled} aria-label="Solicitar pausa">
          Solicitar pausa
        </button>
      )}
      {status === "pausing" && <span>Pausa após o item atual</span>}
      {canResume(status) && onResume && (
        <button onClick={onResume} disabled={disabled} aria-label="Retomar">
          Retomar
        </button>
      )}
      {canRetry(status) && onRetry && (
        <select
          disabled={disabled}
          aria-label="Retry stage"
          onChange={(e) =>
            e.target.value && onRetry(e.target.value as StageName)
          }
        >
          <option value="">Retry...</option>
          {["preparacao", "pesquisa", "roteiro", "plano_midia", "audio", "imagens", "montagem", "validacao"].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      )}
    </div>
  );
}
