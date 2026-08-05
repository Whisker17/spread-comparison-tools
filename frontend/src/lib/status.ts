/**
 * Single source of truth for quote status rendering (WHI-808 / WHI-799 §5.2 / §6.2).
 *
 * Status values on Quote.status:
 *   ok | no_quote | insufficient_liquidity | unsupported_asset | error |
 *   rate_limited | excessive_impact
 *
 * Orthogonal flags (not status enum values):
 *   fee_breakdown.gas_unknown → "cost incomplete"; excluded from best-venue ranking
 *   mid_stale → warning icon with mid timestamp
 *   quote_stale → aged past max_quote_age_for_best_sec (WHI-846); shown, never best
 */

import type { components } from "@/lib/api-types";
import type { RankMetric } from "@/lib/summary";

export type Quote = components["schemas"]["Quote"];
export type QuoteStatus = Quote["status"];
/** Alias kept for StatusCell props; same as RankMetric. */
export type MetricKey = RankMetric;

/** Backend PRICED_QUOTE_STATUSES mirror — keep numbers visible (WHI-845). */
const PRICED_STATUSES: ReadonlySet<string> = new Set(["ok", "excessive_impact"]);

export function isPricedStatus(
  status: string | null | undefined,
): boolean {
  return status != null && PRICED_STATUSES.has(status);
}

/** How a cell should render given status + orthogonal flags. */
export type CellRenderKind =
  | "value" // status=ok with a numeric metric
  | "dash" // no_quote / unsupported_asset
  | "insufficient_liquidity"
  | "error"
  | "rate_limited" // WHI-844: distinguishable from timeout/error
  | "excessive_impact" // WHI-845: number still shown, never best / heat
  | "cost_incomplete"; // gas_unknown (may still show spread_bps)

/** Badge color variant owned by the status SSOT (StatusCell must not re-derive). */
export type StatusBadgeVariant = "warning" | "danger" | "muted";

export type CellRenderDecision = {
  kind: CellRenderKind;
  /** Primary label (bps string or status text). */
  label: string;
  /** Secondary badge / aria description. */
  badge?: string;
  /** Badge color when `badge` is set. */
  badgeVariant?: StatusBadgeVariant;
  /** Retry / action hint for error cells. */
  hint?: string;
  /** mid_stale warning (independent of status). */
  midStale: boolean;
  midTimestamp?: string;
  /** quote_stale: observation aged past best-eligibility window (WHI-846). */
  quoteStale: boolean;
  /** Age in seconds when the API stamped it (store-backed rows). */
  ageSec?: number | null;
  /** Eligible for best-venue highlighting (WHI-799 §5.2). */
  eligibleForBest: boolean;
  /** True when the primary label is a numeric metric (value / cost_incomplete / excessive_impact). */
  showsMetric: boolean;
};

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
      quoteStale: false,
      eligibleForBest: false,
      showsMetric: false,
    };
  }

  const midStale = Boolean(quote.mid_stale);
  const quoteStale = Boolean(quote.quote_stale);
  const midTimestamp = quote.mid_timestamp;
  const ageSec = quote.age_sec;
  const gasUnknown = Boolean(quote.fee_breakdown?.gas_unknown);

  switch (quote.status) {
    case "no_quote":
    case "unsupported_asset":
      return {
        kind: "dash",
        label: "—",
        midStale,
        midTimestamp,
        quoteStale,
        ageSec,
        eligibleForBest: false,
        showsMetric: false,
      };
    case "insufficient_liquidity":
      return {
        kind: "insufficient_liquidity",
        label: "illiquid",
        badge: "insufficient liquidity",
        badgeVariant: "warning",
        midStale,
        midTimestamp,
        quoteStale,
        ageSec,
        eligibleForBest: false,
        showsMetric: false,
      };
    case "error": {
      // WHI-864: unsampled poller tiers are structural (not a transient
      // failure) — mute badge, no retry hint.
      if (
        quote.error_code === "not_yet_sampled" ||
        quote.error_code === "not_initialized"
      ) {
        return {
          kind: "dash",
          label: "—",
          badge:
            quote.error_code === "not_yet_sampled"
              ? "not sampled"
              : "unavailable",
          badgeVariant: "muted",
          midStale,
          midTimestamp,
          quoteStale,
          ageSec,
          eligibleForBest: false,
          showsMetric: false,
        };
      }
      return {
        kind: "error",
        label: "error",
        badge: quote.error_code ?? "error",
        badgeVariant: "danger",
        hint: "Retry refresh",
        midStale,
        midTimestamp,
        quoteStale,
        ageSec,
        eligibleForBest: false,
        showsMetric: false,
      };
    }
    case "rate_limited":
      return {
        kind: "rate_limited",
        label: "RATE LIMITED",
        badge: "RATE LIMITED",
        badgeVariant: "warning",
        hint: "Retry later",
        midStale,
        midTimestamp,
        quoteStale,
        ageSec,
        eligibleForBest: false,
        showsMetric: false,
      };
    case "excessive_impact":
      // Keep the magnitude legible (WHI-845); exclude from best / heat via
      // eligibleForBest=false and includeInHeat requiring status=ok.
      return {
        kind: "excessive_impact",
        label: options.formattedMetric ?? "—",
        badge: "excessive impact",
        badgeVariant: "warning",
        midStale,
        midTimestamp,
        quoteStale,
        ageSec,
        eligibleForBest: false,
        showsMetric: true,
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
            badgeVariant: "muted",
            midStale,
            midTimestamp,
            quoteStale,
            ageSec,
            eligibleForBest: false,
            showsMetric: true,
          };
        }
      }
      // Stale ok rows keep the number but badge "stale" (WHI-846).
      if (quoteStale) {
        return {
          kind: "value",
          label: options.formattedMetric ?? "—",
          badge: "stale",
          badgeVariant: "muted",
          midStale,
          midTimestamp,
          quoteStale: true,
          ageSec,
          eligibleForBest: false,
          showsMetric: true,
        };
      }
      return {
        kind: "value",
        label: options.formattedMetric ?? "—",
        midStale,
        midTimestamp,
        quoteStale: false,
        ageSec,
        eligibleForBest: isEligibleForBest(quote),
        showsMetric: true,
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
        quoteStale,
        ageSec,
        eligibleForBest: false,
        showsMetric: false,
      };
    }
  }
}

/**
 * WHI-799 §5.2: only status=ok AND total_cost_bps is not null participate in
 * "best venue" ranking. gas_unknown forces total_cost_bps null.
 * ``excessive_impact`` is never eligible (WHI-845).
 * ``quote_stale`` is never eligible (WHI-846 age gate).
 */
export function isEligibleForBest(quote: Quote | null | undefined): boolean {
  if (!quote) return false;
  if (quote.status !== "ok") return false;
  if (quote.quote_stale) return false;
  if (quote.fee_breakdown?.gas_unknown) return false;
  if (quote.total_cost_bps === null || quote.total_cost_bps === undefined) {
    return false;
  }
  return true;
}

/**
 * Whether a quote's metric may enter the per-column heat range (WHI-838 / WHI-845).
 * Only comparable ``ok`` quotes — never ``excessive_impact``.
 */
export function includeQuoteInHeat(
  quote: Quote | null | undefined,
  metric: MetricKey = "total_cost_bps",
): boolean {
  if (!quote || quote.status !== "ok") return false;
  if (metric === "total_cost_bps") return isEligibleForBest(quote);
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
    id: "rate_limited",
    title: "rate_limited",
    description:
      'Venue rate limit would exceed remaining quote budget (WHI-844) — "RATE LIMITED", distinct from timeout. Never best-venue eligible.',
    exampleKind: "rate_limited",
  },
  {
    id: "excessive_impact",
    title: "excessive_impact",
    description:
      "Price impact over config threshold (WHI-845) — bps number stays visible with badge; never best-venue eligible and excluded from heat range.",
    exampleKind: "excessive_impact",
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
