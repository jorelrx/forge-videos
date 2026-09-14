import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef } from "react";

import { NewVideoForm } from "./new-video-form";

describe("NewVideoForm", () => {
  it("usa o escopo de estilo .video-form de globals.css", () => {
    render(<NewVideoForm onSubmit={vi.fn()} />);
    const form = screen.getByTestId("new-video-form");
    expect(form.className).toContain("video-form");
    expect(form.querySelector('input[type="text"]')).not.toBeNull();
    expect(form.querySelector('button[type="submit"]')).not.toBeNull();
  });

  it("expõe o elemento form via ref (foco pelo header)", () => {
    const ref = createRef<HTMLFormElement>();
    render(<NewVideoForm ref={ref} onSubmit={vi.fn()} />);
    expect(ref.current).toBe(screen.getByTestId("new-video-form"));
  });

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
