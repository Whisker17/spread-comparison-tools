/**
 * Fee-structure table helpers for /fees (WHI-813).
 *
 * Groups GET /fees schedules by venue class (from GET /venues) for display.
 * Does not invent fee numbers — only arranges the validated catalog.
 */

import { VENUE_CLASS_LABELS } from "@/config/sections/helpers";
import type { VenueClass } from "@/config/sections/types";
import type { FeeSchedule, VenueResponse } from "@/lib/api";
import { compareSlug } from "@/lib/format";

export type FeeTableVenueClass = VenueClass | "unknown";

export type FeeTableRow = {
  venue: string;
  displayName: string;
  venueClass: FeeTableVenueClass;
  instrumentType: FeeSchedule["instrument_type"];
  makerBps: string | null;
  takerBps: string | null;
  lpFeeTiersBps: string[] | null;
  gasEstimateUsd: string | null;
  fundingModel: FeeSchedule["funding_model"];
  feeEmbeddedInQuote: boolean;
  sourceUrls: string[];
  updatedAt: string;
};

export type FeeTableGroup = {
  venueClass: FeeTableVenueClass;
  label: string;
  rows: FeeTableRow[];
};

/** Emit order; every FeeTableVenueClass must appear so rows are never dropped. */
const CLASS_ORDER: readonly FeeTableVenueClass[] = [
  "cex",
  "perp_dex",
  "amm_dex",
  "prop_amm",
  "mock",
  "unknown",
] as const;

const CLASS_LABELS: Record<FeeTableVenueClass, string> = {
  ...VENUE_CLASS_LABELS,
};

const KNOWN_CLASSES = new Set<string>(CLASS_ORDER);

const INSTRUMENT_RANK: Record<FeeSchedule["instrument_type"], number> = {
  spot: 0,
  perp: 1,
  amm_pool: 2,
  prop_amm: 3,
};

const INSTRUMENT_LABEL: Record<FeeSchedule["instrument_type"], string> = {
  spot: "spot",
  perp: "perp",
  amm_pool: "AMM pool",
  prop_amm: "prop AMM",
};

const FUNDING_LABEL: Record<FeeSchedule["funding_model"], string> = {
  none: "—",
  perp_8h: "8h funding",
  perp_continuous: "continuous funding",
};

function normalizeVenueClass(
  raw: string | undefined | null,
): FeeTableVenueClass {
  if (raw && KNOWN_CLASSES.has(raw)) {
    return raw as FeeTableVenueClass;
  }
  return "unknown";
}

/**
 * Join fee schedules with venue metadata and group by venue class.
 *
 * Unmapped or missing classes become `"unknown"` so no schedule is dropped
 * (acceptance: fee table renders all venues).
 */
export function buildFeeTableGroups(
  schedules: readonly FeeSchedule[],
  venues: readonly VenueResponse[],
): FeeTableGroup[] {
  const metaBySlug = new Map(venues.map((v) => [v.slug, v]));

  const rows: FeeTableRow[] = schedules.map((s) => {
    const meta = metaBySlug.get(s.venue);
    return {
      venue: s.venue,
      displayName: meta?.display_name ?? s.venue,
      venueClass: normalizeVenueClass(meta?.venue_class),
      instrumentType: s.instrument_type,
      makerBps: s.maker_bps ?? null,
      takerBps: s.taker_bps ?? null,
      lpFeeTiersBps: s.lp_fee_tiers_bps ?? null,
      gasEstimateUsd: s.gas_estimate_usd ?? null,
      fundingModel: s.funding_model,
      feeEmbeddedInQuote: Boolean(s.fee_embedded_in_quote),
      sourceUrls: s.source_urls ?? [],
      updatedAt: s.updated_at,
    };
  });

  rows.sort((a, b) => {
    const ca = CLASS_ORDER.indexOf(a.venueClass);
    const cb = CLASS_ORDER.indexOf(b.venueClass);
    if (ca !== cb) return ca - cb;
    if (a.venue !== b.venue) return compareSlug(a.venue, b.venue);
    return (
      (INSTRUMENT_RANK[a.instrumentType] ?? 9) -
      (INSTRUMENT_RANK[b.instrumentType] ?? 9)
    );
  });

  const byClass = new Map<FeeTableVenueClass, FeeTableRow[]>();
  for (const row of rows) {
    const bucket = byClass.get(row.venueClass);
    if (bucket) {
      bucket.push(row);
    } else {
      byClass.set(row.venueClass, [row]);
    }
  }

  return CLASS_ORDER.filter((c) => byClass.has(c)).map((venueClass) => ({
    venueClass,
    label: CLASS_LABELS[venueClass],
    rows: byClass.get(venueClass) ?? [],
  }));
}

export function fundingModelLabel(
  model: FeeSchedule["funding_model"],
): string {
  return FUNDING_LABEL[model] ?? String(model);
}

export function instrumentTypeLabel(
  t: FeeSchedule["instrument_type"],
): string {
  return INSTRUMENT_LABEL[t] ?? String(t);
}

/** Map venue slug → display name from GET /venues. */
export function buildVenueLabelMap(
  venues: readonly VenueResponse[],
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const v of venues) {
    out[v.slug] = v.display_name;
  }
  return out;
}
