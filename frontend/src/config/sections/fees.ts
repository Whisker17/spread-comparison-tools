import { NOTIONAL_TIERS_USD } from "@/config/notionals";
import type { AssetResponse } from "@/lib/api";
import { compareVenueSlug } from "@/lib/feesTable";

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

/**
 * Asset switcher options from GET /assets (category is a plain string — read
 * at runtime). Majors first, then the rest of the catalog A–Z.
 */
export function assetSwitcherOptions(
  assets: readonly AssetResponse[] | undefined,
): string[] {
  if (!assets || assets.length === 0) {
    return [...FEES_FALLBACK_ASSETS];
  }
  const preferred = new Set<string>(FEES_FALLBACK_ASSETS);
  const majors = assets
    .map((a) => a.id.toUpperCase())
    .filter((id) => preferred.has(id));
  const rest = assets
    .map((a) => a.id.toUpperCase())
    .filter((id) => !preferred.has(id))
    .sort(compareVenueSlug);
  const seen = new Set<string>();
  const out: string[] = [];
  for (const id of [...majors, ...rest]) {
    if (seen.has(id)) continue;
    seen.add(id);
    out.push(id);
  }
  return out.length > 0 ? out : [...FEES_FALLBACK_ASSETS];
}
