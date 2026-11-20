import React from "react";
import { serviceStatusLabel } from "../lib/stage-map";

export type Tone = "ok" | "live" | "warn" | "fail" | "neutral";

/** Tom visual de um `run.status`; a mesma régua vale para a tabela e o cabeçalho. */
export function runTone(status: string | null | undefined): Tone {
  switch (status) {
    case "completed":
      return "ok";
    case "preparing":
    case "running":
    case "validating":
      return "live";
    case "pausing":
    case "paused":
      return "warn";
    case "failed":
    case "interrupted":
      return "fail";
    default:
      return "neutral";
  }
}

/** Tom de um serviço do `/api/services`. */
export function serviceTone(state: string | null | undefined): Tone {
  if (state === "available" || state === "healthy") return "ok";
  if (state === "degraded") return "warn";
  if (state === "unavailable" || state === "unhealthy" || state === "down") return "fail";
  return "neutral";
}

export function serviceStateLabel(state: string | null | undefined): string {
  switch (serviceTone(state)) {
    case "ok":
      return "Disponível";
    case "warn":
      return "Degradado";
    case "fail":
      return "Indisponível";
    default:
      return state || "Desconhecido";
  }
}

export function StatusBadge({
  tone,
  children,
  className,
}: {
  tone: Tone;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span className={`badge badge-${tone}${className ? ` ${className}` : ""}`}>
      <span className="badge-dot" aria-hidden="true" />
      {children}
    </span>
  );
}

export function RunStatusBadge({ status }: { status: string | null | undefined }) {
  return <StatusBadge tone={runTone(status)}>{status ? serviceStatusLabel(status) : "—"}</StatusBadge>;
}
