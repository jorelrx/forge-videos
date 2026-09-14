import React from "react";

export interface FailureDrawerProps {
  error?: any;
  open?: boolean;
  onClose?: () => void;
  onRetryFailed?: () => void;
}

export function FailureDrawer({ error, open = true, onClose, onRetryFailed }: FailureDrawerProps) {
  if (!open || !error) return null;
  const message = error?.message || String(error) || "Erro desconhecido";

  return (
    <div className="failure-box" role="alert" aria-label="Falhas recentes">
      <b>{message}</b>
      <p>O run pode concluir parcialmente. Falhas permanecem visíveis no manifesto.</p>
      {onRetryFailed && (
        <button className="retry-btn" type="button" onClick={onRetryFailed}>
          Repetir somente os falhos
        </button>
      )}
    </div>
  );
}
