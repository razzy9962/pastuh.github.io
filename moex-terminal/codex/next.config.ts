import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Свечи и котировки кешируются в памяти процесса и в заголовках CDN —
  // это снижает нагрузку и расход памяти на бесплатном инстансе.
  compress: true,
  poweredByHeader: false,
  outputFileTracingIncludes: {
    "/api/market": ["./certs/*.pem"],
  },
  experimental: {
    // Турбопакет не нужен в рантайме — меньше памяти при старте.
    optimizePackageImports: ["lucide-react"],
  },
};

export default nextConfig;
