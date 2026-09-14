import React from "react";

export interface FailureDrawerProps {
  error?: any;
  open?: boolean;
  onClose?: () => void;
}

export function FailureDrawer({ error, open = true, onClose }: FailureDrawerProps) {
  if (!open || !error) return null;
  return (
    <aside aria-label="Falhas recentes" className="failure-drawer" role="alert">
      <h3>Falhas</h3>
      <pre>{String(error?.message || error || "Erro desconhecido")}</pre>
      {onClose && <button onClick={onClose} aria-label="Fechar">Fechar</button>}
    </aside>
  );
}
