import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BoardCriativo } from "./board-criativo";

const push = vi.fn();
vi.mock("next/navigation", () => ({useRouter: () => ({push})}));
afterEach(() => { vi.unstubAllGlobals(); push.mockReset(); });

const pauta = {
  titulo: "Um ensaio", tema: "Escolhas", pergunta: "Por quê?", recorte: "Cozinha", promessa: "Entender",
  abertura: "", blocos: ["A cena"], desfecho: "", perguntas_pesquisa: [], referencias: [],
};
const board = {
  revisao: 9, propostas: [], guardadas: [], candidata: null, origem_pauta: null, pauta, operacao: null, erro: null,
  posicionamento: "Canal", fluxo_id: "padrao", analisado_em: null, conversa: [], pendencias: [],
  fluxos: [{id: "padrao", nome: "Padrão", descricao: "Roteiro atual", disponivel: true, motivo: null}],
  contexto: {precisa_posicionamento: false, aguardando: false, observacoes: [], estado_catalogo: "atualizado",
    estado_analytics: "atualizado", atualizado_em: null},
};
const novo = {...board, revisao: 10, pauta: null, fluxo_id: null,
  ultima_aprovacao: {id: "a1", run_id: "run-7", revisao: 9, titulo: "Um ensaio"}};

it("criar roteiro aprova e abre a execução", async () => {
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (url, init) =>
    init?.method === "POST" ? Response.json({run_id: "run-7", aprovacao: {id: "a1"}, board: novo}, {status: 201})
      : Response.json(board));
  vi.stubGlobal("fetch", fetcher);
  render(<BoardCriativo canal="A"/>);

  fireEvent.click(await screen.findByRole("button", {name: "Criar roteiro"}));
  await waitFor(() => expect(push).toHaveBeenCalledWith("/canais/A/producao#/producao?run=run-7"));
  const post = fetcher.mock.calls.find(([, init]) => init?.method === "POST")!;
  expect(String(post[0])).toBe("/api/canais/A/board/aprovacoes");
  expect(JSON.parse(String(post[1]?.body))).toEqual({revisao: 9, fluxo_id: "padrao"});
});

it("repetir após falha usa a mesma revisão", async () => {
  let tentativas = 0;
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (_url, init) => {
    if (init?.method !== "POST") return Response.json(board);
    tentativas += 1;
    if (tentativas === 1) return Response.json({error: {code: "error", message: "Falha temporária"}}, {status: 503});
    return Response.json({run_id: "run-7", aprovacao: {id: "a1"}, board: novo});
  });
  vi.stubGlobal("fetch", fetcher);
  render(<BoardCriativo canal="A"/>);

  fireEvent.click(await screen.findByRole("button", {name: "Criar roteiro"}));
  fireEvent.click(await screen.findByRole("button", {name: "Tentar de novo"}));
  await waitFor(() => expect(push).toHaveBeenCalled());
  expect(fetcher.mock.calls.some(([url]) => String(url).endsWith("/analises"))).toBe(false);
  const corpos = fetcher.mock.calls.filter(([url, init]) => init?.method === "POST" && String(url).endsWith("/aprovacoes")).map(([, init]) => JSON.parse(String(init?.body)));
  expect(corpos).toEqual([{revisao: 9, fluxo_id: "padrao"}, {revisao: 9, fluxo_id: "padrao"}]);
});
