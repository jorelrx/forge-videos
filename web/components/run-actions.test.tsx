import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { RunActions } from "./run-actions";

describe("RunActions", () => {
  it("oferece retomar e retry para run pausada", () => {
    render(
      <RunActions
        run={{ status: "paused" }}
        onResume={vi.fn()}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Retomar" })).not.toBeNull();
    expect(screen.getByLabelText("Retry stage")).not.toBeNull();
    expect(screen.queryByRole("button", { name: "Solicitar pausa" })).toBeNull();
  });
});
