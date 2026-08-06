/**
 * Summary-strip rule engine: best venue (or form-class row) per notional tier.
 *
 * Eligibility (WHI-799 §5.2): status=ok AND total_cost_bps is not null
 * (gas_unknown ⇒ total null ⇒ excluded). Shared by all section pages;
 * WHI-818 later swaps the data source without re-implementing the rule.
 *
 * Stocks (WHI-882 / WHI-799 §5.2 v3): when pairs carry `form`, default best
 * is grouped by `form_class` (perp | tokenized) — one winner per class per
 * tier. Non-stocks keep a single global winner per tier.
 */

import type { components } from "@/lib/api-types";
import { formatNotional, parseDecimal, sortNotionals } from "@/lib/format";
import {
  formClassOf,
  pairRowKey,
  pairsHaveForms,
  type FormClass,
} from "@/lib/pairIdentity";
import { isEligibleForBest } from "@/lib/status";

export type Quote = components["schemas"]["Quote"];
export type SizeQuotePair = components["schemas"]["SizeQuotePair"];

export type SideView = "buy" | "sell" | "round_trip";

/** Ranking / cell metric — single union shared with status + section config. */
export type RankMetric = "total_cost_bps" | "spread_bps";

export type BestVenuePick = {
  notionalUsd: string;
  venue: string;
  /** Stock form id when present (WHI-881). */
  form?: string | null;
  /** form_class for §5.2 grouping when form is set. */
  formClass?: FormClass | null;
  /**
   * Matrix row key: `venue` (crypto) or `venue|form` (stocks).
   * Best-highlight and labels key off this.
   */
  rowKey: string;
  /** Metric value used for ranking (bps). Name is historical; holds whichever metric. */
  valueBps: number;
  /** Which metric was ranked. */
  metric: RankMetric;
  side: SideView;
  /** True when no eligible quote existed for this tier (or form_class bucket). */
  empty: boolean;
};

export type BestVenueOptions = {
  /** Which leg / aggregate to rank on. Default: buy. */
  side?: SideView;
  /** Metric to minimize. Default total_cost_bps (WHI-799 §5.2 eligibility applies). */
  metric?: RankMetric;
  /**
   * Optional allow-list of venue slugs **or** row keys (`venue|form`).
   * Empty/undefined = all pairs.
   */
  venues?: readonly string[];
  /**
   * Optional set of venue slugs / row keys to hide/disable.
   * Hidden rows never win "best".
   */
  hiddenVenues?: readonly string[];
};

function pairAllowed(
  pair: SizeQuotePair,
  allow: Set<string> | null,
  hidden: Set<string>,
): boolean {
  const rowKey = pairRowKey(pair);
  if (hidden.has(pair.venue) || hidden.has(rowKey)) return false;
  if (!allow) return true;
  return allow.has(pair.venue) || allow.has(rowKey);
}

function pickFromBucket(
  bucket: readonly SizeQuotePair[],
  notionalUsd: string,
  side: SideView,
  metric: RankMetric,
): BestVenuePick | null {
  let best: BestVenuePick | null = null;
  for (const pair of bucket) {
    const cost = metricForPair(pair, side, metric);
    if (cost === null) continue;
    const rowKey = pairRowKey(pair);
    // Strictly lower cost wins; equal cost → stable rowKey tiebreak.
    if (
      best === null ||
      cost < best.valueBps ||
      (cost === best.valueBps && rowKey < best.rowKey)
    ) {
      const form = pair.form ?? null;
      best = {
        notionalUsd,
        venue: pair.venue,
        form,
        formClass: formClassOf(form),
        rowKey,
        valueBps: cost,
        metric,
        side,
        empty: false,
      };
    }
  }
  return best;
}

/**
 * Pick the lowest total_cost_bps row for each notional tier.
 *
 * When any pair has a stock `form`, group by form_class first (WHI-799 §5.2
 * v3) and emit one pick per class per tier. Otherwise emit one global pick
 * per tier (blue chips / others).
 *
 * `pairs` may mix notionals (from multi-notional fan-out). Grouping is by
 * `notional_usd` string as returned by the API.
 */
export function bestVenuePerTier(
  pairs: readonly SizeQuotePair[],
  options: BestVenueOptions = {},
): BestVenuePick[] {
  const side = options.side ?? "buy";
  const metric = options.metric ?? "total_cost_bps";
  const allow = options.venues ? new Set(options.venues) : null;
  const hidden = new Set(options.hiddenVenues ?? []);
  const formAware = pairsHaveForms(pairs);

  const byNotional = new Map<string, SizeQuotePair[]>();
  for (const pair of pairs) {
    if (!pairAllowed(pair, allow, hidden)) continue;
    const key = String(pair.notional_usd);
    const bucket = byNotional.get(key);
    if (bucket) {
      bucket.push(pair);
    } else {
      byNotional.set(key, [pair]);
    }
  }

  const notionals = sortNotionals([...byNotional.keys()]);
  const out: BestVenuePick[] = [];

  for (const notionalUsd of notionals) {
    const bucket = byNotional.get(notionalUsd) ?? [];

    if (!formAware) {
      const best = pickFromBucket(bucket, notionalUsd, side, metric);
      out.push(
        best ?? {
          notionalUsd,
          venue: "",
          form: null,
          formClass: null,
          rowKey: "",
          valueBps: Number.POSITIVE_INFINITY,
          metric,
          side,
          empty: true,
        },
      );
      continue;
    }

    // form_class partitions: perp vs tokenized (WHI-799 §5.2 v3 default).
    const byClass = new Map<FormClass, SizeQuotePair[]>();
    for (const pair of bucket) {
      const fc = formClassOf(pair.form);
      if (!fc) continue;
      const classBucket = byClass.get(fc);
      if (classBucket) {
        classBucket.push(pair);
      } else {
        byClass.set(fc, [pair]);
      }
    }

    // Stable form_class order for summary prose.
    const classOrder: FormClass[] = ["perp", "tokenized"];
    let emitted = false;
    for (const fc of classOrder) {
      const classBucket = byClass.get(fc);
      if (!classBucket) continue;
      const best = pickFromBucket(classBucket, notionalUsd, side, metric);
      if (best) {
        out.push(best);
        emitted = true;
      }
    }
    if (!emitted) {
      out.push({
        notionalUsd,
        venue: "",
        form: null,
        formClass: null,
        rowKey: "",
        valueBps: Number.POSITIVE_INFINITY,
        metric,
        side,
        empty: true,
      });
    }
  }

  return out;
}

/**
 * Read ranking metric from a pair. Round-trip values come **only** from the
 * aggregator pair fields (backend `costs.py` is the sole formula owner) —
 * never re-sum legs client-side.
 */
export function metricForPair(
  pair: SizeQuotePair,
  side: SideView,
  metric: RankMetric = "total_cost_bps",
): number | null {
  if (side === "round_trip") {
    if (metric === "total_cost_bps") {
      if (!bothLegsEligible(pair)) return null;
      return parseDecimal(pair.round_trip_total_cost_bps);
    }
    if (pair.buy?.status !== "ok" || pair.sell?.status !== "ok") return null;
    if (pair.buy.quote_stale || pair.sell.quote_stale) return null;
    return parseDecimal(pair.round_trip_spread_bps);
  }

  const quote = side === "buy" ? pair.buy : pair.sell;
  if (!quote || quote.status !== "ok") return null;
  // WHI-846: stale store rows never rank as best (any metric).
  if (quote.quote_stale) return null;
  if (metric === "total_cost_bps") {
    if (!isEligibleForBest(quote)) return null;
    return parseDecimal(quote.total_cost_bps);
  }
  return parseDecimal(quote.spread_bps);
}

/** Both legs pass WHI-799 §5.2 total-cost eligibility. Shared with SpreadMatrix. */
export function bothLegsEligible(pair: SizeQuotePair): boolean {
  return (
    isEligibleForBest(pair.buy ?? null) && isEligibleForBest(pair.sell ?? null)
  );
}

/**
 * Map of notional → best **row key** (non-empty picks only).
 *
 * When form_class grouping yields multiple winners, the **overall cheapest**
 * row key is stored (for simple call sites). Prefer `bestRowKeysByNotional`
 * for matrix multi-badge highlight.
 */
export function bestVenueMap(
  pairs: readonly SizeQuotePair[],
  options: BestVenueOptions = {},
): Record<string, string> {
  const out: Record<string, string> = {};
  const bestCost: Record<string, number> = {};
  for (const pick of bestVenuePerTier(pairs, options)) {
    if (pick.empty) continue;
    const prev = bestCost[pick.notionalUsd];
    if (
      prev === undefined ||
      pick.valueBps < prev ||
      (pick.valueBps === prev && pick.rowKey < (out[pick.notionalUsd] ?? ""))
    ) {
      out[pick.notionalUsd] = pick.rowKey;
      bestCost[pick.notionalUsd] = pick.valueBps;
    }
  }
  return out;
}

/**
 * Map of notional → set of best row keys (one per form_class when form-aware).
 * Used by SpreadMatrix for multi-badge §5.2 highlight.
 */
export function bestRowKeysByNotional(
  pairs: readonly SizeQuotePair[],
  options: BestVenueOptions = {},
): Record<string, ReadonlySet<string>> {
  const out: Record<string, Set<string>> = {};
  for (const pick of bestVenuePerTier(pairs, options)) {
    if (pick.empty) continue;
    const set = out[pick.notionalUsd] ?? new Set<string>();
    set.add(pick.rowKey);
    out[pick.notionalUsd] = set;
  }
  return out;
}

export type SnapshotSummaryOptions = BestVenueOptions & {
  /** Logical asset id shown in the prose (e.g. "BTC"). */
  asset: string;
  /**
   * Map venue slug **or** row key → display label used in the sentence.
   * Defaults to the raw key when missing.
   */
  venueLabels?: Readonly<Record<string, string>>;
};

/**
 * Point-in-time prose summary of best venue per tier (WHI-809 Phase 1).
 *
 * Uses the same WHI-799 §5.2 eligibility as `bestVenuePerTier` — non-ok and
 * gas_unknown / cost-incomplete venues never appear. Empty when no tier has
 * an eligible pick.
 *
 * Stocks with forms (WHI-882): one clause per form_class per tier, with a
 * class tag so perp vs tokenized winners are not conflated.
 *
 * WHI-841 single-tier pages pass pairs for only the selected size; the prose
 * still names that size explicitly ("At $10k, …") so the figure is never
 * read as size-independent. Multi-tier wording is unchanged when more data
 * is present (e.g. after server-side batching returns).
 *
 * Example:
 *   "At $10k, HumidiFi has the lowest total cost for BTC (2.1 bps); at $1M, Binance perp (4.4 bps)."
 */
export function formatSnapshotSummary(
  pairs: readonly SizeQuotePair[],
  options: SnapshotSummaryOptions,
): string {
  const picks = bestVenuePerTier(pairs, options).filter((p) => !p.empty);
  if (picks.length === 0) {
    return "";
  }

  const asset = options.asset;
  const side = options.side ?? "buy";
  const metric = options.metric ?? "total_cost_bps";
  const labelOf = (pick: BestVenuePick) =>
    options.venueLabels?.[pick.rowKey] ??
    options.venueLabels?.[pick.venue] ??
    pick.venue;

  const metricPhrase =
    metric === "spread_bps" ? "lowest spread" : "lowest total cost";
  const sidePhrase =
    side === "round_trip"
      ? "round-trip"
      : side === "sell"
        ? "sell"
        : "buy";

  const formAware = pairsHaveForms(pairs);

  if (!formAware) {
    const clauses = picks.map((pick, i) => {
      const notional = formatNotional(pick.notionalUsd);
      const venue = labelOf(pick);
      const bps = pick.valueBps.toFixed(1);
      if (i === 0) {
        return `At ${notional}, ${venue} has the ${metricPhrase} to ${sidePhrase} ${asset} (${bps} bps)`;
      }
      return `at ${notional}, ${venue} (${bps} bps)`;
    });
    if (clauses.length === 1) {
      return `${clauses[0]}.`;
    }
    return `${clauses.join("; ")}.`;
  }

  // Form-aware: group picks by notional, phrase form_class winners together.
  const byNotional = new Map<string, BestVenuePick[]>();
  for (const pick of picks) {
    const list = byNotional.get(pick.notionalUsd) ?? [];
    list.push(pick);
    byNotional.set(pick.notionalUsd, list);
  }
  const notionals = sortNotionals([...byNotional.keys()]);
  const clauses: string[] = [];

  for (let i = 0; i < notionals.length; i++) {
    const n = notionals[i]!;
    const tierPicks = byNotional.get(n) ?? [];
    const notional = formatNotional(n);
    const parts = tierPicks.map((pick) => {
      const venue = labelOf(pick);
      const bps = pick.valueBps.toFixed(1);
      const classLabel =
        pick.formClass === "perp"
          ? "perp"
          : pick.formClass === "tokenized"
            ? "tokenized"
            : "path";
      return `${venue} among ${classLabel} (${bps} bps)`;
    });
    if (i === 0) {
      clauses.push(
        `At ${notional}, ${metricPhrase} to ${sidePhrase} ${asset}: ${parts.join("; ")}`,
      );
    } else {
      clauses.push(`at ${notional}: ${parts.join("; ")}`);
    }
  }

  if (clauses.length === 1) {
    return `${clauses[0]}.`;
  }
  return `${clauses.join("; ")}.`;
}
