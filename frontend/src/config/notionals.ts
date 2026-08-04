/** WHI-799 §4.1 fixed notional tiers (USD) — must match backend models.NOTIONAL_TIERS_USD. */

import { SIZE_ALL } from "@/lib/notionalSize";

export const NOTIONAL_TIERS_USD = [
  "100",
  "1000",
  "10000",
  "100000",
  "1000000",
] as const;

export type NotionalTierUsd = (typeof NOTIONAL_TIERS_USD)[number];

/**
 * Product default when the size selector focuses a single tier (WHI-841 focus).
 * Multi-column default is ``DEFAULT_SIZE_VIEW`` after WHI-843.
 */
export const DEFAULT_NOTIONAL_USD: NotionalTierUsd = "1000";

/**
 * Default size-selector view: multi-column matrix (WHI-843). Pass as
 * ``section.defaultNotional`` so ``?size=`` absent → all tiers.
 * SSOT for the sentinel is ``SIZE_ALL`` in `lib/notionalSize.ts`.
 */
export const DEFAULT_SIZE_VIEW = SIZE_ALL;
