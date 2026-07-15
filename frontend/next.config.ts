import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",

  // recharts 3.x 与 Turbopack 的 ESM 互操作兼容
  transpilePackages: ["recharts"],

  images: {
    remotePatterns: [
      {
        protocol: "http",
        hostname: "localhost",
        port: "9000",
        pathname: "/product-images/**",
      },
      {
        protocol: "https",
        hostname: "placehold.co",
      },
    ],
  },

  // API 代理 → 后端容器（Docker 内用 backend:8000，本地开发用 localhost:8000）
  async rewrites() {
    const backendUrl = process.env.BACKEND_URL || "http://backend:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
