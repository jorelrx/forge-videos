import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { RunOutputs } from "./run-outputs";
import type { RunView } from "../lib/contracts";

function artifact(overrides: Record<string, unknown>) {
  return {
    id: "artifact-1", run_id: "run-1", stage_run_id: "stage-1", work_item_id: null,
    kind: "roteiro", relative_path: "video/roteiro.json", mime_type: "application/json",
    size_bytes: 100, sha256: "a".repeat(64), metadata: {}, is_current: true,
    created_at: "2026-10-01T00:00:00Z", ...overrides,
  };
}

function makeRun(overrides: Record<string, unknown> = {}) {
  return {
    run: { id: "run-1", status: "running" },
    video: { id: "video-1", tema: "Tema do vídeo", tese: null },
    progress: 0.5,
    current_stage: "audio",
    artifacts: [],
    stages: {},
    ...overrides,
  } as unknown as RunView;
}

describe("RunOutputs", () => {
  it("separa referências do texto falado no roteiro", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      text: async () => JSON.stringify({
        tese: "A tese",
        fontes: [{ path: "8.f2", titulo: "Obra", autor: "Cohen" }],
        secoes: [{ nome: "Prova", conteudo: "Cohen argumenta. [8.f2]", blocos: [] }],
      }),
    }));
    render(<RunOutputs run={makeRun({ artifacts: [artifact({})] })} />);

    expect(await screen.findByText("Cohen argumenta.")).not.toBeNull();
    expect(screen.queryByText("Cohen argumenta. [8.f2]")).toBeNull();
    fireEvent.click(screen.getByText(/Referências/));
    expect(screen.getByText("8.f2")).not.toBeNull();
    expect(screen.getByText("Cohen · Obra")).not.toBeNull();
  });

  it("preserva aba, seleção e elemento de áudio durante atualização incremental", async () => {
    const audioArtifact = artifact({
      id: "audio-1", work_item_id: "work-b001", kind: "audio.wav",
      relative_path: "video/audio/b001.wav", mime_type: "audio/wav",
    });
    const item = {
      id: "work-b001", stage_run_id: "audio-stage", item_key: "b001", status: "succeeded",
      input: { texto: "Fala limpa.", secao: "Gancho" }, input_hash: "b".repeat(64),
      attempts: 1, duration_ms: 1000, failure_code: null, failure_message: null,
    };
    const initial = makeRun({
      artifacts: [audioArtifact],
      stages: { audio: { stage_run: { status: "running" }, items: [item], metrics: {} } },
    });
    const view = render(<RunOutputs run={initial} />);
    fireEvent.click(screen.getByRole("tab", { name: /Áudios/ }));
    expect(await screen.findByText("Fala limpa.")).not.toBeNull();
    const player = view.container.querySelector("audio");
    expect(player).not.toBeNull();

    view.rerender(<RunOutputs run={makeRun({
      artifacts: [{ ...audioArtifact }],
      stages: { audio: { stage_run: { status: "running" }, items: [{ ...item, duration_ms: 1800 }], metrics: {} } },
    })} />);

    await waitFor(() => expect(screen.getByRole("tab", { name: /Áudios/ }).getAttribute("aria-selected")).toBe("true"));
    expect(view.container.querySelector("audio")).toBe(player);
    expect(screen.getByRole("button", { name: /b001/ }).getAttribute("aria-pressed")).toBe("true");
  });

  it("mostra aguardando e erro de prévia sem criar artefatos", async () => {
    const run = makeRun({
      run: { id: "run-1", status: "failed" },
      stages: { imagens: { stage_run: { status: "pending" }, items: [], metrics: {} } },
    });
    const view = render(<RunOutputs run={run} />);
    fireEvent.click(screen.getByRole("tab", { name: /Imagens/ }));
    expect(screen.getByText("Imagens aguardando")).not.toBeNull();

    const imageArtifact = artifact({
      id: "image-1", kind: "image.png", relative_path: "video/images/i001.png",
      mime_type: "image/png",
    });
    view.rerender(<RunOutputs run={makeRun({ artifacts: [imageArtifact] })} />);
    fireEvent.click(screen.getByRole("tab", { name: /Imagens/ }));
    fireEvent.error(view.container.querySelector("img")!);
    expect(screen.getByText("Imagem indisponível")).not.toBeNull();
  });
});
