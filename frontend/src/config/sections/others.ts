import { NOTIONAL_TIERS_USD } from "@/config/notionals";
import type {
  SectionConfig,
  VenueClass,
  VenueMeta,
} from "@/config/sections/types";

/**
 * Others section (WHI-811).
 *
 * High-volume CEX + perp-DEX board only — prop AMMs are deliberately absent
 * (WHI-798 §5 / §7.3). Asset tiers live here so quarterly re-scans only touch
 * config, not component code.
 */

/** Five-venue intersection: CEX + three perp DEXes. Never include prop AMM. */
export const OTHER_VENUES = [
  "binance",
  "bybit",
  "hyperliquid",
  "lighter",
  "apex",
] as const;

/** P0 — full CEX + three perp DEX coverage (WHI-798 §5.5 / §7.3). */
export const OTHER_P0_ASSETS = [
  "DOGE",
  "WIF",
  "XRP",
  "SUI",
  "LINK",
  "AVAX",
  "ADA",
  "BNB",
] as const;

/**
 * P1 — scaled memes. Backend already normalizes contract units to 1×
 * (WHI-826); UI only annotates via Quote.venue_symbol.
 */
export const OTHER_P1_SCALED_ASSETS = ["PEPE", "BONK"] as const;

export type WatchlistAsset = {
  id: string;
  /** Coverage caveat shown on the collapsed watchlist row. */
  caveat: string;
};

/**
 * P2 watchlist — default-collapsed. Still quoted only on CEX + perp DEX;
 * caveats document limited prop coverage (not requested from this page).
 */
export const OTHER_P2_WATCHLIST: readonly WatchlistAsset[] = [
  {
    id: "JUP",
    caveat: "Prop coverage = HumidiFi only (not the three-venue prop intersection)",
  },
  {
    id: "AERO",
    caveat: "Tessera-Base-only prop quotes vs CEX (WHI-798 §1.3)",
  },
  {
    id: "VIRTUAL",
    caveat: "Tessera-Base-only prop quotes vs CEX (WHI-798 §1.3)",
  },
  {
    id: "EURC",
    caveat: "Tessera-Base-only prop quotes vs CEX (WHI-798 §1.3)",
  },
] as const;

export const OTHER_VENUE_META: Readonly<Record<string, VenueMeta>> = {
  binance: {
    displayName: "Binance",
    venueClass: "cex",
    quoteCurrency: "USDT",
  },
  bybit: {
    displayName: "Bybit",
    venueClass: "cex",
    quoteCurrency: "USDT",
  },
  hyperliquid: {
    displayName: "Hyperliquid",
    venueClass: "perp_dex",
    quoteCurrency: "USDC",
  },
  lighter: {
    displayName: "Lighter",
    venueClass: "perp_dex",
    quoteCurrency: "USDC",
  },
  apex: {
    displayName: "ApeX",
    venueClass: "perp_dex",
    quoteCurrency: "USDT",
  },
};

export const ORDERBOOK_VENUE_CLASSES: ReadonlySet<VenueClass> = new Set([
  "cex",
  "perp_dex",
]);

export const OTHER_POLL_MS = 30_000;

/** Expanded (non-watchlist) assets rendered as full blocks. */
export const OTHER_EXPANDED_ASSETS: readonly string[] = [
  ...OTHER_P0_ASSETS,
  ...OTHER_P1_SCALED_ASSETS,
];

const SCALED_SET = new Set<string>(OTHER_P1_SCALED_ASSETS);

/** True for PEPE/BONK-style assets that need venue_symbol contract notes. */
export function isScaledContractAsset(asset: string): boolean {
  return SCALED_SET.has(asset.toUpperCase());
}

export const othersSection: SectionConfig = {
  id: "others",
  title: "Others",
  description:
    "High-volume CEX + perp-DEX assets (no prop AMM). Where is it cheapest to buy at your size right now?",
  // Config-driven list for the main board (P0 + P1). P2 lives in OTHER_P2_WATCHLIST.
  assets: [...OTHER_EXPANDED_ASSETS],
  venues: [...OTHER_VENUES],
  notionals: [...NOTIONAL_TIERS_USD],
  defaultSideView: "buy",
  cellMetric: "total_cost_bps",
  showTopOfBook: true,
  pollIntervalMs: OTHER_POLL_MS,
};

function defaultInstrumentType(
  venueClass: VenueClass | undefined,
): string | undefined {
  if (venueClass === "perp_dex") return "perp";
  if (venueClass === "cex") return "spot";
  return undefined;
}

/**
 * Build matrix row labels: display · instrument · quote currency.
 * Others has no on-chain wrappers — representation is the wire form only.
 */
export function buildVenueLabels(
  venues: readonly string[],
  options: {
    representationOverrides?: Readonly<Record<string, string>>;
  } = {},
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const slug of venues) {
    const meta = OTHER_VENUE_META[slug];
    const display = meta?.displayName ?? slug;
    const quote = meta?.quoteCurrency;
    const instrument = defaultInstrumentType(meta?.venueClass);
    const rep = options.representationOverrides?.[slug];

    const parts: string[] = [display];
    if (instrument) parts.push(instrument);
    if (rep) parts.push(rep);
    if (quote) parts.push(quote);
    out[slug] = parts.join(" · ");
  }
  return out;
}

/** Short summary labels: "Binance spot", "Hyperliquid perp". */
export function venueSummaryLabel(slug: string): string {
  const meta = OTHER_VENUE_META[slug];
  const name = meta?.displayName ?? slug;
  if (!meta) return name;
  if (meta.venueClass === "cex") {
    return `${name} ${defaultInstrumentType("cex") ?? "spot"}`;
  }
  if (meta.venueClass === "perp_dex") {
    return `${name} perp`;
  }
  return name;
}

export function isOrderbookVenue(slug: string): boolean {
  const cls = OTHER_VENUE_META[slug]?.venueClass;
  return cls !== undefined && ORDERBOOK_VENUE_CLASSES.has(cls);
}
