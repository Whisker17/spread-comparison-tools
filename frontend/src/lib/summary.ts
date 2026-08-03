/**
 * Summary-strip rule engine: best venue per notional tier.
 *
 * Eligibility (WHI-799 §5.2): status=ok AND total_cost_bps is not null
 * (gas_unknown ⇒ total null ⇒ excluded). Shared by all section pages;
 * WHI-818 later swaps the data source without re-implementing the rule.
 */

import type { components } from "@/lib/api-types";
import { parseDecimal } from "@/lib/format";
import { isEligibleForBest } from "@/lib/status";

export type Quote = components["schemas"]["Quote"];
export type SizeQuotePair = components["schemas"]["SizeQuotePair"];

export type SideView = "buy" | "sell" | "round_trip";

export type BestVenuePick = {
  notionalUsd: string;
  venue: string;
  /** Metric used for ranking (total cost). */
  totalCostBps: number;
  side: SideView;
  /** True when no eligible quote existed for this tier. */
  empty: boolean;
};

export type BestVenueOptions = {
  /** Which leg / aggregate to rank on. Default: buy. */
  side?: SideView;
  /**
   * Optional venue allow-list (section config). Empty/undefined = all venues
   * present in `pairs`.
   */
  venues?: readonly string[];
  /**
   * Optional set of venue slugs to hide/disable (section config).
   * Hidden venues never win "best".
   */
  hiddenVenues?: readonly string[];
};

/**
 * Pick the lowest total_cost_bps venue for each notional tier.
 *
 * `pairs` may mix notionals (from multi-notional fan-out). Grouping is by
 * `notional_usd` string as returned by the API.
 */
export function bestVenuePerTier(
  pairs: readonly SizeQuotePair[],
  options: BestVenueOptions = {},
): BestVenuePick[] {
  const side = options.side ?? "buy";
  const allow = options.venues ? new Set(options.venues) : null;
  const hidden = new Set(options.hiddenVenues ?? []);

  const byNotional = new Map<string, SizeQuotePair[]>();
  for (const pair of pairs) {
    if (allow && !allow.has(pair.venue)) continue;
    if (hidden.has(pair.venue)) continue;
    const key = String(pair.notional_usd);
    const bucket = byNotional.get(key);
    if (bucket) {
      bucket.push(pair);
    } else {
      byNotional.set(key, [pair]);
    }
  }

  // Stable notional order: numeric ascending when parseable.
  const notionals = [...byNotional.keys()].sort(
    (a, b) => (parseDecimal(a) ?? 0) - (parseDecimal(b) ?? 0),
  );

  return notionals.map((notionalUsd) => {
    const bucket = byNotional.get(notionalUsd) ?? [];
    let best: BestVenuePick | null = null;

    for (const pair of bucket) {
      const cost = metricForPair(pair, side);
      if (cost === null) continue;
      if (best === null || cost < best.totalCostBps) {
        best = {
          notionalUsd,
          venue: pair.venue,
          totalCostBps: cost,
          side,
          empty: false,
        };
      }
    }

    return (
      best ?? {
        notionalUsd,
        venue: "",
        totalCostBps: Number.POSITIVE_INFINITY,
        side,
        empty: true,
      }
    );
  });
}

/** Extract ranking metric for a pair under the chosen side view. */
export function metricForPair(
  pair: SizeQuotePair,
  side: SideView,
): number | null {
  if (side === "round_trip") {
    // Prefer pair-level round_trip_total_cost_bps when both legs eligible.
    const rt = parseDecimal(pair.round_trip_total_cost_bps);
    if (rt !== null && bothLegsEligible(pair)) {
      return rt;
    }
    // Fall back to sum of eligible legs only when both exist and are eligible.
    if (!bothLegsEligible(pair)) return null;
    const buy = parseDecimal(pair.buy?.total_cost_bps);
    const sell = parseDecimal(pair.sell?.total_cost_bps);
    if (buy === null || sell === null) return null;
    return buy + sell;
  }

  const quote = side === "buy" ? pair.buy : pair.sell;
  if (!isEligibleForBest(quote ?? null)) return null;
  return parseDecimal(quote?.total_cost_bps);
}

function bothLegsEligible(pair: SizeQuotePair): boolean {
  return isEligibleForBest(pair.buy ?? null) && isEligibleForBest(pair.sell ?? null);
}

/**
 * Map of notional → best venue slug (non-empty picks only). Convenient for
 * SpreadMatrix highlight props.
 */
export function bestVenueMap(
  pairs: readonly SizeQuotePair[],
  options: BestVenueOptions = {},
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const pick of bestVenuePerTier(pairs, options)) {
    if (!pick.empty) {
      out[pick.notionalUsd] = pick.venue;
    }
  }
  return out;
}
