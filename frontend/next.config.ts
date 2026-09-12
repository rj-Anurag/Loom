import type { NextConfig } from "next";

const apiOrigin =
  process.env.LOOM_API_INTERNAL_URL ??
  (process.env.LOOM_API_INTERNAL_HOSTPORT
    ? `http://${process.env.LOOM_API_INTERNAL_HOSTPORT}`
    : process.env.VERCEL
      ? "https://loom-api-zzy0.onrender.com"
      : "http://127.0.0.1:8000");

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  async rewrites() {
    return [
      { source: "/v1/:path*", destination: `${apiOrigin}/v1/:path*` },
      { source: "/health", destination: `${apiOrigin}/health` },
      { source: "/ready", destination: `${apiOrigin}/ready` },
    ];
  },
};

export default nextConfig;
