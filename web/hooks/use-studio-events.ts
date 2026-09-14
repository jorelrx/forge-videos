import { useState, useEffect, useRef } from "react";

export interface StudioEvent {
  id: number;
  kind: string;
  level?: string;
  message?: string;
  [key: string]: unknown;
}

export interface StudioEventsState {
  connection: "connecting" | "live" | "reconnecting" | "offline";
  events: StudioEvent[];
}

export function eventsUrl(runId: string | null): string {
  const base = "/api/events/stream";
  return runId ? `${base}?run_id=${encodeURIComponent(runId)}` : base;
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
    return () => source.close();
  }, [runId, dependencies.EventSource]);

  return { connection, events };
}
