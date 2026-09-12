import type { NextConfig } from "next";

const noStoreHeaders = [
  { key: "Cache-Control", value: "private, no-store" },
  { key: "Pragma", value: "no-cache" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
];

const nextConfig: NextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
  async headers() {
    return [
      { source: "/leads/:path*", headers: noStoreHeaders },
      { source: "/api/internal/:path*", headers: noStoreHeaders },
    ];
  },
};

export default nextConfig;
