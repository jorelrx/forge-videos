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
      fluxo_geracao: "padrao",
    });
  });

  it("enfileira a revisão editorial com as referências escolhidas", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<NewVideoForm onSubmit={onSubmit} />);

    await user.type(screen.getByLabelText("Tema"), "Liberdade");
    await user.click(screen.getByRole("checkbox", { name: "Revisar proposta e abertura" }));
    await user.type(screen.getByLabelText("Referências editoriais opcionais"), "  Abrir com uma escolha concreta.  ");
    await user.click(screen.getByRole("button", { name: "Enfileirar vídeo" }));

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      revisao_editorial: true,
      referencias_editoriais: "Abrir com uma escolha concreta.",
    }));
  });

  it("salva e seleciona um fluxo personalizado sem perder o tema", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    const fluxo = {
      id: "personalizado-1",
      nome: "Dilemas",
      descricao: "Uma decisão concreta.",
      instrucoes: "Abra o roteiro com duas escolhas.",
    };
    const fluxosApi = {
      getGenerationFlows: vi.fn().mockResolvedValue([
        { id: "padrao", nome: "Padrão", descricao: "Roteiro atual.", instrucoes: null },
      ]),
      createGenerationFlow: vi.fn().mockResolvedValue(fluxo),
    };
    render(<NewVideoForm onSubmit={onSubmit} fluxosApi={fluxosApi} />);

    await user.type(screen.getByLabelText("Tema"), "Coragem");
    await user.click(await screen.findByText("Criar fluxo"));
    await user.type(screen.getByLabelText("Nome do fluxo"), fluxo.nome);
    await user.type(screen.getByLabelText("Descrição"), fluxo.descricao);
    await user.type(screen.getByLabelText("Instruções para o roteiro"), fluxo.instrucoes);
    await user.click(screen.getByRole("button", { name: "Salvar fluxo" }));
    await screen.findByRole("option", { name: "Dilemas", selected: true });
    expect(fluxosApi.createGenerationFlow).toHaveBeenCalledWith({
      nome: fluxo.nome, descricao: fluxo.descricao, instrucoes: fluxo.instrucoes,
    });
    expect(onSubmit).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Enfileirar vídeo" }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      tema: "Coragem", fluxo_geracao: fluxo.id,
    }));
  });
});
