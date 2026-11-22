import { useState, useEffect, useRef } from "react";
import { studioEventsUrl } from "../lib/api";
import type { StudioEvent } from "../lib/contracts";

export type { StudioEvent } from "../lib/contracts";

export interface StudioEventsState {
  connection: "connecting" | "live" | "reconnecting" | "offline";
  events: StudioEvent[];
}

export function eventsUrl(runId: string | null): string {
  return studioEventsUrl(runId);
}

export function useStudioEvents(
  runId: string | null,
  dependencies: { EventSource?: typeof EventSource } = {},
): StudioEventsState {
  const [connection, setConnection] = useState<StudioEventsState["connection"]>("connecting");
  const [events, setEvents] = useState<StudioEvent[]>([]);
  const opened = useRef(false);

  useEffect(() => {
    const Source = dependencies.EventSource ?? window.EventSource ?? (globalThis as any).EventSource;
    if (!Source) {
      setConnection("offline");
      return;
    }
    const source = new Source(eventsUrl(runId));
    source.onopen = () => {
      opened.current = true;
      setConnection("live");
    };
    source.onerror = () => setConnection(opened.current ? "reconnecting" : "offline");
    source.onmessage = (message: MessageEvent) => {
      try {
        const event = JSON.parse(message.data) as StudioEvent;
        setEvents((current) => {
          const byId = new Map(current.map((item) => [item.id, item]));
          byId.set(event.id, event);
          return [...byId.values()].sort((a, b) => a.id - b.id).slice(-200);
        });
      } catch {
        // Malformed public data is ignored; connection remains observable.
      }
    };
    const fechar = () => source.close();
    window.addEventListener("pagehide", fechar);
    return () => {
      window.removeEventListener("pagehide", fechar);
      source.onmessage = null;
      source.onerror = null;
      source.onopen = null;
      fechar();
    };
  }, [runId, dependencies.EventSource]);

  return { connection, events };
}
