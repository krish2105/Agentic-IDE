/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // @sani/client ships TypeScript source rather than a build artifact, so Next
  // has to compile it the same way it compiles this app.
  transpilePackages: ["@sani/client"],
};

export default nextConfig;
