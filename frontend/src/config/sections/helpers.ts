import type { SectionConfig } from "@/config/sections/types";

/**
 * Shared section helpers for WHI-809/810/811.
 * Lives outside any one section module so concurrent section PRs can share
 * filtering without importing a sibling section's config.
 */

/** Merge section-level + per-asset hidden venues for one asset. */
export function hiddenVenuesForAsset(
  section: SectionConfig,
  asset: string,
): string[] {
  const global = section.hiddenVenues ?? [];
  const perAsset = section.hiddenVenuesByAsset?.[asset] ?? [];
  return [...new Set([...global, ...perAsset])];
}

/**
 * Visible venue row order for an asset: section venues minus hidden.
 * When `section.venues` is empty, returns [] (caller may fall back to API union).
 */
export function venuesForAsset(
  section: SectionConfig,
  asset: string,
): string[] {
  const hidden = new Set(hiddenVenuesForAsset(section, asset));
  if (section.venues.length === 0) {
    return [];
  }
  return section.venues.filter((v) => !hidden.has(v));
}
