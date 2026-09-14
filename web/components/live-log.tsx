import React from "react";
import { StudioEvent } from "../lib/contracts";

export interface LiveLogProps {
  events: StudioEvent[];
  max?: number;
}

export function LiveLog({ events, max = 50 }: LiveLogProps) {
  const visible = (events || []).slice(-max);
  if (!visible.length) return null;

  return (
    <div className="log-view" aria-label="Log ao vivo">
      {visible.map((e) => {
        const cls =
          e.level === "error"
            ? "log-err"
            : e.level === "warn"
              ? "log-warn"
              : e.level === "ok"
                ? "log-ok"
                : "log-line";
        const time = e.created_at
          ? new Date(e.created_at).toLocaleTimeString("pt-BR", {
              hour: "2-digit",
              minute: "2-digit",
              second: "2-digit",
            })
          : "—";
        return (
          <div key={e.id} className={cls}>
            <span className="log-time">{time}</span>
            <span style={{ color: "#506176" }}>[{e.kind}]</span>
            <span>{e.message || "—"}</span>
          </div>
        );
      })}
    </div>
  );
}
