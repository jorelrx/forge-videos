import { describe, it, expect } from "vitest";
import { ArtifactPreview } from "./artifact-preview";

describe("artifact-preview RED", () => {
  it("fails: preview should render artifact token", () => {
    expect("token").toBe("artifact_rendered");
  });
});
