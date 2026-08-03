/**
 * Fee-structure table helpers for /fees (WHI-813).
 *
 * Groups GET /fees schedules by venue class (from GET /venues) for display.
 * Does not invent fee numbers — only arranges the validated catalog.
 */

import type { FeeSchedule, VenueResponse } from "@/lib/api";

export type VenueClass = VenueResponse["venue_class"] | "unknown";

export type FeeTableRow = {
  venue: string;
  displayName: string;
  venueClass: VenueClass;
  instrumentType: FeeSchedule["instrument_type"];
  makerBps: string | null;
  takerBps: string | null;
  lpFeeTiersBps: string[] | null;
  gasEstimateUsd: string | null;
  fundingModel: FeeSchedule["funding_model"];
  feeEmbeddedInQuote: boolean;
  sourceUrls: string[];
  updatedAt: string;
  defaultTier: string;
  tiers: FeeSchedule["tiers"];
};

export type FeeTableGroup = {
  venueClass: VenueClass;
  label: string;
  rows: FeeTableRow[];
};

const CLASS_ORDER: VenueClass[] = [
  "cex",
  "perp_dex",
  "amm_dex",
  "prop_amm",
  "unknown",
];

const CLASS_LABELS: Record<VenueClass, string> = {
  cex: "CEX",
  perp_dex: "Perp DEX",
  amm_dex: "Public AMM",
  prop_amm: "Prop AMM",
  unknown: "Other",
};

/**
 * Join fee schedules with venue metadata and group by venue class.
 *
 * Order within a group: venue slug, then instrument_type (spot before perp).
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
      venueClass: meta?.venue_class ?? "unknown",
      instrumentType: s.instrument_type,
      makerBps: s.maker_bps ?? null,
      takerBps: s.taker_bps ?? null,
      lpFeeTiersBps: s.lp_fee_tiers_bps ?? null,
      gasEstimateUsd: s.gas_estimate_usd ?? null,
      fundingModel: s.funding_model,
      feeEmbeddedInQuote: Boolean(s.fee_embedded_in_quote),
      sourceUrls: s.source_urls ?? [],
      updatedAt: s.updated_at,
      defaultTier: s.default_tier,
      tiers: s.tiers ?? null,
    };
  });

  rows.sort((a, b) => {
    const ca = CLASS_ORDER.indexOf(a.venueClass);
    const cb = CLASS_ORDER.indexOf(b.venueClass);
    if (ca !== cb) return ca - cb;
    if (a.venue !== b.venue) return a.venue.localeCompare(b.venue);
    return instrumentRank(a.instrumentType) - instrumentRank(b.instrumentType);
  });

  const byClass = new Map<VenueClass, FeeTableRow[]>();
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

function instrumentRank(t: FeeSchedule["instrument_type"]): number {
  switch (t) {
    case "spot":
      return 0;
    case "perp":
      return 1;
    case "amm_pool":
      return 2;
    case "prop_amm":
      return 3;
    default:
      return 9;
  }
}

export function fundingModelLabel(
  model: FeeSchedule["funding_model"],
): string {
  switch (model) {
    case "none":
      return "—";
    case "perp_8h":
      return "8h funding";
    case "perp_continuous":
      return "continuous funding";
    default:
      return String(model);
  }
}

export function instrumentTypeLabel(
  t: FeeSchedule["instrument_type"],
): string {
  switch (t) {
    case "spot":
      return "spot";
    case "perp":
      return "perp";
    case "amm_pool":
      return "AMM pool";
    case "prop_amm":
      return "prop AMM";
    default:
      return String(t);
  }
}
