import { afterEach, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { InsightsVideo } from "./insights-video";
afterEach(()=>vi.unstubAllGlobals());
it("retorna à mesma página de resultados e distingue medidas ausentes", async () => {
 vi.stubGlobal("fetch",vi.fn(async()=>Response.json({video:{video_id:"ext",titulo:"Externo"},estado:"sem_dados",serie:[],observacoes:[],retencao:[],janelas:{d7:[],d28:[]}})));
 render(<InsightsVideo canal="A" videoId="ext" consulta="cursor=dois&busca=externo"/>);
 await screen.findByRole("heading",{name:"Externo"});
 expect(screen.getByRole("link",{name:"Voltar ao catálogo"}).getAttribute("href")).toBe("/canais/A?cursor=dois&busca=externo");
 expect(screen.getByText(/Sem dados no período/)).toBeTruthy();
});
