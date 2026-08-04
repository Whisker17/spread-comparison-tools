/** WHI-799 §4.1 fixed notional tiers (USD) — must match backend models.NOTIONAL_TIERS_USD. */

export const NOTIONAL_TIERS_USD = [
  "100",
  "1000",
  "10000",
  "100000",
  "1000000",
] as const;

export type NotionalTierUsd = (typeof NOTIONAL_TIERS_USD)[number];
