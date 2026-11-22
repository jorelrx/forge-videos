import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BoardCriativo } from "./board-criativo";

afterEach(() => vi.unstubAllGlobals());

const pauta = {titulo: "Da ideia ao vídeo", tema: "Escolhas", pergunta: "Por quê?", recorte: "O cotidiano", promessa: "Uma reflexão"};
const ideia = {
  id: "a", tipo: "continuacao", pauta, hipotese: false, diferenca: "Uma pergunta diferente",
  justificativa: "Inspirada em um episódio", motivo_descarte: null,
  referencias: [{id: "v1", tipo: "catalogo", titulo: "Vídeo anterior", url: "/canais/A/videos/existente"}],
};
const base = {
  revisao: 1, propostas: [ideia], guardadas: [], candidata: null, origem_pauta: null,
  pauta: null, operacao: null, erro: null, posicionamento: "",
  contexto: {precisa_posicionamento: false, aguardando: false, observacoes: [], estado_catalogo: "atualizado"},
};

it("recupera propostas sem nova análise e abre o vídeo de origem", async () => {
  const fetcher = vi.fn(async () => Response.json(base));
  vi.stubGlobal("fetch", fetcher);
  render(<BoardCriativo canal="A"/>);

  await screen.findByRole("heading", {name: "Da ideia ao vídeo"});
  const link = screen.getByRole("link", {name: "Vídeo anterior", hidden: true});
  expect(link.getAttribute("href")).toBe("/canais/A/videos/existente");
  expect(fetcher.mock.calls).toHaveLength(1);
});

it("mostra mudanças antes de desenvolver uma proposta sobre a pauta existente", async () => {
  const existente = {...base, pauta: {...pauta, titulo: "Meu título editado"}};
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async () => Response.json(existente));
  vi.stubGlobal("fetch", fetcher);
  render(<BoardCriativo canal="A"/>);
  fireEvent.click(await screen.findByRole("button", {name: "Desenvolver"}));

  expect(await screen.findByRole("heading", {name: "Revisar mudanças na pauta"})).toBeTruthy();
  expect(screen.getByText("Meu título editado")).toBeTruthy();
  expect(fetcher.mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true);
  fireEvent.click(screen.getByRole("button", {name: "Aplicar proposta à pauta"}));
  await waitFor(() => expect(fetcher.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(true));
});

it("salva posicionamento e inicia sugestões para canal sem histórico", async () => {
  const novo = {...base, propostas: [], contexto: {...base.contexto, precisa_posicionamento: true}};
  const comPosicionamento = {...novo, revisao: 2, posicionamento: "Ensaios sobre escolhas"};
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (_url, init) => {
    if (init?.method === "PUT") return Response.json(comPosicionamento);
    if (init?.method === "POST") return Response.json({...comPosicionamento, operacao: "sugestoes"}, {status: 202});
    return Response.json(novo);
  });
  vi.stubGlobal("fetch", fetcher);
  render(<BoardCriativo canal="A"/>);
  fireEvent.change(await screen.findByLabelText(/Sobre o que é o canal/), {target: {value: "Ensaios sobre escolhas"}});
  fireEvent.click(screen.getByRole("button", {name: "Salvar posicionamento"}));

  expect(await screen.findByText("Preparando sugestões…")).toBeTruthy();
  const analises = fetcher.mock.calls.filter(([, init]) => init?.method === "POST");
  expect(analises).toHaveLength(1);
  expect(JSON.parse(String(analises[0][1]?.body))).toEqual({revisao: 2, tipo: "sugestoes"});
});

it("oferece pauta manual e nova tentativa quando a análise falha", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({
    ...base, propostas: [], erro: "analise_indisponivel",
  })));
  render(<BoardCriativo canal="A"/>);

  fireEvent.click(await screen.findByRole("button", {name: "Abrir pauta manual"}));
  expect(screen.getByLabelText("Título provisório")).toBeTruthy();
  expect(screen.getByRole("button", {name: "Tentar análise novamente"})).toBeTruthy();
});
