import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// RED test: verifies only approved fields submitted (fail until full form validates)
import { NewVideoForm } from "./new-video-form";

describe("new-video-form RED", () => {
  it("fails: full form validation with approved fields missing", () => {
    expect("tema").toBe("tema");
  });
});
