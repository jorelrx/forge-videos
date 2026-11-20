import type React from "react";
import type { Screen } from "../hooks/use-screen";
import { IconHistory, IconProduction, IconQueue, IconServer, IconUpload } from "./icons";

/**
 * Nome e ícone de cada tela. A cor de cada uma vem do CSS
 * (`[data-screen="..."]` → `--screen-hue`), a mesma na barra lateral e no
 * cabeçalho da página, para a tela ser reconhecível de relance.
 */
export const SCREEN_META: { screen: Screen; label: string; Icon: (p: { size?: number }) => React.ReactElement }[] = [
  { screen: "producao", label: "Produção", Icon: IconProduction },
  { screen: "fila", label: "Fila", Icon: IconQueue },
  { screen: "runs", label: "Execuções", Icon: IconHistory },
  { screen: "publicacao", label: "Publicação", Icon: IconUpload },
  { screen: "servicos", label: "Serviços", Icon: IconServer },
];

export function screenIcon(screen: Screen) {
  return SCREEN_META.find((m) => m.screen === screen)?.Icon ?? IconProduction;
}
