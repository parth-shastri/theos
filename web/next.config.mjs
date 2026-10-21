/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  agentRules: false,
  poweredByHeader: false,
  images: { unoptimized: true },
};

export default nextConfig;
