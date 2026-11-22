import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { SessaoStudio, destinoInicial } from "./sessao-studio";

vi.mock("next/navigation", () => ({
  usePathname: () => location.pathname,
  useRouter: () => ({push: vi.fn()}),
}));

const conta = { id: "p", nome: "Joana", avatar: null };
const canal = (id: string) => ({ id, titulo: "Canal " + id, conectado: true });
afterEach(() => vi.unstubAllGlobals());

it("preserva permalink no login e esconde conteúdo privado", async () => {
  history.replaceState(null, "", "/canais/A/videos/teste?inicio=2026-10-01");
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({}, {status:401})));
  render(<SessaoStudio canalId="A">Privado</SessaoStudio>);
  const login = await screen.findByRole("link", {name:"Entrar com Google"});
  expect(new URL(login.getAttribute("href")!, location.origin).searchParams.get("retorno")).toBe(location.pathname + location.search);
  expect(screen.queryByText("Privado")).toBeNull();
});

it("oferece vínculo para zero canais e seletor para vários", async () => {
  let canais: ReturnType<typeof canal>[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => Response.json(url === "/api/sessao" ? conta : {canais})));
  const primeira = render(<SessaoStudio />);
  await screen.findByRole("button", {name:"Vincular canal"});
  primeira.unmount();
  canais = [canal("A"),canal("B")];
  render(<SessaoStudio />);
  expect(await screen.findByRole("combobox", {name:"Canal"})).toBeTruthy();
});

it("restringe permalink, restaura foco e revoga sessão", async () => {
  const fetcher = vi.fn(async (url: string) => url.endsWith("/sair") ? new Response(null,{status:204}) :
    Response.json(url === "/api/sessao" ? conta : {canais:[canal("A")]}));
  vi.stubGlobal("fetch",fetcher);
  const negado = render(<SessaoStudio canalId="B">Privado</SessaoStudio>);
  await screen.findByText("Canal sem acesso");
  expect(screen.queryByText("Privado")).toBeNull();
  negado.unmount();
  render(<SessaoStudio canalId="A">Privado</SessaoStudio>);
  await screen.findByText("Privado");
  const menu = screen.getByRole("button",{name:"Menu"});
  fireEvent.click(menu);
  fireEvent.keyDown(screen.getByRole("navigation",{name:"Canal"}),{key:"Escape"});
  expect(document.activeElement).toBe(menu);
  fireEvent.click(screen.getByRole("button",{name:"Sair"}));
  await waitFor(()=>expect(screen.queryByText("Privado")).toBeNull());
  await screen.findByRole("link",{name:"Entrar com Google"});
});


it("abre o único canal, restaura a última seleção válida e ignora preferência revogada", () => {
  expect(destinoInicial([canal("A")], null)).toBe("A");
  expect(destinoInicial([canal("A"),canal("B")], "B")).toBe("B");
  expect(destinoInicial([canal("A"),canal("B")], "C")).toBeUndefined();
});

it("atualiza os canais ao recuperar foco sem desmontar a página", async () => {
  let titulo = "Canal A";
  let consultas = 0;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url === "/api/sessao") return Response.json(conta);
    if (url !== "/api/canais") return Response.json([]);
    consultas++;
    return Response.json({canais:[{...canal("A"), titulo}]});
  }));
  render(<SessaoStudio canalId="A"><input aria-label="Edição" defaultValue="Rascunho"/></SessaoStudio>);
  const campo = await screen.findByRole("textbox", {name:"Edição"});
  fireEvent.change(campo, {target:{value:"Trabalho em andamento"}});
  titulo = "Nome atualizado";
  fireEvent(window, new Event("focus"));
  await waitFor(() => expect(consultas).toBe(2));
  await screen.findByRole("option", {name:titulo});
  expect(screen.getByRole("textbox", {name:"Edição"})).toBe(campo);
  expect((campo as HTMLInputElement).value).toBe("Trabalho em andamento");
});
