import { afterEach, describe, expect, it, vi } from "vitest";
import { createStudioApi } from "./api";

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("createStudioApi", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("lê projeções da fila e envia a chave idempotente do chamador", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(
        jsonResponse({
          id: "command-1",
          run_id: "run-1",
          type: "pause",
          stage: null,
          idempotency_key: "pause-run-1-click-1",
          status: "accepted",
          result: {},
          created_at: "2026-09-14T00:00:00Z",
          applied_at: null,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const api = createStudioApi("http://127.0.0.1:8765");

    await expect(api.getQueue()).resolves.toEqual([]);
    await api.pauseRun("run-1", "pause-run-1-click-1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://127.0.0.1:8765/api/queue",
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://127.0.0.1:8765/api/runs/run-1/pause",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "Idempotency-Key": "pause-run-1-click-1",
        }),
      }),
    );
  });
});
