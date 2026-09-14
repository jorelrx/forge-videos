import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { FailureDrawer } from "./failure-drawer";

describe("FailureDrawer", () => {
  it("expõe falha ao operador com semântica de alerta", () => {
    render(<FailureDrawer error={new Error("Falha na pesquisa")} />);

    expect(screen.getByRole("alert")).not.toBeNull();
    expect(screen.getByText("Falha na pesquisa")).not.toBeNull();
  });
});
