import { afterEach } from "vitest";

// A tela corrente vive no hash da URL; o jsdom mantém a URL entre testes do
// mesmo arquivo, então cada teste começa de novo na Produção.
afterEach(() => {
  window.history.replaceState(null, "", "/");
});
