import React from "react";
import { StageName } from "../lib/contracts";

export interface RunProgressProps {
  currentStage: StageName | null;
  progress: number;
}

export function RunProgress({ currentStage, progress }: RunProgressProps) {
  return (
    <div aria-label="Progresso da run">
      <progress max={1} value={progress} />
      <span>{Math.round(progress * 100)}%</span>
      <p>Etapa atual: {currentStage || "—"}</p>
    </div>
  );
}
