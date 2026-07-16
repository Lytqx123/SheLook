import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",

  // recharts 3.x 跟 Turbopack 不太对付，必须 transpile
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

  // 代理到后端，Docker里用backend:8000，本地用localhost:8000
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
