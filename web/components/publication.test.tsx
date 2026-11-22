import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Publication } from "./publication";
import type { Artifact, RunSummary } from "../lib/contracts";

function artifact(overrides: Partial<Artifact>): Artifact {
  return {
    id: "a-1", run_id: "run-1", stage_run_id: "stage-1", work_item_id: null,
    kind: "embalagem", relative_path: "video/embalagem.json", mime_type: "application/json",
    size_bytes: 100, sha256: "a".repeat(64), metadata: {}, is_current: true,
    created_at: "2026-11-01T00:00:00Z", ...overrides,
  };
}

function summary(id: string, status: string, tema: string, finished_at: string | null = null): RunSummary {
  return {
    run: { id, status, finished_at, created_at: "2026-11-01T00:00:00Z" },
    video: { id: `v-${id}`, tema, tese: null },
    progress: 1,
    current_stage: null,
  } as unknown as RunSummary;
}

const EMBALAGEM = {
  titulos: [
    { texto: "Por que o tédio é um alarme", angulo: "pergunta" },
    { texto: "O tédio não é preguiça", angulo: "contraintuitivo" },
    { texto: "Use o tédio a seu favor", angulo: "benefício" },
  ],
  thumbnail: { texto: "Tédio é sinal", prompt: "a lone figure" },
  descricao: "Primeira linha.\n\n00:00 Abertura\n01:10 Prova",
  capitulos: [{ secao: "Gancho", titulo: "Abertura", inicio_segundos: 0 }],
  capitulos_estimados: false,
  tags: ["estoicismo", "tédio", "filosofia"],
  hashtags: ["#filosofia"],
  comentario_fixado: "O que o seu tédio está tentando dizer?",
  fontes: [],
  abertura: "Primeira linha.",
};

const FULL = [
  artifact({ id: "emb", kind: "embalagem" }),
  artifact({ id: "thumb", kind: "thumbnail.jpg", relative_path: "video/thumbnail.jpg", mime_type: "image/jpeg" }),
  artifact({ id: "srt", kind: "legendas.srt", relative_path: "video/legendas.srt", mime_type: "application/x-subrip" }),
  artifact({ id: "mp4", kind: "video/final.mp4", relative_path: "video/final.mp4", mime_type: "video/mp4" }),
];

function stubFetch(payload: unknown, ok = true) {
  const mock = vi.fn().mockResolvedValue({ ok, text: async () => JSON.stringify(payload), json: async () => payload });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function stubClipboard() {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  return writeText;
}

afterEach(() => {
  history.replaceState(null,'','/');
  vi.unstubAllGlobals();
  Object.defineProperty(navigator, "clipboard", { value: undefined, configurable: true });
});

const RUNS = [summary("run-1", "completed", "O tédio como alarme", "2026-11-02T10:00:00Z")];

describe("Publication", () => {
  it("renderiza a embalagem completa e os arquivos para baixar", async () => {
    stubFetch(EMBALAGEM);
    const loadArtifacts = vi.fn().mockResolvedValue(FULL);
    render(<Publication runs={RUNS} loadArtifacts={loadArtifacts} />);

    expect(await screen.findByText("Por que o tédio é um alarme")).not.toBeNull();
    expect(screen.getByText("O tédio não é preguiça")).not.toBeNull();
    expect(screen.getByText("Use o tédio a seu favor")).not.toBeNull();
    const descricao = screen.getByTestId("pub-descricao");
    expect(descricao.textContent).toBe(EMBALAGEM.descricao);
    expect(descricao.tagName).toBe("PRE");
    expect(screen.getByText("estoicismo,tédio,filosofia")).not.toBeNull();
    expect(screen.getByText(EMBALAGEM.comentario_fixado)).not.toBeNull();
    expect((screen.getByRole("img", { name: /Thumbnail/ }) as HTMLImageElement).src).toContain("/api/artifacts/thumb/content");

    const video = screen.getByRole("link", { name: "Baixar vídeo" });
    expect(video.getAttribute("href")).toContain("/api/artifacts/mp4/content?download=1");
    expect(video.hasAttribute("download")).toBe(true);
    expect(screen.getByRole("link", { name: "Baixar legenda" }).getAttribute("href")).toContain("/api/artifacts/srt/content?download=1");
    expect(screen.getByRole("link", { name: "Baixar thumbnail" }).getAttribute("href")).toContain("/api/artifacts/thumb/content?download=1");
    expect(screen.queryByText(/tempos dos capítulos são estimados/)).toBeNull();
    expect(loadArtifacts).toHaveBeenCalledWith("run-1");
  });

  it("copiar chama o clipboard com o texto certo e mostra Copiado", async () => {
    stubFetch(EMBALAGEM);
    const writeText = stubClipboard();
    render(<Publication runs={RUNS} loadArtifacts={async () => FULL} />);
    await screen.findByText("Por que o tédio é um alarme");

    fireEvent.click(screen.getByRole("button", { name: "Copiar título 2" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("O tédio não é preguiça"));
    expect(await screen.findByText("Copiado")).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Copiar descrição" }));
    await waitFor(() => expect(writeText).toHaveBeenLastCalledWith(EMBALAGEM.descricao));
    fireEvent.click(screen.getByRole("button", { name: "Copiar tags" }));
    await waitFor(() => expect(writeText).toHaveBeenLastCalledWith("estoicismo,tédio,filosofia"));
    fireEvent.click(screen.getByRole("button", { name: "Copiar comentário fixado" }));
    await waitFor(() => expect(writeText).toHaveBeenLastCalledWith(EMBALAGEM.comentario_fixado));
  });

  it("sem API de clipboard, copiar não quebra e avisa", async () => {
    stubFetch(EMBALAGEM);
    render(<Publication runs={RUNS} loadArtifacts={async () => FULL} />);
    await screen.findByText("Por que o tédio é um alarme");
    fireEvent.click(screen.getByRole("button", { name: "Copiar título 1" }));
    expect(await screen.findByText("Copie manualmente")).not.toBeNull();
  });

  it("contadores marcam aviso acima de 60 e erro acima de 70 nos títulos", async () => {
    const t65 = "a".repeat(65);
    const t75 = "b".repeat(75);
    stubFetch({ ...EMBALAGEM, titulos: [{ texto: "curto" }, { texto: t65 }, { texto: t75 }] });
    render(<Publication runs={RUNS} loadArtifacts={async () => FULL} />);
    await screen.findByText("curto");

    const ok = screen.getByTestId("contador-titulo-1");
    const warn = screen.getByTestId("contador-titulo-2");
    const error = screen.getByTestId("contador-titulo-3");
    expect(ok.textContent).toContain("5/70");
    expect(ok.getAttribute("data-level")).toBe("ok");
    expect(warn.textContent).toContain("65/70");
    expect(warn.getAttribute("data-level")).toBe("warn");
    expect(warn.textContent).toContain("corta no celular");
    expect(error.textContent).toContain("75/70");
    expect(error.getAttribute("data-level")).toBe("error");
    expect(error.textContent).toContain("acima do limite");

    expect(screen.getByTestId("contador-descricao").textContent).toContain(`${EMBALAGEM.descricao.length}/5000`);
    // tags: soma dos tamanhos mais as vírgulas, como no gate do backend
    expect(screen.getByTestId("contador-tags").textContent).toContain("26/500");
  });

  it("contador de descrição e de tags passa a erro acima do limite", async () => {
    stubFetch({ ...EMBALAGEM, descricao: "x".repeat(5001), tags: ["t".repeat(300), "u".repeat(300)] });
    render(<Publication runs={RUNS} loadArtifacts={async () => FULL} />);
    await screen.findByText("Por que o tédio é um alarme");
    expect(screen.getByTestId("contador-descricao").getAttribute("data-level")).toBe("error");
    expect(screen.getByTestId("contador-tags").getAttribute("data-level")).toBe("error");
  });

  it("avisa quando os capítulos ainda são estimados", async () => {
    stubFetch({ ...EMBALAGEM, capitulos_estimados: true });
    render(<Publication runs={RUNS} loadArtifacts={async () => FULL} />);
    expect(await screen.findByText(/tempos dos capítulos são estimados; confira antes de publicar/)).not.toBeNull();
  });

  it("mostra estado vazio para cada artefato ausente", async () => {
    const fetchMock = stubFetch(EMBALAGEM);
    render(<Publication runs={RUNS} loadArtifacts={async () => []} />);
    expect(await screen.findByText("Embalagem ausente")).not.toBeNull();
    expect(screen.getByText("Thumbnail ausente")).not.toBeNull();
    expect(screen.getByText("Vídeo ausente")).not.toBeNull();
    expect(screen.getByText("Legenda ausente")).not.toBeNull();
    expect(screen.queryByRole("link", { name: "Baixar vídeo" })).toBeNull();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/api/artifacts/"))).toBe(false);
  });

  it("embalagem ilegível vira estado vazio, não erro", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, text: async () => "" }));
    render(<Publication runs={RUNS} loadArtifacts={async () => FULL} />);
    expect(await screen.findByText("Embalagem indisponível")).not.toBeNull();
    expect(screen.getByRole("link", { name: "Baixar vídeo" })).not.toBeNull();
  });

  it("falha ao listar artefatos não quebra a tela", async () => {
    stubFetch(EMBALAGEM);
    render(<Publication runs={RUNS} loadArtifacts={async () => { throw new Error("offline"); }} />);
    expect(await screen.findByText(/não puderam ser carregados/)).not.toBeNull();
  });

  it("sem run concluída mostra estado vazio", () => {
    render(<Publication runs={[summary("run-x", "running", "Em curso")]} loadArtifacts={async () => []} />);
    expect(screen.getByText("Nenhuma execução concluída")).not.toBeNull();
  });

  it("escolhe a concluída mais recente e troca de run pelo seletor", async () => {
    const runs = [
      summary("run-live", "running", "Em curso"),
      summary("run-old", "completed", "Tema antigo", "2026-11-01T10:00:00Z"),
      summary("run-new", "completed", "Tema novo", "2026-11-03T10:00:00Z"),
    ];
    const byRun: Record<string, unknown> = {
      "run-new": { ...EMBALAGEM, titulos: [{ texto: "Título novo" }] },
      "run-old": { ...EMBALAGEM, titulos: [{ texto: "Título antigo" }] },
    };
    vi.stubGlobal("fetch", vi.fn(async (url: string) => ({
      ok: true,
      text: async () => JSON.stringify(byRun[url.includes("emb-run-old") ? "run-old" : "run-new"]),
    })));
    const loadArtifacts = vi.fn(async (runId: string) => [artifact({ id: `emb-${runId}`, run_id: runId })]);
    render(<Publication runs={runs} loadArtifacts={loadArtifacts} />);

    expect(await screen.findByText("Título novo")).not.toBeNull();
    const select = screen.getByLabelText("Execução") as HTMLSelectElement;
    expect(select.value).toBe("run-new");

    fireEvent.change(select, { target: { value: "run-old" } });
    expect(await screen.findByText("Título antigo")).not.toBeNull();
    expect(screen.queryByText("Título novo")).toBeNull();
    expect(loadArtifacts).toHaveBeenLastCalledWith("run-old");
  });

  it("lista de conferência é local e marcável", async () => {
    stubFetch(EMBALAGEM);
    render(<Publication runs={RUNS} loadArtifacts={async () => FULL} />);
    await screen.findByText("Por que o tédio é um alarme");
    const lista = screen.getByRole("region", { name: "Conferência do upload" });
    const boxes = within(lista).getAllByRole("checkbox");
    expect(boxes).toHaveLength(5);
    const sintetico = within(lista).getByLabelText(/conteúdo alterado ou sintético/);
    fireEvent.click(sintetico);
    expect((sintetico as HTMLInputElement).checked).toBe(true);
    expect(within(lista).getByLabelText(/legenda em português/i)).not.toBeNull();
  });
});

type PubEstado = Record<string, unknown>;

function estado(overrides: PubEstado = {}): PubEstado {
  return {
    etapa: "enviando", titulo: "O tédio não é preguiça", publicar_em: null, upload_uri: "u",
    bytes_enviados: 0, total_bytes: 0, video_id: null, thumbnail: "pendente", legenda: "pendente",
    avisos: [], erro: null, erro_codigo: null, atualizado_em: "2026-11-20T10:00:00Z", url: null,
    ...overrides,
  };
}

function res(status: number, body: unknown) {
  return { ok: status < 400, status, text: async () => JSON.stringify(body), json: async () => body };
}

function stubPublication(get: unknown[], post: unknown[] = []) {
  history.replaceState(null,"","/canais/UC1/producao");
  const gets = [...get];
  const posts = [...post];
  const mock = vi.fn(async (url: string, init?: RequestInit) => {
    if (String(url).includes("/publication")) {
      const queue = init?.method === "POST" ? posts : gets;
      return queue.length > 1 ? queue.shift() : queue[0];
    }
    return res(200, EMBALAGEM);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function postCalls(mock: ReturnType<typeof vi.fn>) {
  return mock.mock.calls.filter(
    ([url, init]) => (init as RequestInit | undefined)?.method === "POST" && String(url).includes("/publication"),
  );
}

function postBody(mock: ReturnType<typeof vi.fn>) {
  return JSON.parse((postCalls(mock)[0][1] as RequestInit).body as string);
}

describe("Publicar no YouTube", () => {
  it("oferece reconexão e bloqueia envio até conectar o canal da aba", async () => {
    stubPublication([res(200, {estado:null, em_andamento:false, conectado:false})]);
    render(<Publication runs={RUNS} loadArtifacts={async () => FULL} />);
    await screen.findByRole("button", {name:"Reconectar YouTube"});
    expect((screen.getByRole("button", {name:"Enviar ao YouTube"}) as HTMLButtonElement).disabled).toBe(true);
  });

  it("concluída mostra o canal", async () => {
    stubPublication([res(200, {
      estado: estado({ etapa: "concluida", video_id: "abc", url: "https://studio.youtube.com/video/abc/edit", canal_id: "UC1", canal_titulo: "Conquistas Cósmicas" }),
      em_andamento: false, conectado: true,
    })]);
    render(<Publication runs={RUNS} loadArtifacts={async () => FULL} />);
    expect(await screen.findByText("Canal: Conquistas Cósmicas")).not.toBeNull();
  });

  it("envia o título escolhido com publicar_em nulo e passa a mostrar progresso", async () => {
    const mock = stubPublication(
      [res(200, { estado: null, em_andamento: false, conectado: true })],
      [res(202, { estado: estado({ bytes_enviados: 25, total_bytes: 100 }), em_andamento: true, conectado: true })],
    );
    render(<Publication runs={RUNS} loadArtifacts={async () => FULL} />);
    fireEvent.click(await screen.findByRole("radio", { name: "O tédio não é preguiça" }));
    fireEvent.click(screen.getByRole("button", { name: "Enviar ao YouTube" }));

    expect(await screen.findByText(/25%/)).not.toBeNull();
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("25");
    expect(String(postCalls(mock)[0][0])).toContain("/api/runs/run-1/publication");
    expect(postBody(mock)).toEqual({ titulo: "O tédio não é preguiça", publicar_em: null, canal_id: "UC1" });
  });

  it("logo após o envio, sem estado gravado ainda, mostra iniciando e não o formulário", async () => {
    stubPublication(
      [res(200, { estado: null, em_andamento: false, conectado: true })],
      [res(202, { estado: null, em_andamento: true, conectado: true })],
    );
    render(<Publication runs={RUNS} loadArtifacts={async () => FULL} />);
    fireEvent.click(await screen.findByRole("button", { name: "Enviar ao YouTube" }));
    expect(await screen.findByText(/Iniciando envio/)).not.toBeNull();
    expect(screen.queryByRole("button", { name: "Enviar ao YouTube" })).toBeNull();
  });

  it("retentativa em andamento não volta a oferecer Tentar de novo", async () => {
    stubPublication([res(200, {
      estado: estado({ etapa: "falhou", erro: "caiu" }), em_andamento: true, conectado: true,
    })]);
    render(<Publication runs={RUNS} loadArtifacts={async () => FULL} />);
    expect(await screen.findByText(/Iniciando envio/)).not.toBeNull();
    expect(screen.queryByRole("button", { name: "Tentar de novo" })).toBeNull();
  });

  it("padrão é o primeiro título", async () => {
    const mock = stubPublication(
      [res(200, { estado: null, em_andamento: false, conectado: true })],
      [res(202, { estado: estado(), em_andamento: true, conectado: true })],
    );
    render(<Publication runs={RUNS} loadArtifacts={async () => FULL} />);
    await screen.findByRole("radio", { name: "Por que o tédio é um alarme" });
    fireEvent.click(screen.getByRole("button", { name: "Enviar ao YouTube" }));
    await waitFor(() => expect(postCalls(mock)).toHaveLength(1));
    expect(postBody(mock).titulo).toBe("Por que o tédio é um alarme");
  });

  it("agendar envia publicar_em em ISO 8601", async () => {
    const mock = stubPublication(
      [res(200, { estado: null, em_andamento: false, conectado: true })],
      [res(202, { estado: estado(), em_andamento: true, conectado: true })],
    );
    render(<Publication runs={RUNS} loadArtifacts={async () => FULL} />);
    await screen.findByRole("radio", { name: "Por que o tédio é um alarme" });
    fireEvent.click(screen.getByRole("radio", { name: "Agendar" }));
    fireEvent.change(screen.getByLabelText("Data e hora"), { target: { value: "2026-11-21T18:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar ao YouTube" }));
    await waitFor(() => expect(postCalls(mock)).toHaveLength(1));
    expect(postBody(mock).publicar_em).toBe(new Date("2026-11-21T18:00").toISOString());
  });

  it("enquanto em andamento consulta a cada 3 s", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const mock = stubPublication([
        res(200, { estado: estado({ bytes_enviados: 10, total_bytes: 100 }), em_andamento: true, conectado: true }),
        res(200, { estado: estado({ bytes_enviados: 60, total_bytes: 100 }), em_andamento: true, conectado: true }),
      ]);
      render(<Publication runs={RUNS} loadArtifacts={async () => FULL} />);
      expect(await screen.findByText(/10%/)).not.toBeNull();
      await act(async () => { await vi.advanceTimersByTimeAsync(3100); });
      expect(await screen.findByText(/60%/)).not.toBeNull();
      expect(mock.mock.calls.filter(([u]) => String(u).includes("/publication")).length).toBeGreaterThanOrEqual(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("etapa de thumbnail mostra o texto da etapa", async () => {
    stubPublication([res(200, { estado: estado({ etapa: "thumbnail" }), em_andamento: true, conectado: true })]);
    render(<Publication runs={RUNS} loadArtifacts={async () => FULL} />);
    expect(await screen.findByText("Enviando thumbnail…")).not.toBeNull();
  });

  it("envio interrompido oferece retomar com título e data guardados", async () => {
    const mock = stubPublication(
      [res(200, { estado: estado({ publicar_em: "2026-11-21T21:00:00Z" }), em_andamento: false, conectado: true })],
      [res(202, { estado: estado(), em_andamento: true, conectado: true })],
    );
    render(<Publication runs={RUNS} loadArtifacts={async () => FULL} />);
    expect(await screen.findByText("Envio interrompido.")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retomar envio" }));
    await waitFor(() => expect(postCalls(mock)).toHaveLength(1));
    expect(postBody(mock)).toEqual({ titulo: "O tédio não é preguiça", publicar_em: "2026-11-21T21:00:00Z", canal_id: "UC1" });
  });

  it("concluída mostra o link do Studio, o agendamento e os avisos", async () => {
    stubPublication([res(200, {
      estado: estado({
        etapa: "concluida", video_id: "abc", url: "https://studio.youtube.com/video/abc/edit",
        publicar_em: "2026-11-21T21:00:00Z", avisos: ["legenda recusada"], thumbnail: "ok", legenda: "recusada",
      }),
      em_andamento: false, conectado: true,
    })]);
    render(<Publication runs={RUNS} loadArtifacts={async () => FULL} />);
    expect(await screen.findByText("Enviado ao YouTube")).not.toBeNull();
    const link = screen.getByRole("link", { name: "Abrir no YouTube Studio" });
    expect(link.getAttribute("href")).toBe("https://studio.youtube.com/video/abc/edit");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
    expect(screen.getByText("legenda recusada")).not.toBeNull();
    expect(screen.getByText(/Fixe o comentário manualmente/)).not.toBeNull();
    expect(screen.queryByRole("button", { name: "Enviar ao YouTube" })).toBeNull();
  });

  it("concluída sem data mostra Privado", async () => {
    stubPublication([res(200, {
      estado: estado({ etapa: "concluida", video_id: "abc", url: "https://studio.youtube.com/video/abc/edit" }),
      em_andamento: false, conectado: true,
    })]);
    render(<Publication runs={RUNS} loadArtifacts={async () => FULL} />);
    expect(await screen.findByText("Privado")).not.toBeNull();
  });

  it("falha mostra o erro e Tentar de novo reenvia o título guardado", async () => {
    const mock = stubPublication(
      [res(200, { estado: estado({ etapa: "falhou", erro: "cota excedida", erro_codigo: "quota" }), em_andamento: false, conectado: true })],
      [res(202, { estado: estado({ bytes_enviados: 1, total_bytes: 100 }), em_andamento: true, conectado: true })],
    );
    render(<Publication runs={RUNS} loadArtifacts={async () => FULL} />);
    expect(await screen.findByText(/cota excedida/)).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
    await waitFor(() => expect(postCalls(mock)).toHaveLength(1));
    expect(postBody(mock)).toEqual({ titulo: "O tédio não é preguiça", publicar_em: null, canal_id: "UC1" });
    expect(await screen.findByText(/1%/)).not.toBeNull();
  });

  it("erro 409 do POST aparece como alerta", async () => {
    stubPublication(
      [res(200, { estado: null, em_andamento: false, conectado: true })],
      [res(409, { error: { code: "publication_refused", message: "Gate recusou a publicação" } })],
    );
    render(<Publication runs={RUNS} loadArtifacts={async () => FULL} />);
    await screen.findByRole("radio", { name: "Por que o tédio é um alarme" });
    fireEvent.click(screen.getByRole("button", { name: "Enviar ao YouTube" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Gate recusou a publicação");
  });
});
