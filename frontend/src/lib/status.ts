/**
 * Single source of truth for quote status rendering (WHI-808 / WHI-799 §5.2 / §6.2).
 *
 * Status values on Quote.status:
 *   ok | no_quote | insufficient_liquidity | unsupported_asset | error
 *
 * Orthogonal flags (not status enum values):
 *   fee_breakdown.gas_unknown → "cost incomplete"; excluded from best-venue ranking
 *   mid_stale → warning icon with mid timestamp
 */

import type { components } from "@/lib/api-types";

export type Quote = components["schemas"]["Quote"];
export type QuoteStatus = Quote["status"];

/** How a cell should render given status + orthogonal flags. */
export type CellRenderKind =
  | "value" // status=ok with a numeric metric
  | "dash" // no_quote / unsupported_asset
  | "insufficient_liquidity"
  | "error"
  | "cost_incomplete"; // gas_unknown (may still show spread_bps)

export type CellRenderDecision = {
  kind: CellRenderKind;
  /** Primary label (bps string or status text). */
  label: string;
  /** Secondary badge / aria description. */
  badge?: string;
  /** Retry / action hint for error cells. */
  hint?: string;
  /** mid_stale warning (independent of status). */
  midStale: boolean;
  midTimestamp?: string;
  /** Eligible for best-venue highlighting (WHI-799 §5.2). */
  eligibleForBest: boolean;
};

export type MetricKey = "total_cost_bps" | "spread_bps";

/**
 * Decide how to render one quote cell.
 * `displayValue` is the already-formatted metric (2 dp) when kind === "value" or
 * "cost_incomplete" (spread may still show).
 */
export function decideCellRender(
  quote: Quote | null | undefined,
  options: {
    /** Formatted metric for ok cells (caller chooses spread vs total_cost). */
    formattedMetric?: string | null;
    metricKey?: MetricKey;
  } = {},
): CellRenderDecision {
  if (!quote) {
    return {
      kind: "dash",
      label: "—",
      midStale: false,
      eligibleForBest: false,
    };
  }

  const midStale = Boolean(quote.mid_stale);
  const midTimestamp = quote.mid_timestamp;
  const gasUnknown = Boolean(quote.fee_breakdown?.gas_unknown);

  switch (quote.status) {
    case "no_quote":
    case "unsupported_asset":
      return {
        kind: "dash",
        label: "—",
        midStale,
        midTimestamp,
        eligibleForBest: false,
      };
    case "insufficient_liquidity":
      return {
        kind: "insufficient_liquidity",
        label: "illiquid",
        badge: "insufficient liquidity",
        midStale,
        midTimestamp,
        eligibleForBest: false,
      };
    case "error":
      return {
        kind: "error",
        label: "error",
        badge: quote.error_code ?? "error",
        hint: "Retry refresh",
        midStale,
        midTimestamp,
        eligibleForBest: false,
      };
    case "ok": {
      const metricKey = options.metricKey ?? "total_cost_bps";
      // gas_unknown / null total only make *cost* incomplete (WHI-799 §5.2).
      // When displaying spread_bps the number is still complete.
      if (metricKey === "total_cost_bps") {
        const totalNull =
          quote.total_cost_bps === null || quote.total_cost_bps === undefined;
        if (gasUnknown || totalNull) {
          return {
            kind: "cost_incomplete",
            label: options.formattedMetric ?? "—",
            badge: "cost incomplete",
            midStale,
            midTimestamp,
            eligibleForBest: false,
          };
        }
      }
      return {
        kind: "value",
        label: options.formattedMetric ?? "—",
        midStale,
        midTimestamp,
        eligibleForBest: isEligibleForBest(quote),
      };
    }
    default: {
      const _exhaustive: never = quote.status;
      return {
        kind: "error",
        label: String(_exhaustive),
        badge: "unknown status",
        midStale,
        midTimestamp,
        eligibleForBest: false,
      };
    }
  }
}

/**
 * WHI-799 §5.2: only status=ok AND total_cost_bps is not null participate in
 * "best venue" ranking. gas_unknown forces total_cost_bps null.
 */
export function isEligibleForBest(quote: Quote | null | undefined): boolean {
  if (!quote) return false;
  if (quote.status !== "ok") return false;
  if (quote.fee_breakdown?.gas_unknown) return false;
  if (quote.total_cost_bps === null || quote.total_cost_bps === undefined) {
    return false;
  }
  return true;
}

/** Human-readable status legend entries for the fixtures / docs page. */
export const STATUS_LEGEND: ReadonlyArray<{
  id: string;
  title: string;
  description: string;
  exampleKind: CellRenderKind | "mid_stale";
}> = [
  {
    id: "ok",
    title: "ok",
    description: "Numeric bps cell (2 decimal places). Eligible for best-venue highlight when total_cost_bps is present.",
    exampleKind: "value",
  },
  {
    id: "no_quote",
    title: "no_quote",
    description: 'No market / no route — render as "—".',
    exampleKind: "dash",
  },
  {
    id: "unsupported_asset",
    title: "unsupported_asset",
    description: 'Asset not listed on venue — render as "—".',
    exampleKind: "dash",
  },
  {
    id: "insufficient_liquidity",
    title: "insufficient_liquidity",
    description: "Depth below target size — badge \"insufficient liquidity\".",
    exampleKind: "insufficient_liquidity",
  },
  {
    id: "error",
    title: "error",
    description: "Adapter/transport failure — badge with retry hint.",
    exampleKind: "error",
  },
  {
    id: "gas_unknown",
    title: "gas_unknown",
    description:
      'Cost incomplete group (badge). Excluded from best-venue highlighting (WHI-799 §5.2).',
    exampleKind: "cost_incomplete",
  },
  {
    id: "mid_stale",
    title: "mid_stale",
    description:
      "Orthogonal to status: warning icon + mid timestamp; does not change bps.",
    exampleKind: "mid_stale",
  },
] as const;
