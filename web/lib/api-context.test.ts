import { afterEach, expect, it, vi } from "vitest";
import { artifactDownloadUrl, createStudioApi, studioEventsUrl } from "./api";

afterEach(() => { history.replaceState(null, "", "/"); vi.unstubAllGlobals(); });

it("usa a origem da aba e inclui o canal em comandos, downloads e eventos", async () => {
  history.replaceState(null, "", "/canais/A/producao");
  const fetcher = vi.fn().mockResolvedValue(Response.json([]));
  vi.stubGlobal("fetch", fetcher);
  await createStudioApi().getQueue();
  expect(fetcher.mock.calls[0][0]).toBe("/api/queue?canal_id=A");
  expect(artifactDownloadUrl("file")).toBe("/api/artifacts/file/content?download=1&canal_id=A");
  expect(studioEventsUrl("run")).toBe("/api/events/stream?run_id=run&canal_id=A");
});
