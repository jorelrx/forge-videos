import React from "react";

export interface QueueProps {
  runs: Array<{ video: { tema: string }; progress: number; run: { status: string } }>;
}

export function Queue({ runs }: QueueProps) {
  if (runs.length === 0) return <p>Nenhum vídeo aguardando</p>;
  return (
    <ul aria-label="Fila de vídeos">
      {runs.map((r, i) => (
        <li key={i}>
          <span>{r.video?.tema || "Sem tema"}</span>
          <span>Prioridade: {i + 1}</span>
        </li>
      ))}
    </ul>
  );
}
