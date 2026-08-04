/** WHI-799 §4.1 fixed notional tiers (USD) — must match backend models.NOTIONAL_TIERS_USD. */

export const NOTIONAL_TIERS_USD = [
  "100",
  "1000",
  "10000",
  "100000",
  "1000000",
] as const;

export type NotionalTierUsd = (typeof NOTIONAL_TIERS_USD)[number];

/**
 * Product default for the size selector when `?size=` is absent/invalid (WHI-841).
 * Section configs reference this so the shared default is one line to change.
 */
export const DEFAULT_NOTIONAL_USD: NotionalTierUsd = "1000";
