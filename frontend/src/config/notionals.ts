/** WHI-799 §4.1 fixed notional tiers (USD). */

export const NOTIONAL_TIERS_USD = [
  "1000",
  "10000",
  "100000",
  "1000000",
] as const;

export type NotionalTierUsd = (typeof NOTIONAL_TIERS_USD)[number];
