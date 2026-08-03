/**
 * Cost-composition view for /fees (WHI-813).
 *
 * Segments follow WHI-799 §5.2:
 *   total_cost_bps = spread_bps + trading_component + platform_fee_bps + gas_bps
 * where trading_component is 0 when fee is embedded in price.
 *
 * Ranking uses the same eligibility as summary.ts / status.ts:
 *   status=ok AND total_cost_bps != null (gas_unknown never ranks best).
 */

import type { Quote, SizeQuotePair } from "@/lib/api";
import { formatBps, formatNotional, parseDecimal } from "@/lib/format";
import { isEligibleForBest } from "@/lib/status";

export type CostSegmentId =
  | "spread_bps"
  | "trading_component_bps"
  | "platform_fee_bps"
  | "gas_bps";

export type CostSegment = {
  id: CostSegmentId;
  /** Segment contribution in bps (may be 0). */
  bps: number;
};

export type CostComposition = {
  venue: string;
  /** True when trading fee is inside the quoted price (prop/AMM). */
  feeEmbeddedInPrice: boolean;
  /** Segments that sum to total when total is complete. */
  segments: CostSegment[];
  /** Sum of segment bps; null when total_cost is incomplete. */
  segmentsSumBps: number | null;
  /** Quote total_cost_bps when present. */
  totalCostBps: number | null;
  /** gas_unknown on the quote fee breakdown. */
  gasUnknown: boolean;
  /** status=ok with non-null total (eligible to rank). */
  rankable: boolean;
  quoteStatus: Quote["status"] | "missing";
};

export type CostBarRow = CostComposition & {
  /** Display label for the venue (caller-supplied map). */
  label: string;
};

export type RankedCostBars = {
  /** Rankable rows, ascending total_cost_bps. */
  ranked: CostBarRow[];
  /** status=ok but gas_unknown / null total — never ranked best. */
  incomplete: CostBarRow[];
  /** Non-ok or missing quote. */
  other: CostBarRow[];
};

const SEGMENT_ORDER: CostSegmentId[] = [
  "spread_bps",
  "trading_component_bps",
  "platform_fee_bps",
  "gas_bps",
];

/**
 * Derive stacked-bar segments from one quote (WHI-799 §5.2).
 *
 * Does not recompute total from segments for ranking — uses quote.total_cost_bps
 * as SSOT. segmentsSumBps is exposed so tests can assert the §5.2 identity.
 */
export function costCompositionFromQuote(
  quote: Quote | null | undefined,
  venue?: string,
): CostComposition {
  if (!quote) {
    return {
      venue: venue ?? "",
      feeEmbeddedInPrice: false,
      segments: emptySegments(),
      segmentsSumBps: null,
      totalCostBps: null,
      gasUnknown: false,
      rankable: false,
      quoteStatus: "missing",
    };
  }

  const fb = quote.fee_breakdown;
  const embedded = Boolean(fb?.embedded_in_price);
  const gasUnknown = Boolean(fb?.gas_unknown);

  const spread = parseDecimal(quote.spread_bps) ?? 0;
  const tradingFee = parseDecimal(fb?.trading_fee_bps);
  const tradingComponent = embedded ? 0 : (tradingFee ?? 0);
  const platform = parseDecimal(fb?.platform_fee_bps) ?? 0;
  const gas = gasUnknown ? 0 : (parseDecimal(fb?.gas_bps) ?? 0);

  const segments: CostSegment[] = [
    { id: "spread_bps", bps: spread },
    { id: "trading_component_bps", bps: tradingComponent },
    { id: "platform_fee_bps", bps: platform },
    { id: "gas_bps", bps: gas },
  ];

  const totalCostBps = parseDecimal(quote.total_cost_bps);
  // When cost is complete, segments must sum to total (identity for the bar).
  // When gas_unknown, gas is omitted from the total — sum is still useful for
  // display of known pieces but segmentsSumBps stays null so we never pretend
  // the bar equals total_cost.
  const segmentsSumBps =
    quote.status === "ok" && !gasUnknown && totalCostBps !== null
      ? round4(spread + tradingComponent + platform + gas)
      : null;

  return {
    venue: quote.venue || venue || "",
    feeEmbeddedInPrice: embedded,
    segments,
    segmentsSumBps,
    totalCostBps,
    gasUnknown,
    rankable: isEligibleForBest(quote),
    quoteStatus: quote.status,
  };
}

/**
 * Build ranked / incomplete / other groups for the cost-composition view.
 *
 * Only buy (default) or sell legs are used — round-trip is out of scope for
 * the fees page stacked bars (issue: single-side trade cost).
 */
export function rankCostComposition(
  pairs: readonly SizeQuotePair[],
  options: {
    side?: "buy" | "sell";
    venueLabels?: Readonly<Record<string, string>>;
    /** Optional allow-list; empty/undefined = all pairs. */
    venues?: readonly string[];
  } = {},
): RankedCostBars {
  const side = options.side ?? "buy";
  const allow = options.venues ? new Set(options.venues) : null;
  const labelOf = (slug: string) => options.venueLabels?.[slug] ?? slug;

  const ranked: CostBarRow[] = [];
  const incomplete: CostBarRow[] = [];
  const other: CostBarRow[] = [];

  for (const pair of pairs) {
    if (allow && !allow.has(pair.venue)) continue;
    const quote = side === "buy" ? pair.buy : pair.sell;
    const composition = costCompositionFromQuote(quote, pair.venue);
    const row: CostBarRow = {
      ...composition,
      venue: composition.venue || pair.venue,
      label: labelOf(composition.venue || pair.venue),
    };

    if (row.rankable) {
      ranked.push(row);
    } else if (
      row.quoteStatus === "ok" &&
      (row.gasUnknown || row.totalCostBps === null)
    ) {
      incomplete.push(row);
    } else {
      other.push(row);
    }
  }

  ranked.sort((a, b) => {
    const ta = a.totalCostBps ?? Number.POSITIVE_INFINITY;
    const tb = b.totalCostBps ?? Number.POSITIVE_INFINITY;
    if (ta !== tb) return ta - tb;
    return a.venue.localeCompare(b.venue);
  });

  // Stable incomplete / other by venue slug for deterministic UI.
  incomplete.sort((a, b) => a.venue.localeCompare(b.venue));
  other.sort((a, b) => a.venue.localeCompare(b.venue));

  return { ranked, incomplete, other };
}

export type FeesConclusionOptions = {
  asset: string;
  notionalUsd: string | number;
  side?: "buy" | "sell";
  venueLabels?: Readonly<Record<string, string>>;
};

/**
 * Rule-generated conclusion line for the cost view.
 *
 * Example:
 *   "For a $10k BTC buy right now, total cost is lowest on HumidiFi (2.1 bps);
 *    the cheapest explicit-fee venue is Binance (14.4 bps)."
 *
 * Returns empty string when nothing is rankable.
 */
export function formatFeesConclusion(
  pairs: readonly SizeQuotePair[],
  options: FeesConclusionOptions,
): string {
  const side = options.side ?? "buy";
  const { ranked } = rankCostComposition(pairs, {
    side,
    venueLabels: options.venueLabels,
  });
  if (ranked.length === 0) {
    return "";
  }

  const labelOf = (slug: string) => options.venueLabels?.[slug] ?? slug;
  const notional = formatNotional(options.notionalUsd);
  const sideWord = side === "sell" ? "sell" : "buy";
  const best = ranked[0]!;
  const bestBps = formatBps(best.totalCostBps);
  const bestLabel = labelOf(best.venue);

  // Explicit-fee = trading fee not embedded in price (CEX / perp style).
  const explicitBest = ranked.find((r) => !r.feeEmbeddedInPrice);

  let sentence = `For a ${notional} ${options.asset} ${sideWord} right now, total cost is lowest on ${bestLabel} (${bestBps} bps)`;

  if (explicitBest) {
    if (explicitBest.venue === best.venue) {
      sentence += `; it is also the cheapest explicit-fee venue`;
    } else {
      const eLabel = labelOf(explicitBest.venue);
      const eBps = formatBps(explicitBest.totalCostBps);
      sentence += `; the cheapest explicit-fee venue is ${eLabel} (${eBps} bps)`;
    }
  }

  return `${sentence}.`;
}

/** Segment display order for stacked bars (stable legend). */
export function costSegmentOrder(): readonly CostSegmentId[] {
  return SEGMENT_ORDER;
}

function emptySegments(): CostSegment[] {
  return SEGMENT_ORDER.map((id) => ({ id, bps: 0 }));
}

function round4(n: number): number {
  return Math.round(n * 10_000) / 10_000;
}
