import type { NextConfig } from "next";

const API = process.env.SIGNAL_API_URL ?? "http://localhost:8710";

const nextConfig: NextConfig = {
  reactCompiler: true,
  // Same-origin proxy: the browser only talks to the web origin, so session + CSRF cookies just work.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/:path*` }];
  },
  turbopack: {
    rules: {
      "*.css": { loaders: ["@tailwindcss/turbopack"], as: "*.css" },
    },
  },
};

export default nextConfig;
