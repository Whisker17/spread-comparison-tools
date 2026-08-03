/**
 * Pure view helpers for the trade simulator (WHI-815).
 *
 * Ranking / best-flag ownership: the backend. This module partitions and
 * formats only — never re-derives a winner from expected_output or costs.
 */

import {
  ON_CHAIN_VENUE_CLASSES,
  VENUE_CLASS_LABELS,
  VENUE_META,
} from "@/config/sections/helpers";
import type { VenueClass } from "@/config/sections/types";
import type {
  SimulatePairErrorDetail,
  SimulateRowResponse,
  VenueResponse,
} from "@/lib/api";
import { ApiError, unwrapApiDetail } from "@/lib/api";
import { compareSlug, parseDecimal } from "@/lib/format";

export type SimulateRowPartition = {
  /** Non-not_supported rows in backend order (already expected_output desc). */
  ranked: SimulateRowResponse[];
  /** status=not_supported — collapsed "unavailable for this pair" section. */
  notSupported: SimulateRowResponse[];
};

/**
 * Split rows into the main ranked list and the collapsed unavailable section.
 *
 * Does not re-sort: POST /simulate already ranks by expected_output desc and
 * flags at most one `best=true` under WHI-799 §5.2.
 */
export function partitionSimulateRows(
  rows: readonly SimulateRowResponse[],
): SimulateRowPartition {
  const ranked: SimulateRowResponse[] = [];
  const notSupported: SimulateRowResponse[] = [];
  for (const row of rows) {
    if (row.status === "not_supported") {
      notSupported.push(row);
    } else {
      ranked.push(row);
    }
  }
  // Stable secondary order for unavailable list: slug.
  notSupported.sort((a, b) => compareSlug(a.venue, b.venue));
  return { ranked, notSupported };
}

/** The backend-flagged best row, if any. Never re-derived client-side. */
export function bestSimulateRow(
  rows: readonly SimulateRowResponse[],
): SimulateRowResponse | null {
  return rows.find((r) => r.best === true) ?? null;
}

export type DeltaVsBest = {
  /** best.expected_output − row.expected_output (null if either missing). */
  absolute: number | null;
  /**
   * Absolute delta as bps of best output:
   *   (best − row) / best × 10_000
   * Null when absolute is null or best is zero.
   */
  bps: number | null;
};

/**
 * How far this row's expected output trails the reference row.
 *
 * Prefer the backend-flagged `best` row. When none is flagged (e.g. every ok
 * row is gas_unknown / §5.2-ineligible), fall back to the first ranked row
 * with an expected_output — that is still backend order, not a client re-rank.
 * The `best` highlight is never re-derived; only the delta baseline is.
 */
export function referenceOutputRow(
  ranked: readonly SimulateRowResponse[],
  best: SimulateRowResponse | null,
): SimulateRowResponse | null {
  if (best && parseDecimal(best.expected_output) !== null) return best;
  return (
    ranked.find((r) => parseDecimal(r.expected_output) !== null) ?? null
  );
}

/**
 * How far this row's expected output trails the reference row.
 * Reference row itself returns {0, 0}. Missing outputs return nulls.
 */
export function deltaVsBest(
  row: SimulateRowResponse,
  best: SimulateRowResponse | null,
): DeltaVsBest {
  // Same row identity as the reference (by best flag or object equality).
  if (best && (row.best || row === best)) {
    return { absolute: 0, bps: 0 };
  }
  const bestOut = parseDecimal(best?.expected_output);
  const rowOut = parseDecimal(row.expected_output);
  if (bestOut === null || rowOut === null) {
    return { absolute: null, bps: null };
  }
  // Same venue+output as reference when no best flag (fallback baseline).
  if (
    best &&
    !best.best &&
    row.venue === best.venue &&
    row.instrument_type === best.instrument_type
  ) {
    return { absolute: 0, bps: 0 };
  }
  const absolute = bestOut - rowOut;
  if (bestOut === 0) {
    return { absolute, bps: null };
  }
  return { absolute, bps: (absolute / bestOut) * 10_000 };
}

export type VenueDisplayMeta = {
  displayName: string;
  venueClass: string;
  chain: string | null;
  classLabel: string;
  /** True for AMM/prop classes that show representation badges. */
  showRepresentation: boolean;
};

/**
 * Map venue chrome for simulate rows.
 *
 * Prefer section SSOT (`VENUE_META` in helpers.ts) for display name + class;
 * overlay chain from live GET /venues (helpers has no chain field).
 */
export function buildVenueMetaMap(
  venues: readonly VenueResponse[],
): Record<string, VenueDisplayMeta> {
  const out: Record<string, VenueDisplayMeta> = {};
  for (const v of venues) {
    const staticMeta = VENUE_META[v.slug];
    const venueClass = (staticMeta?.venueClass ?? v.venue_class) as VenueClass;
    out[v.slug] = {
      displayName: staticMeta?.displayName ?? v.display_name,
      venueClass,
      chain: v.chain ?? null,
      classLabel:
        VENUE_CLASS_LABELS[venueClass] ??
        VENUE_CLASS_LABELS.unknown ??
        venueClass,
      showRepresentation: ON_CHAIN_VENUE_CLASSES.has(venueClass),
    };
  }
  return out;
}

export type SimulateUserErrorKind =
  | "unknown_asset"
  | "cross_pair"
  | "validation"
  | "rate_limit"
  | "mid_unavailable"
  | "generic";

export type SimulateUserError = {
  kind: SimulateUserErrorKind;
  message: string;
};

/**
 * Map an API failure into an inline user-facing error.
 * Structured 422 pair failures use FastAPI's `{detail: {message, reason}}`.
 */
export function parseSimulateError(error: unknown): SimulateUserError {
  if (!(error instanceof ApiError)) {
    return {
      kind: "generic",
      message:
        error instanceof Error ? error.message : "Simulation failed. Try again.",
    };
  }

  if (error.status === 429) {
    return {
      kind: "rate_limit",
      message:
        "Too many simulations — wait a moment and try again (rate limited).",
    };
  }
  if (error.status === 503) {
    const { message } = unwrapApiDetail(error.body);
    const lower = (message ?? "").toLowerCase();
    if (!message || lower.includes("mid")) {
      return {
        kind: "mid_unavailable",
        message:
          message ||
          "Reference mid is unavailable right now. Retry in a few seconds.",
      };
    }
    return {
      kind: "generic",
      message,
    };
  }

  if (error.status === 422) {
    const pair = extractPairErrorDetail(error.body);
    if (pair?.reason === "unknown_asset") {
      return {
        kind: "unknown_asset",
        message:
          pair.message ||
          "Unknown asset — pick a catalogued asset and a tradeable stable.",
      };
    }
    if (pair?.reason === "cross_pair") {
      return {
        kind: "cross_pair",
        message:
          pair.message ||
          "Invalid pair — exactly one leg must be a tradeable USD stablecoin.",
      };
    }
    const { message } = unwrapApiDetail(error.body);
    return {
      kind: "validation",
      message: pair?.message || message || "Request validation failed",
    };
  }

  const { message } = unwrapApiDetail(error.body);
  return {
    kind: "generic",
    message: message || error.message,
  };
}

function extractPairErrorDetail(
  body: unknown,
): SimulatePairErrorDetail | null {
  if (typeof body !== "object" || body === null) return null;
  // FastAPI HTTPException: { detail: { message, reason } }
  if ("detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (isPairErrorDetail(detail)) return detail;
  }
  // OpenAPI documents the 422 model flat; accept either shape.
  if (isPairErrorDetail(body)) return body;
  return null;
}

function isPairErrorDetail(value: unknown): value is SimulatePairErrorDetail {
  if (typeof value !== "object" || value === null) return false;
  const v = value as { message?: unknown; reason?: unknown };
  return (
    typeof v.message === "string" &&
    (v.reason === "unknown_asset" || v.reason === "cross_pair")
  );
}

/**
 * Fee-breakdown lines for the expandable panel. Display only — never recomputes
 * total_cost_bps (backend / costs.py is SSOT).
 */
export type FeeBreakdownLine = {
  id: string;
  label: string;
  bps: string | number | null | undefined;
  /** True when the value is intentionally unknown (e.g. gas_unknown). */
  unknown?: boolean;
  note?: string;
};

export function feeBreakdownLines(
  row: SimulateRowResponse,
): FeeBreakdownLine[] {
  const fb = row.fee_breakdown;
  const lines: FeeBreakdownLine[] = [
    {
      id: "spread",
      label: "Spread",
      bps: row.spread_bps,
    },
    {
      id: "trading",
      label: "Trading fee",
      bps: fb.trading_fee_bps,
      note: fb.embedded_in_price ? "embedded in price" : undefined,
    },
    {
      id: "platform",
      label: "Platform fee",
      bps: fb.platform_fee_bps,
    },
    {
      id: "gas",
      label: "Gas",
      bps: fb.gas_unknown ? null : fb.gas_bps,
      unknown: Boolean(fb.gas_unknown),
    },
    {
      id: "total",
      label: "Total cost",
      bps: row.total_cost_bps,
      note:
        row.total_cost_bps == null && fb.gas_unknown
          ? "incomplete (gas unknown)"
          : undefined,
    },
  ];
  return lines;
}
