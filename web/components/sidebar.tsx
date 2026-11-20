import React from "react";
import { screenHref, type Screen } from "../hooks/use-screen";
import { IconPlus } from "./icons";
import { SCREEN_META } from "./screen-meta";

const NAV = SCREEN_META;

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
          <svg viewBox="0 0 20 20" width="15" height="15">
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
              data-screen={target}
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
