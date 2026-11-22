import { afterEach, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { InsightsVideo } from "./insights-video";
afterEach(()=>vi.unstubAllGlobals());
it("retorna à mesma página de resultados e distingue medidas ausentes", async () => {
 vi.stubGlobal("fetch",vi.fn(async()=>Response.json({video:{video_id:"ext",titulo:"Externo"},estado:"sem_dados",serie:[],observacoes:[],retencao:[],janelas:{d7:[],d28:[]}})));
 render(<InsightsVideo canal="A" videoId="ext" consulta="cursor=dois&busca=externo"/>);
 await screen.findByRole("heading",{name:"Externo"});
 expect(screen.getByRole("link",{name:"Voltar ao catálogo"}).getAttribute("href")).toBe("/canais/A?cursor=dois&busca=externo");
 expect(screen.getByText(/Sem dados no período/)).toBeTruthy();
});

it("distingue retenção ausente de zero observado", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({
    video: {video_id: "ext", titulo: "Externo"}, estado: "atualizado", serie: [], observacoes: [],
    retencao: [{posicao: 0.25, proporcao: null}, {posicao: 0.5, proporcao: 0}],
    janelas: {d7: [], d28: []},
  })));
  render(<InsightsVideo canal="A" videoId="ext" consulta=""/>);

  const tabela = await screen.findByRole("table", {hidden: true});
  const [, ausente, zero] = within(tabela).getAllByRole("row", {hidden: true});
  expect(within(ausente).getByText("Indisponível")).toBeTruthy();
  expect(within(zero).getByText("0%")).toBeTruthy();
});
