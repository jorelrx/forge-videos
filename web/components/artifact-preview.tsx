import React from "react";
import { artifactContentUrl } from "../lib/api";

export interface ArtifactPreviewProps {
  artifact?: {
    id: string;
    kind: string;
    relative_path: string;
    mime_type: string;
  };
}

function getThumbLabel(kind: string): string {
  if (kind.startsWith("image")) return "imagem";
  if (kind.includes("audio")) return "áudio";
  if (kind.includes("video")) return "vídeo";
  if (kind.includes("script") || kind.includes("roteiro")) return "roteiro";
  return kind;
}

export function ArtifactPreview({ artifact }: ArtifactPreviewProps) {
  if (!artifact) {
    return (
      <div className="artifact-card">
        <h3>Artefato mais recente</h3>
        <div className="empty-state">Nenhum artefato ainda</div>
      </div>
    );
  }

  const url = artifactContentUrl(artifact.id);
  const label = getThumbLabel(artifact.mime_type);
  const title = artifact.relative_path.split("/").pop() ?? artifact.relative_path;
  const short = title.replace(/\.[^.]+$/, "");

  const preview = (() => {
    if (artifact.mime_type.startsWith("image/")) {
      return <img src={url} alt={artifact.kind} style={{ width: "100%", borderRadius: "7px", maxHeight: "126px", objectFit: "cover" }} />;
    }
    if (artifact.mime_type === "audio/wav" || artifact.mime_type.startsWith("audio/")) {
      return <audio controls preload="metadata" src={url} style={{ width: "100%" }} />;
    }
    if (artifact.mime_type === "video/mp4") {
      return <video controls preload="metadata" src={url} style={{ width: "100%", borderRadius: "7px", maxHeight: "126px" }} />;
    }
    return (
      <div className="preview-box" aria-hidden="true">
        <div className="preview-person" />
        <div className="preview-caption">{short}</div>
      </div>
    );
  })();

  return (
    <div className="artifact-card" aria-label="Artefato mais recente">
      <h3>{label === "vídeo" ? "Artefato: " + artifact.relative_path : "Artefato mais recente"}</h3>
      {preview}
      <div className="artifact-meta">
        <span>{artifact.relative_path}</span>
        <span>{artifact.mime_type}</span>
      </div>
    </div>
  );
}
