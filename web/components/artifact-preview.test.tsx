import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ArtifactPreview } from "./artifact-preview";

describe("ArtifactPreview", () => {
  it("renderiza vídeo pelo endpoint seguro de conteúdo", () => {
    render(
      <ArtifactPreview
        artifact={{
          id: "artifact-1",
          kind: "video",
          relative_path: "final.mp4",
          mime_type: "video/mp4",
        }}
      />,
    );

    expect(document.querySelector("video")?.getAttribute("src")).toBe(
      "http://127.0.0.1:8765/api/artifacts/artifact-1/content",
    );
  });
});
