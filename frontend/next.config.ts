import type { NextConfig } from "next";

import { resolveApiBaseUrl } from "./src/lib/apiBaseUrl";

// Fail production builds early when NEXT_PUBLIC_API_URL would bake a loopback
// (or missing) origin into every visitor's bundle (WHI-857). next dev keeps
// the localhost default via resolveApiBaseUrl isProduction=false.
if (process.env.NODE_ENV === "production") {
  resolveApiBaseUrl(process.env.NEXT_PUBLIC_API_URL, { isProduction: true });
}

const nextConfig: NextConfig = {
  /* config options here */
};

export default nextConfig;
