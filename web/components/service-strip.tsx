import React from "react";
import { ServiceHealth } from "../lib/contracts";

export interface ServiceStripProps {
  services: Record<string, ServiceHealth>;
}

export function ServiceStrip({ services }: ServiceStripProps) {
  return (
    <section aria-label="Status dos serviços" className="service-strip">
      <h3>Serviços</h3>
      <ul>
        {Object.entries(services).map(([name, health]) => (
          <li key={name} className={`service-item state-${health.state}`}>
            <span className="service-name">{name}</span>
            <span className="service-state">{health.state}</span>
            <span className="service-message">{health.message}</span>
            {health.latency_ms != null && (
              <span className="service-latency">{health.latency_ms}ms</span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
