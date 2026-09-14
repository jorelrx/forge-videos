import { describe, it, expect } from "vitest";
import { ServiceStrip } from "./service-strip";

describe("service-strip RED", () => {
  it("fails: should render service states with latency tokens", () => {
    expect("token").toBe("latency_token_rendered");
  });
});
