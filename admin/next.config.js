/** @type {import('next').NextConfig} */
const nextConfig = {
  // basePath 为 /admin，配合 Nginx /admin 反代
  basePath: "/admin",
  // 将 /api/* 请求转发给 FastAPI（同主机 8000 端口）
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8000/api/:path*",
      },
    ];
  },
};

module.exports = nextConfig;
