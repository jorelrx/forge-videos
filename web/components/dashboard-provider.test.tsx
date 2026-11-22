import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Dashboard } from "./dashboard";
import { DashboardProvider } from "./dashboard-provider";
import type { StudioApi } from "../lib/api";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  constructor() {
    FakeEventSource.instances.push(this);
  }
  close() {}
}

function makeApi(): StudioApi {
  return {
    getQueue: vi.fn().mockResolvedValue([]),
    getRuns: vi.fn().mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 }),
    getRun: vi.fn(),
    getServices: vi.fn().mockResolvedValue({ comfyui: { status: "ok", latency_ms: 12 } }),
    getEvents: vi.fn().mockResolvedValue({ items: [], next_before_id: null }),
    createVideo: vi.fn(),
    getGenerationFlows: vi.fn().mockResolvedValue([]),
    createGenerationFlow: vi.fn(),
    pauseRun: vi.fn(),
    resumeRun: vi.fn(),
    retryStage: vi.fn(),
  } as unknown as StudioApi;
}

describe("DashboardProvider", () => {
  it("mantém serviços e atividade ao vivo quando a página de produção remonta", async () => {
    FakeEventSource.instances = [];
    const api = makeApi();
    const EventSource = FakeEventSource as unknown as typeof globalThis.EventSource;

    // O layout do canal persiste entre rotas; a página de produção não.
    const { rerender } = render(
      <DashboardProvider api={api} eventSource={EventSource}>
        <Dashboard />
      </DashboardProvider>,
    );
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    act(() => FakeEventSource.instances[0].onopen?.());
    expect(await screen.findByText("Ao vivo")).not.toBeNull();

    rerender(
      <DashboardProvider api={api} eventSource={EventSource}>
        <p>Vídeos e insights</p>
      </DashboardProvider>,
    );
    rerender(
      <DashboardProvider api={api} eventSource={EventSource}>
        <Dashboard />
      </DashboardProvider>,
    );

    expect(screen.getByText("Ao vivo")).not.toBeNull();
    expect(api.getServices).toHaveBeenCalledOnce();
    expect(api.getQueue).toHaveBeenCalledOnce();
    expect(FakeEventSource.instances).toHaveLength(1);
  });
});
