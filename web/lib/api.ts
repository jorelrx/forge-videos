import { Video } from "./contracts";

export async function fetchVideos(): Promise<Video[]> {
  return [
    { id: "v1", title: "Intro", url: "https://example.com/v1", duration: 120 },
  ];
}
