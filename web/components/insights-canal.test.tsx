import { afterEach, it, expect, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { InsightsCanal } from "./insights-canal";

afterEach(() => vi.unstubAllGlobals());
it("preserva busca, cursor e período no link do vídeo externo; zero é observado", async () => {
 const parametros = "busca=externo&cursor=pagina-2&inicio=2026-10-01&fim=2026-10-28";
 vi.stubGlobal("fetch",vi.fn(async (url:string) => Response.json(url.includes("/resumo?") ?
 {inicio:"2026-10-01",fim:"2026-10-28",views:120,minutos:null,estado:"atualizado",observacoes:[],contribuicoes:[],serie:[]} :
 {videos:[{video_id:"ext",titulo:"Externo",publicado_em:"2026-09-01",views:0}],proximo_cursor:null})));
 render(<InsightsCanal canal="A" consulta={parametros}/>);
 const link=await screen.findByRole("link",{name:"Externo"});
 expect(link.getAttribute("href")).toBe("/canais/A/videos/ext?"+parametros);
 expect(screen.getByText("120")).toBeTruthy();
 expect(screen.getByText("0")).toBeTruthy();
});


const resumo = {inicio:"2026-10-01",fim:"2026-10-28",views:120,minutos:0,estado:"atualizado",observacoes:[],contribuicoes:[],serie:[]};
it("descarta leitura lenta de A depois da troca para B", async () => {
  let liberar!: (value: Response)=>void;
  vi.stubGlobal("fetch",vi.fn((url:string)=>{
    if(url.startsWith("/api/canais/A/resumo")) return new Promise<Response>(ok=>{liberar=ok;});
    return Promise.resolve(Response.json(url.includes("/resumo") ? {...resumo, views:99} : {videos:[],proximo_cursor:null}));
  }));
  const view=render(<InsightsCanal canal="A" consulta=""/>);
  view.rerender(<InsightsCanal canal="B" consulta=""/>);
  await screen.findByText("99");
  await act(async()=>liberar(Response.json(resumo)));
  expect(screen.queryByText("120")).toBeNull();
  expect(screen.getByText("99")).toBeTruthy();
});

it("recupera falha transitória e consulta o novo período", async () => {
  let tentativa=0;
  const fetcher=vi.fn(async (url:string)=>{
    if(!url.includes("/resumo")) return Response.json({videos:[],proximo_cursor:null});
    if(++tentativa===1) return Response.json({detail:"Fonte indisponível"},{status:503});
    return Response.json(resumo);
  });
  vi.stubGlobal("fetch",fetcher);
  const view=render(<InsightsCanal canal="A" consulta="inicio=2026-10-01&fim=2026-10-28"/>);
  fireEvent.click(await screen.findByRole("button",{name:"Tentar novamente"}));
  await screen.findByText("120");
  view.rerender(<InsightsCanal canal="A" consulta="inicio=2026-09-01&fim=2026-09-28"/>);
  expect(fetcher.mock.calls.map(c=>c[0])).toContain("/api/canais/A/resumo?inicio=2026-09-01&fim=2026-09-28");
});
