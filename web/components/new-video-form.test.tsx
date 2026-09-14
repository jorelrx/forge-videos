import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { NewVideoForm } from "./new-video-form";

describe("NewVideoForm", () => {
  it("envia somente campos aprovados, com texto normalizado", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<NewVideoForm onSubmit={onSubmit} />);

    await user.type(screen.getByLabelText("Tema"), "  O peso do silêncio  ");
    await user.type(screen.getByLabelText("Tese opcional"), "  Silêncio decide  ");
    await user.click(screen.getByRole("button", { name: "Enfileirar vídeo" }));

    expect(onSubmit).toHaveBeenCalledWith({
      tema: "O peso do silêncio",
      tese: "Silêncio decide",
      priority: 50,
      preset: "local-recomendado-v1",
    });
  });
});
