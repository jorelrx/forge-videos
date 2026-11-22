import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // Os eventos do Studio precisam atravessar o proxy sem buffer de compressão.
  compress: false,
  async rewrites() {
    const backend = process.env.FORGE_STUDIO_BACKEND_URL ?? "http://127.0.0.1:8765";
    return [{ source: "/api/:path*", destination: backend.replace(/\/$/, "") + "/api/:path*" }];
  },
  reactStrictMode: true,
};

export default nextConfig;
