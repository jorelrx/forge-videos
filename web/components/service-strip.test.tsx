import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ServiceStrip } from "./service-strip";

describe("ServiceStrip", () => {
  it("expõe indisponibilidade e latência sem mascarar estado", () => {
    render(
      <ServiceStrip
        services={{
          comfyui: {
            name: "comfyui",
            state: "unavailable",
            message: "ComfyUI não respondeu",
            latency_ms: 1800,
          },
        }}
      />
    );

    const item = screen.getByText("comfyui").closest(".service-chip");
    expect(item?.getAttribute("class")).toContain("gpu");
    expect(item?.getAttribute("class")).not.toContain("healthy");
    expect(screen.getByText(/ComfyUI não respondeu/)).not.toBeNull();
    expect(screen.getByText("1800ms")).not.toBeNull();
  });

  it("retorna null quando não há serviços", () => {
    const { container } = render(<ServiceStrip services={{}} />);
    expect(container.firstChild).toBeNull();
  });
});
