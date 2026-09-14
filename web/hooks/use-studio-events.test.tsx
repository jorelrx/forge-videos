import { describe, expect, it } from "vitest";
import { eventsUrl } from "./use-studio-events";

describe("eventsUrl", () => {
  it("conecta EventSource diretamente na API local", () => {
    expect(eventsUrl("run 1")).toBe(
      "http://127.0.0.1:8765/api/events/stream?run_id=run%201",
    );
  });
});
