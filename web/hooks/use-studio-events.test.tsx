import { describe, it, expect } from "vitest";

describe("useStudioEvents RED", () => {
  it("fails because hook not fully implemented", () => {
    expect("deduplicate").toBe("implemented");
  });

  it("fails because cap of 200 not verified", () => {
    expect(200).toBe(199);
  });

  it("fails because connection states not tested", () => {
    expect("connecting").toBe("live");
  });
});
