import { useCallback, useEffect, useState } from "react";

export type Screen = "producao" | "fila" | "runs" | "publicacao" | "servicos";

export const SCREENS: readonly Screen[] = ["producao", "fila", "runs", "publicacao", "servicos"];

export function screenHref(screen: Screen): string {
  return `#/${screen}`;
}

/** `#/fila` → "fila"; qualquer outra coisa cai na produção. */
export function parseScreen(hash: string): Screen {
  const name = hash.replace(/^#\/?/, "").split(/[/?]/)[0];
  return (SCREENS as readonly string[]).includes(name) ? (name as Screen) : "producao";
}

/**
 * Tela corrente guardada no hash da URL: cada tela tem endereço próprio e o
 * voltar do navegador funciona, sem trocar o painel cliente por rotas do app.
 * O estado inicial é sempre a produção e o hash só é lido depois de montar,
 * para o HTML do servidor e o primeiro render do cliente coincidirem.
 */
export function useScreen(): [Screen, (screen: Screen) => void] {
  const [screen, setScreen] = useState<Screen>("producao");

  useEffect(() => {
    const sync = () => setScreen(parseScreen(window.location.hash));
    sync();
    window.addEventListener("hashchange", sync);
    window.addEventListener("popstate", sync);
    return () => {
      window.removeEventListener("hashchange", sync);
      window.removeEventListener("popstate", sync);
    };
  }, []);

  const navigate = useCallback((next: Screen) => {
    setScreen(next);
    const href = screenHref(next);
    if (window.location.hash !== href) {
      window.history.pushState(null, "", href);
    }
  }, []);

  return [screen, navigate];
}
