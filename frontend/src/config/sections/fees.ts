import { NOTIONAL_TIERS_USD } from "@/config/notionals";

/**
 * Fees page config (WHI-813).
 *
 * Cost-composition switcher defaults + poll interval live here so the
 * section component does not hardcode product tunables (frontend/README.md
 * layout convention: config/sections/<id>.ts).
 */

/** Default asset for the live cost view. */
export const FEES_DEFAULT_ASSET = "BTC";

/** Default notional tier ($10k). */
export const FEES_DEFAULT_NOTIONAL: (typeof NOTIONAL_TIERS_USD)[number] =
  "10000";

/** Notional tiers offered on the size switcher. */
export const FEES_NOTIONALS = NOTIONAL_TIERS_USD;

/**
 * Fallback asset list when GET /assets is unavailable.
 * Prefer runtime catalog from the API (category read at runtime).
 */
export const FEES_FALLBACK_ASSETS = ["BTC", "ETH", "SOL"] as const;

/** Live quotes poll for the cost-composition panel. */
export const FEES_POLL_MS = 30_000;
