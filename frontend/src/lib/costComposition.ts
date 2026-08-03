/**
 * Cost-composition view for /fees (WHI-813).
 *
 * Bar segments are *display decompositions* of backend fields (spread_bps +
 * fee_breakdown.*). Ranking never recomputes total_cost_bps — it uses the
 * quote's value and the shared isEligibleForBest gate (WHI-799 §5.2 /
 * costs.py remains the sole formula owner).
 *
 * trading_component is 0 when fee_breakdown.embedded_in_price (same rule as
 * §5.2); gas_unknown leaves gas as null so UI never treats unknown gas as 0.
 */

import type { Quote, SizeQuotePair } from "@/lib/api";
import { compareVenueSlug } from "@/lib/feesTable";
import { formatBps, formatNotional, parseDecimal } from "@/lib/format";
import { isEligibleForBest } from "@/lib/status";

export type CostSegmentId =
  | "spread_bps"
  | "trading_component_bps"
  | "platform_fee_bps"
  | "gas_bps";

export type CostSegment = {
  id: CostSegmentId;
  /**
   * Segment contribution in bps.
   * - number: known (may be negative — better than mid; do not clamp)
   * - null: unknown (gas_unknown); never treat as 0 for ranking or scale
   */
  bps: number | null;
};

export type CostComposition = {
  venue: string;
  /** True when trading fee is inside the quoted price (prop/AMM). */
  feeEmbeddedInPrice: boolean;
  /** Segments that sum to total when every segment is known. */
  segments: CostSegment[];
  /**
   * Sum of known segment bps when cost is complete; null when any segment is
   * unknown or status is not ok. Used only to assert the §5.2 identity in
   * tests — ranking always reads totalCostBps from the quote.
   */
  segmentsSumBps: number | null;
  /** Quote total_cost_bps (backend SSOT). */
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

/** Stable segment order for stacked bars / legend. */
export const COST_SEGMENT_ORDER: readonly CostSegmentId[] = [
  "spread_bps",
  "trading_component_bps",
  "platform_fee_bps",
  "gas_bps",
] as const;

/**
 * Derive stacked-bar segments from one quote.
 *
 * Reads API fields only. Does not recompute total_cost_bps for ranking.
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

  // Preserve nulls: missing spread is not "0 bps cheaper than mid".
  const spread = parseDecimal(quote.spread_bps);
  // §5.2 display rule: embedded ⇒ trading component is 0 (fee lives in spread).
  const tradingFee = parseDecimal(fb?.trading_fee_bps);
  const tradingComponent = embedded ? 0 : tradingFee;
  const platform = parseDecimal(fb?.platform_fee_bps) ?? 0;
  // gas_unknown ⇒ null (never 0). costs.py leaves gas_bps null in that case.
  const gas = gasUnknown ? null : parseDecimal(fb?.gas_bps);

  const segments: CostSegment[] = [
    { id: "spread_bps", bps: spread },
    {
      id: "trading_component_bps",
      bps: tradingComponent,
    },
    { id: "platform_fee_bps", bps: platform },
    { id: "gas_bps", bps: gas },
  ];

  const totalCostBps = parseDecimal(quote.total_cost_bps);
  const allKnown = segments.every((s) => s.bps !== null);
  const segmentsSumBps =
    quote.status === "ok" && !gasUnknown && totalCostBps !== null && allKnown
      ? round4(
          (spread as number) +
            (tradingComponent as number) +
            platform +
            (gas as number),
        )
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
 * Tie-break matches summary.ts: ascending total, then venue slug (`<`).
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
    // Match summary.ts stable slug tiebreak (lexicographic `<`).
    return compareVenueSlug(a.venue, b.venue);
  });

  incomplete.sort((a, b) => compareVenueSlug(a.venue, b.venue));
  other.sort((a, b) => compareVenueSlug(a.venue, b.venue));

  return { ranked, incomplete, other };
}

export type FeesConclusionOptions = {
  asset: string;
  notionalUsd: string | number;
  side?: "buy" | "sell";
  /**
   * Optional label overrides. Prefer labels already on each `CostBarRow.label`
   * when calling with pre-ranked rows.
   */
  venueLabels?: Readonly<Record<string, string>>;
};

/**
 * Rule-generated conclusion line from already-ranked cost rows.
 *
 * Takes the same `ranked` list the bars render so the sentence cannot diverge
 * from the visual order (no second ranking pass).
 *
 * Example:
 *   "For a $10k BTC buy right now, total cost is lowest on HumidiFi (2.1 bps);
 *    the cheapest explicit-fee venue is Binance (14.4 bps)."
 *
 * Returns empty string when nothing is rankable.
 */
export function formatFeesConclusion(
  ranked: readonly CostBarRow[],
  options: FeesConclusionOptions,
): string {
  if (ranked.length === 0) {
    return "";
  }

  const side = options.side ?? "buy";
  const labelOf = (row: CostBarRow) =>
    options.venueLabels?.[row.venue] ?? row.label ?? row.venue;
  const notional = formatNotional(options.notionalUsd);
  const sideWord = side === "sell" ? "sell" : "buy";
  const best = ranked[0]!;
  const bestBps = formatBps(best.totalCostBps);
  const bestLabel = labelOf(best);

  // Explicit-fee = trading fee not embedded in price (CEX / perp style).
  const explicitBest = ranked.find((r) => !r.feeEmbeddedInPrice);

  let sentence = `For a ${notional} ${options.asset} ${sideWord} right now, total cost is lowest on ${bestLabel} (${bestBps} bps)`;

  if (explicitBest) {
    if (explicitBest.venue === best.venue) {
      sentence += `; it is also the cheapest explicit-fee venue`;
    } else {
      const eLabel = labelOf(explicitBest);
      const eBps = formatBps(explicitBest.totalCostBps);
      sentence += `; the cheapest explicit-fee venue is ${eLabel} (${eBps} bps)`;
    }
  }

  return `${sentence}.`;
}

function emptySegments(): CostSegment[] {
  return COST_SEGMENT_ORDER.map((id) => ({ id, bps: null }));
}

function round4(n: number): number {
  return Math.round(n * 10_000) / 10_000;
}
