/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  // Docker prod image installs with --omit=dev (no ESLint); lint locally via npm run lint.
  eslint: { ignoreDuringBuilds: true },
};

module.exports = nextConfig;
