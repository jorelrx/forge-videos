import React, { useEffect, useRef, useState } from "react";
import { screenHref, type Screen } from "../hooks/use-screen";
import { IconHistory, IconPlus, IconProduction } from "./icons";
import { SCREEN_META } from "./screen-meta";
import Link from "next/link";

const NAV = SCREEN_META;

export function Sidebar({
  screen,
  onNavigate,
  onNewRun,
  queueCount = 0,
  channelBase,
  boardAtivo = false,
}: {
  screen?: Screen;
  onNavigate?: (screen: Screen) => void;
  onNewRun?: () => void;
  queueCount?: number;
  channelBase?: string;
  boardAtivo?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const menu = useRef<HTMLButtonElement>(null);
  const nav = useRef<HTMLElement>(null);
  const production = channelBase ? channelBase + "/producao" : "";

  useEffect(() => {
    if (!open) return;
    nav.current?.querySelector("a")?.focus();
    function fechar(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        menu.current?.focus();
      }
    }
    document.addEventListener("keydown", fechar);
    return () => document.removeEventListener("keydown", fechar);
  }, [open]);

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

      {channelBase && <button className="btn studio-menu" type="button" ref={menu}
        aria-expanded={open} aria-controls="studio-navigation" onClick={() => setOpen(!open)}>Menu</button>}
      {onNewRun ? (
        <button className="new-run-btn" data-choice="new-run" type="button" onClick={onNewRun}>
          <IconPlus size={16} />
          <span>Novo vídeo</span>
        </button>
      ) : channelBase && (
        <Link className="new-run-btn" href={production + "#/producao?novo=1"}>
          <IconPlus size={16} />
          <span>Novo vídeo</span>
        </Link>
      )}

      <nav ref={nav} id="studio-navigation" className={`nav${open ? " nav-open" : ""}`}
        aria-label={channelBase ? "Canal" : "Telas"}>
        {channelBase && <>
          <Link href={channelBase} className={`nav-item${!screen && !boardAtivo ? " active" : ""}`}
            onClick={() => setOpen(false)} data-screen="insights" aria-current={!screen && !boardAtivo ? "page" : undefined} title="Vídeos e insights">
            <IconHistory size={17} /><span className="nav-label">Vídeos e insights</span>
          </Link>
          <Link href={channelBase + "/proximo-video"} className={`nav-item${boardAtivo ? " active" : ""}`}
            onClick={() => setOpen(false)} data-screen="board" aria-current={boardAtivo ? "page" : undefined} title="Próximo vídeo">
            <IconProduction size={17} /><span className="nav-label">Próximo vídeo</span>
          </Link>
        </>}
        {NAV.map(({ screen: target, label, Icon }) => {
          const active = target === screen;
          return (
            <Link
              key={target}
              href={onNavigate ? screenHref(target) : production + screenHref(target)}
              className={`nav-item${active ? " active" : ""}`}
              data-screen={target}
              aria-current={active ? "page" : undefined}
              title={label}
              onClick={(event) => {
                if (onNavigate && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) {
                  event.preventDefault();
                  onNavigate(target);
                  if (open) {
                    setOpen(false);
                    menu.current?.focus();
                  }
                }
              }}
            >
              <Icon size={17} />
              <span className="nav-label">{label}</span>
              {target === "fila" && queueCount > 0 && (
                <span className="nav-count" aria-label={`${queueCount} na fila`}>{queueCount}</span>
              )}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
