import React from "react";

export interface ArtifactPreviewProps {
  artifact?: { url: string; type: string; name: string };
}

export function ArtifactPreview({ artifact }: ArtifactPreviewProps) {
  if (!artifact) return <div className="artifact-preview empty">Nenhum artefato</div>;
  return (
    <section aria-label="Pré-visualização do artefato" className="artifact-preview">
      <h3>Artefato: {artifact.name}</h3>
      <a href={artifact.url} target="_blank" rel="noopener noreferrer">
        {artifact.type}: {artifact.url}
      </a>
    </section>
  );
}
