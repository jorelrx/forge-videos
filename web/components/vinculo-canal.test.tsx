import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { VinculoCanal } from "./vinculo-canal";

afterEach(() => vi.unstubAllGlobals());

it("notifica a conclusão uma vez mesmo quando o callback muda", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({
    tentativa_id: "tentativa", login: {status: "concluido"},
  })));
  const concluir = vi.fn();
  const view = render(<VinculoCanal canalId="A" onComplete={concluir}/>);
  fireEvent.click(screen.getByRole("button", {name: "Reconectar YouTube"}));
  await waitFor(() => expect(concluir).toHaveBeenCalledTimes(1));
  const novoCallback = vi.fn();
  view.rerender(<VinculoCanal canalId="A" onComplete={novoCallback}/>);
  expect(novoCallback).not.toHaveBeenCalled();
});
