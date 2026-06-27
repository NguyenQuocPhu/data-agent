/** @type {import('next').NextConfig} */
const backendBaseUrl =
  (process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8200").replace(
    /\/+$/,
    ""
  );

const nextConfig = {
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
  experimental: {
    serverActions: {
      bodySizeLimit: "500mb",
    },
  },
  // Cho phép body lớn qua Next.js router
  api: {
    bodyParser: {
      sizeLimit: "500mb",
    },
    responseLimit: "500mb",
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://backend:8000/:path*",
      },
      {
        source: "/workspace/download",
        destination: "http://backend:8000/workspace/download",
      },
      {
        source: "/file",
        destination: "http://backend:8000/file",
      },
    ];
  },
  webpack: (config, { isServer }) => {
    // 配置 Monaco Editor 使用本地资源
    if (!isServer) {
      config.resolve.fallback = {
        ...config.resolve.fallback,
        fs: false,
        net: false,
        tls: false,
      };
    }
    return config;
  },
}

export default nextConfig
