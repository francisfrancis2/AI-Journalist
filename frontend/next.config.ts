import type { NextConfig } from "next";

// Server-side proxy target — only reachable within the Docker internal network.
// The browser never sees this URL; it always talks to the Next.js server on port 3000.
const BACKEND = process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",

  async rewrites() {
    return [
      // Proxy all API calls through Next.js → backend (internal network only)
      {
        source: "/api/:path*",
        destination: `${BACKEND}/api/:path*`,
      },
      // Proxy health check
      {
        source: "/health",
        destination: `${BACKEND}/health`,
      },
    ];
  },
};

export default nextConfig;
