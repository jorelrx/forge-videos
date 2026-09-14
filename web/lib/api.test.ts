import { describe, it, expect } from "vitest";
import { fetchVideos } from "./api";

describe("fetchVideos", () => {
  it("returns a list", async () => {
    const videos = await fetchVideos();
    expect(Array.isArray(videos)).toBe(true);
  });
});
