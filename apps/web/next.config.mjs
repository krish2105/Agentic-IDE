/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // @sani/client ships TypeScript source rather than a build artifact, so Next
  // has to compile it the same way it compiles this app.
  transpilePackages: ["@sani/client"],
  // Next 16 serves `/_next/static/*` in dev only to hosts it recognises, and
  // 127.0.0.1 is not the same host as localhost as far as that check is
  // concerned. Without this, a browser pointed at 127.0.0.1:3200 gets a 403 on
  // every chunk: the page server-renders, so it *looks* fine, and then never
  // hydrates. Playwright hits 127.0.0.1 by default, which made the whole e2e
  // suite fail on selectors that were never the problem.
  allowedDevOrigins: ["127.0.0.1", "localhost", "[::1]"],
};

export default nextConfig;
