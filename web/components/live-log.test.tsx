import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { LiveLog } from "./live-log";
import type { StudioEvent } from "../lib/contracts";

function makeEvent(id: number, kind: string, level?: string, message?: string): StudioEvent {
  return {
    id,
    kind,
    level: level ?? "info",
    message: message ?? "",
    created_at: "2026-09-14T14:48:41Z",
    run_id: null,
    stage_run_id: null,
    work_item_id: null,
    payload: {},
  };
}

describe("LiveLog", () => {
  it("renderiza eventos com timestamp, kind e nível", () => {
    const events = [
      makeEvent(1, "stage.started", undefined, "Iniciando pesquisa"),
      makeEvent(2, "item.succeeded", undefined, "Item concluído"),
      makeEvent(3, "item.failed", undefined, "Falha na API externa"),
    ];
    render(<LiveLog events={events} />);

    expect(screen.getByText("Iniciando pesquisa")).not.toBeNull();
    expect(screen.getByText("Item concluído")).not.toBeNull();
    expect(screen.getByText("Falha na API externa")).not.toBeNull();

    const container = document.querySelector(".log-view");
    expect(container?.querySelectorAll(".log-line")).toHaveLength(3);
  });

  it("não renderiza nada quando sem eventos", () => {
    const { container } = render(<LiveLog events={[]} />);
    expect(container.firstChild).toBeNull();
  });
});
