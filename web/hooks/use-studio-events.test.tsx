import { describe, expect, it } from "vitest";
import { eventsUrl } from "./use-studio-events";

describe("eventsUrl", () => {
  it("conecta EventSource pela origem da aba", () => {
    expect(eventsUrl("run 1")).toBe(
      "/api/events/stream?run_id=run%201",
    );
  });
});
