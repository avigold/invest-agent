/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      { source: "/api/:path*", destination: "http://localhost:8000/api/:path*" },
      { source: "/auth/:path*", destination: "http://localhost:8000/auth/:path*" },
      { source: "/healthz", destination: "http://localhost:8000/healthz" },
    ];
  },
};

module.exports = nextConfig;
