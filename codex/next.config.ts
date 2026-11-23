import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  outputFileTracingIncludes: {
    "/api/market": ["./certs/*.pem"],
  },
};

export default nextConfig;
