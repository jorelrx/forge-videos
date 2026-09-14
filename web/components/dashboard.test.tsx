import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DashboardView } from "./dashboard";

// RED: comportamento completo ainda não implementado no componente.
describe("dashboard — comportamento completo (RED)", () => {
  it("renderiza primeira tela e opera (parcial)", () => {
    const state = {
      queue: [],
      runs: [],
      focusRun: null,
      services: {},
      events: [],
      connection: "offline" as const,
      loading: false,
      error: null,
      refresh: async () => {},
      createVideo: async () => {},
      pause: async () => {},
      resume: async () => {},
      retry: async () => {},
    };
    render(<DashboardView state={state} />);
    expect(screen.getByText("Forge Video Studio")).toBeDefined();
    // Falha esperada: operação completa (create/pause/resume/retry) ainda não conectada.
    expect(false).toBe(true);
    expect(false).toBe(true); // marca parcial
  });
});
