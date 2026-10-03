import type { NextConfig } from "next";

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000").replace(/\/$/, "");

// The session token lives in sessionStorage, so the worst outcome of an
// injected script is a stolen session. This keeps any such script from
// loading from or talking to anywhere but this site and the API. Inline
// scripts stay allowed: Next.js and the theme-before-paint snippet need them.
const csp = [
  "default-src 'self'",
  // `next dev` needs eval for hot reloading; production never gets it.
  `script-src 'self' 'unsafe-inline'${process.env.NODE_ENV === "development" ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self'",
  `connect-src 'self' ${API_BASE}`,
  "frame-src blob:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const nextConfig: NextConfig = {
  async headers() {
    return [{ source: "/(.*)", headers: [{ key: "Content-Security-Policy", value: csp }] }];
  },
};

export default nextConfig;
