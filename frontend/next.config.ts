import type { NextConfig } from "next";
import { PHASE_PRODUCTION_BUILD } from "next/constants";

import { resolveApiBaseUrl } from "./src/lib/apiBaseUrl";

const nextConfig: NextConfig = {
  /* config options here */
};

/**
 * Fail production *builds* when NEXT_PUBLIC_API_URL would bake a loopback
 * (or missing) origin into every visitor's bundle (WHI-857).
 *
 * Guard only PHASE_PRODUCTION_BUILD — not `next start` — so a host that
 * already has a baked public origin need not re-export the var at runtime.
 * `pnpm dev` uses phase-development-server and keeps the localhost default.
 */
export default function config(phase: string): NextConfig {
  if (phase === PHASE_PRODUCTION_BUILD) {
    resolveApiBaseUrl(process.env.NEXT_PUBLIC_API_URL, { isProduction: true });
  }
  return nextConfig;
}
