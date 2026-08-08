/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The IDE is a single long-lived client surface; nothing here is statically
  // renderable, so there is no reason to pay for prerender attempts.
  experimental: {},
};

export default nextConfig;
