import React from "react";
import { screenHref, type Screen } from "../hooks/use-screen";
import {
  IconHistory,
  IconPlus,
  IconProduction,
  IconQueue,
  IconServer,
  IconUpload,
} from "./icons";

const NAV: { screen: Screen; label: string; Icon: (p: { size?: number }) => React.ReactElement }[] = [
  { screen: "producao", label: "Produção", Icon: IconProduction },
  { screen: "fila", label: "Fila", Icon: IconQueue },
  { screen: "runs", label: "Execuções", Icon: IconHistory },
  { screen: "publicacao", label: "Publicação", Icon: IconUpload },
  { screen: "servicos", label: "Serviços", Icon: IconServer },
];

export function Sidebar({
  screen,
  onNavigate,
  onNewRun,
  queueCount,
}: {
  screen: Screen;
  onNavigate: (screen: Screen) => void;
  onNewRun: () => void;
  queueCount: number;
}) {
  return (
    <aside className="sidebar" aria-label="Navegação">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">
          <svg viewBox="0 0 20 20" width="14" height="14">
            <path d="M5 3h11v3H8.5v3H14v3H8.5v5H5z" fill="currentColor" />
          </svg>
        </span>
        <span className="brand-name">Forge Studio</span>
      </div>

      <button className="new-run-btn" data-choice="new-run" type="button" onClick={onNewRun}>
        <IconPlus size={16} />
        <span>Novo vídeo</span>
      </button>

      <nav className="nav" aria-label="Telas">
        {NAV.map(({ screen: target, label, Icon }) => {
          const active = target === screen;
          return (
            <a
              key={target}
              href={screenHref(target)}
              className={`nav-item${active ? " active" : ""}`}
              aria-current={active ? "page" : undefined}
              onClick={(event) => {
                event.preventDefault();
                onNavigate(target);
              }}
            >
              <Icon size={17} />
              <span className="nav-label">{label}</span>
              {target === "fila" && queueCount > 0 && (
                <span className="nav-count" aria-label={`${queueCount} na fila`}>{queueCount}</span>
              )}
            </a>
          );
        })}
      </nav>
    </aside>
  );
}
