import React from "react";
import { StudioEvent } from "../lib/contracts";

export interface LiveLogProps {
  events: StudioEvent[];
  max?: number;
}

export function LiveLog({ events, max = 50 }: LiveLogProps) {
  const visible = events.slice(-max);
  return (
    <section aria-label="Log ao vivo" className="live-log">
      <h3>Log ao vivo</h3>
      <ul>
        {visible.map((e) => (
          <li key={e.id} className={`log-level-${e.level || "info"}`}>
            <span className="log-time">{e.created_at || "—"}</span>
            <span className="log-kind">[{e.kind}]</span>
            <span className="log-message">{e.message || "—"}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
