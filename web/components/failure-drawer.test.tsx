import { describe, it, expect } from "vitest";
import { FailureDrawer } from "./failure-drawer";

describe("failure-drawer RED", () => {
  it("fails: failure drawer renders error token", () => {
    expect("token").toBe("failure_rendered");
  });
});
