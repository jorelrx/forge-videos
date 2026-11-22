import { afterEach, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BoardCriativo } from "./board-criativo";

vi.mock("next/navigation", () => ({useRouter: () => ({push: vi.fn()})}));

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

const pauta = {
  titulo: "Um ensaio", tema: "Escolhas", pergunta: "Por que adiamos?", recorte: "Cozinha", promessa: "Entender",
  abertura: "Abre na pia", blocos: ["A cena"], desfecho: "Volta", perguntas_pesquisa: [], referencias: [],
};
const base = {
  revisao: 4, propostas: [], guardadas: [], candidata: null, origem_pauta: null, pauta, operacao: null, erro: null,
  posicionamento: "Canal", fluxo_id: "padrao", analisado_em: null,
  fluxos: [{id: "padrao", nome: "Padrão", descricao: "Roteiro atual", disponivel: true, motivo: null}],
  pendencias: [],
  contexto: {precisa_posicionamento: false, aguardando: false, observacoes: [], estado_catalogo: "atualizado",
    estado_analytics: "atualizado", atualizado_em: null},
  conversa: [
    {id: "m1", autor: "criador", texto: "Melhore a abertura", criada_em: "", base_revisao: null, alteracoes: [], aplicadas: []},
    {id: "m2", autor: "ia", texto: "Sugiro outra abertura.", criada_em: "", base_revisao: 3, aplicadas: [],
      alteracoes: [{campo: "abertura", anterior: "Abre na pia", valor: "Abre no ônibus"}]},
  ],
};

function corpo(call: unknown[]) {
  const init = call[1] as RequestInit | undefined;
  return init?.body ? JSON.parse(String(init.body)) : null;
}

it("aplica só a abertura proposta pela IA", async () => {
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (_url, init) => {
    if (init?.method === "PUT") return Response.json({...base, revisao: 5, pauta: {...pauta, abertura: "Abre no ônibus"}});
    return Response.json(base);
  });
  vi.stubGlobal("fetch", fetcher);
  render(<BoardCriativo canal="A"/>);

  expect(await screen.findByText("Abre no ônibus")).toBeTruthy();
  fireEvent.click(screen.getByRole("checkbox", {name: /Abertura/}));
  fireEvent.click(screen.getByRole("button", {name: "Aplicar selecionadas (1)"}));
  await waitFor(() => expect(fetcher.mock.calls.some(c => corpo(c)?.acao === "aplicar_sugestao")).toBe(true));
  const put = fetcher.mock.calls.find(c => corpo(c)?.acao === "aplicar_sugestao")!;
  expect(corpo(put)).toEqual({revisao: 4, acao: "aplicar_sugestao", mensagem_id: "m2", campos: ["abertura"]});
});

it("conflito mostra a versão atual e reaplica a edição", async () => {
  const outraAba = {...base, revisao: 6, pauta: {...pauta, desfecho: "Desfecho da outra aba"}};
  let leituras = 0;
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (_url, init) => {
    if (init?.method === "PUT") {
      const body = JSON.parse(String(init.body));
      if (body.revisao === 4) return Response.json({error: {code: "revisao_board", message: "Outra aba"}}, {status: 409});
      return Response.json({...outraAba, revisao: 7, pauta: body.pauta});
    }
    leituras += 1;
    return Response.json(leituras === 1 ? base : outraAba);
  });
  vi.stubGlobal("fetch", fetcher);
  render(<BoardCriativo canal="A"/>);

  fireEvent.change(await screen.findByLabelText("Tema"), {target: {value: "Escolhas difíceis"}});
  fireEvent.click(screen.getByRole("button", {name: "Salvar pauta"}));
  expect(await screen.findByRole("heading", {name: /Outra aba salvou a pauta \(revisão 6\)/})).toBeTruthy();
  expect(screen.getByText("Escolhas difíceis")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", {name: "Reaplicar minha edição"}));
  await waitFor(() => expect(fetcher.mock.calls.some(c => corpo(c)?.revisao === 6)).toBe(true));
  const reaplicada = fetcher.mock.calls.find(c => corpo(c)?.revisao === 6)!;
  expect(corpo(reaplicada).pauta.tema).toBe("Escolhas difíceis");
});

it("revisão final aponta pendência ao lado de Criar roteiro", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({
    ...base, pauta: {...pauta, blocos: []}, pendencias: [{campo: "blocos", mensagem: "Inclua pelo menos um bloco."}],
  })));
  render(<BoardCriativo canal="A"/>);

  const criar = await screen.findByRole("button", {name: "Criar roteiro"});
  expect((criar as HTMLButtonElement).disabled).toBe(true);
  expect(document.getElementById("board-create-reason")?.textContent).toBe("Inclua pelo menos um bloco.");
});

it("abas preservam o texto digitado", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(base)));
  render(<BoardCriativo canal="A"/>);

  fireEvent.click(await screen.findByRole("tab", {name: "Conversa"}));
  fireEvent.change(screen.getByLabelText("Mensagem"), {target: {value: "Rascunho da pergunta"}});
  fireEvent.change(screen.getByLabelText("Desfecho"), {target: {value: "Desfecho em edição"}});
  fireEvent.click(screen.getByRole("tab", {name: "Pauta"}));
  fireEvent.click(screen.getByRole("tab", {name: "Conversa"}));
  expect((screen.getByLabelText("Mensagem") as HTMLTextAreaElement).value).toBe("Rascunho da pergunta");
  expect((screen.getByLabelText("Desfecho") as HTMLTextAreaElement).value).toBe("Desfecho em edição");
});

it("salva sozinho depois de uma pausa na digitação", async () => {
  vi.useFakeTimers({shouldAdvanceTime: true});
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (_url, init) =>
    Response.json(init?.method === "PUT" ? {...base, revisao: 5, pauta: JSON.parse(String(init.body)).pauta} : base));
  vi.stubGlobal("fetch", fetcher);
  render(<BoardCriativo canal="A"/>);

  fireEvent.change(await screen.findByLabelText("Promessa"), {target: {value: "Entender por que adiamos"}});
  expect(fetcher.mock.calls.some(c => (c[1] as RequestInit | undefined)?.method === "PUT")).toBe(false);
  await act(async () => { vi.advanceTimersByTime(1300); });
  await waitFor(() => expect(fetcher.mock.calls.some(c => corpo(c)?.pauta?.promessa === "Entender por que adiamos")).toBe(true));
});

it("espaço no fim do texto não faz o salvamento automático repetir", async () => {
  vi.useFakeTimers({shouldAdvanceTime: true});
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (_url, init) => {
    if (init?.method !== "PUT") return Response.json(base);
    const enviada = JSON.parse(String(init.body)).pauta;
    return Response.json({...base, revisao: 5, pauta: {...enviada, promessa: enviada.promessa.trim()}});
  });
  vi.stubGlobal("fetch", fetcher);
  render(<BoardCriativo canal="A"/>);

  fireEvent.change(await screen.findByLabelText("Promessa"), {target: {value: "Entender o adiamento "}});
  await act(async () => { vi.advanceTimersByTime(1300); });
  await waitFor(() => expect(fetcher.mock.calls.filter(c => corpo(c)?.acao === "pauta")).toHaveLength(1));
  await act(async () => { vi.advanceTimersByTime(4000); });
  expect(fetcher.mock.calls.filter(c => corpo(c)?.acao === "pauta")).toHaveLength(1);
});

it("gravação de outra aba substitui a cópia local sem edição pendente", async () => {
  vi.useFakeTimers({shouldAdvanceTime: true});
  const salvo = {...base, revisao: 5, pauta: {...pauta, promessa: "Minha promessa"}};
  const outraAba = {...base, revisao: 6, pauta: {...pauta, promessa: "Promessa da outra aba"}};
  let leituras = 0;
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (_url, init) => {
    if (init?.method === "PUT") return Response.json(salvo);
    if (init?.method === "POST") return Response.json({estado_catalogo: "atualizado", estado: "atualizado"}, {status: 202});
    leituras += 1;
    return Response.json(leituras === 1 ? base : outraAba);
  });
  vi.stubGlobal("fetch", fetcher);
  render(<BoardCriativo canal="A"/>);

  fireEvent.change(await screen.findByLabelText("Promessa"), {target: {value: "Minha promessa"}});
  await act(async () => { vi.advanceTimersByTime(1300); });
  await waitFor(() => expect(fetcher.mock.calls.some(c => corpo(c)?.acao === "pauta")).toBe(true));
  fireEvent.click(screen.getByRole("button", {name: /Atualizar histórico/}));
  await waitFor(() => expect((screen.getByLabelText("Promessa") as HTMLTextAreaElement).value).toBe("Promessa da outra aba"));
  await act(async () => { vi.advanceTimersByTime(3000); });
  expect(fetcher.mock.calls.filter(c => corpo(c)?.acao === "pauta")).toHaveLength(1);
  expect(screen.queryByText(/Outra aba salvou a pauta/)).toBeNull();
});

it("envio da conversa espera a análise de propostas", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({...base, operacao: "sugestoes"})));
  render(<BoardCriativo canal="A"/>);
  fireEvent.change(await screen.findByLabelText("Mensagem"), {target: {value: "Uma pergunta"}});
  expect((screen.getByRole("button", {name: "Enviar"}) as HTMLButtonElement).disabled).toBe(true);
});
