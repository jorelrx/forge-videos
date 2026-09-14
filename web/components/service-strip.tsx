import React from "react";
import { ServiceHealth } from "../lib/contracts";

export interface ServiceStripProps {
  services: Record<string, ServiceHealth>;
}

const GPU_SERVICES = ["lm-studio", "comfyui", "tts", "audio-generate"];

export function ServiceStrip({ services }: ServiceStripProps) {
  const entries = Object.entries(services);
  if (entries.length === 0) return null;

  return (
    <div className="services-strip" aria-label="Status dos serviços">
      {entries.map(([name, health]) => {
        const isGpu = GPU_SERVICES.some((g) => name.includes(g));
        const ledState =
          health.state === "healthy"
            ? "led"
            : health.state === "degraded"
              ? "led busy"
              : "led off";
        return (
          <div key={name} className={`service-chip ${isGpu ? "gpu" : ""}`}>
            <span className={ledState} aria-hidden="true" />
            <span>{name}</span>
            {health.message && (
              <span style={{ color: "var(--muted)" }}>· {health.message}</span>
            )}
            {health.latency_ms != null && <span>{health.latency_ms}ms</span>}
          </div>
        );
      })}
    </div>
  );
}
