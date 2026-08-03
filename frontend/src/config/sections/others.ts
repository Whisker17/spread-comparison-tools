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
 * this module (not component code).
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
 * (WHI-826); UI only annotates via Quote.venue_symbol. Quotes use
 * instrument_type=perp so CEX hits 1000PEPE / 1000BONK books.
 */
export const OTHER_P1_SCALED_ASSETS = ["PEPE", "BONK"] as const;

export type WatchlistAsset = {
  id: string;
  /** Coverage caveat shown on the collapsed watchlist row. */
  caveat: string;
};

/**
 * P2 watchlist — labels + caveats only (no live /quotes). Prop-side notes
 * explain why these stay off the main CEX+perp board; Phase-1 symbol maps
 * do not cover them yet.
 */
export const OTHER_P2_WATCHLIST: readonly WatchlistAsset[] = [
  {
    id: "JUP",
    caveat:
      "Prop coverage = HumidiFi only (not the three-venue prop intersection). Not on the Phase-1 CEX+perp board.",
  },
  {
    id: "AERO",
    caveat:
      "Tessera-Base-only prop quotes vs CEX (WHI-798 §1.3). Not on the Phase-1 CEX+perp board.",
  },
  {
    id: "VIRTUAL",
    caveat:
      "Tessera-Base-only prop quotes vs CEX (WHI-798 §1.3). Not on the Phase-1 CEX+perp board.",
  },
  {
    id: "EURC",
    caveat:
      "Tessera-Base-only prop quotes vs CEX (WHI-798 §1.3). Not on the Phase-1 CEX+perp board.",
  },
] as const;

/** Grouped board content — SSOT for OthersSection rendering. */
export type OtherAssetGroup = {
  id: string;
  title: string;
  description?: string;
  assets: readonly string[];
  /** Prefer perp books (scaled memes). */
  preferPerp?: boolean;
  /** Annotate Quote.venue_symbol (scaled contracts). */
  showVenueSymbolNote?: boolean;
};

export const OTHER_ASSET_GROUPS: readonly OtherAssetGroup[] = [
  {
    id: "p0",
    title: "P0 · high-volume intersection",
    assets: OTHER_P0_ASSETS,
  },
  {
    id: "p1",
    title: "P1 · scaled memes",
    description:
      "Prices are backend-normalized to 1× units. Hover the badge for the raw venue contract symbol (Quote.venue_symbol). CEX rows use perp books so scaled 1000× contracts surface.",
    assets: OTHER_P1_SCALED_ASSETS,
    preferPerp: true,
    showVenueSymbolNote: true,
  },
];

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

const ORDERBOOK_VENUE_CLASSES: ReadonlySet<VenueClass> = new Set([
  "cex",
  "perp_dex",
]);

export const OTHER_POLL_MS = 30_000;

/** Flat expanded board (P0+P1) — also feeds section.assets SSOT. */
export function expandedOtherAssets(): string[] {
  return OTHER_ASSET_GROUPS.flatMap((g) => [...g.assets]);
}

/** Comma-separated venue filter for /quotes (and tests / footer copy). */
export function otherVenuesQueryParam(): string {
  return OTHER_VENUES.join(",");
}

/** Human venue list for page copy, derived from OTHER_VENUE_META. */
export function otherVenuesDisplayList(): string {
  return OTHER_VENUES.map((slug) => venueDisplayName(slug)).join(" · ");
}

export const othersSection: SectionConfig = {
  id: "others",
  title: "Others",
  description:
    "High-volume CEX + perp-DEX assets (no prop AMM). Where is it cheapest to buy at your size right now?",
  // SSOT for "which assets are on the main board". Groups above are the
  // rendering structure; both stay in lockstep via expandedOtherAssets().
  assets: expandedOtherAssets(),
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

export type BuildVenueLabelsOptions = {
  /**
   * Force instrument label + intent for CEX/perp rows (e.g. "perp" for scaled
   * memes). Default derives spot for CEX and perp for perp_dex.
   */
  instrument?: "spot" | "perp";
};

/**
 * Build matrix row labels for Others (CEX / perp only).
 * display · instrument · quote currency.
 * First arg mirrors blue-chips call shape (asset unused: no wrapper labels).
 */
export function buildVenueLabels(
  asset: string,
  venues: readonly string[],
  options: BuildVenueLabelsOptions = {},
): Record<string, string> {
  void asset;
  const out: Record<string, string> = {};
  for (const slug of venues) {
    const meta = OTHER_VENUE_META[slug];
    const display = meta?.displayName ?? slug;
    const quote = meta?.quoteCurrency;
    const venueClass = meta?.venueClass;
    let instrument: string | undefined;
    if (venueClass === "cex" || venueClass === "perp_dex") {
      instrument =
        options.instrument ?? defaultInstrumentType(venueClass) ?? undefined;
    }

    const parts: string[] = [display];
    if (instrument) parts.push(instrument);
    if (quote) parts.push(quote);
    out[slug] = parts.join(" · ");
  }
  return out;
}

/** Short summary labels: "Binance spot", "Hyperliquid perp". */
export function venueSummaryLabel(
  slug: string,
  options: { instrument?: "spot" | "perp" } = {},
): string {
  const meta = OTHER_VENUE_META[slug];
  const name = meta?.displayName ?? slug;
  if (!meta) return name;
  if (meta.venueClass === "cex") {
    return `${name} ${options.instrument ?? "spot"}`;
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

export function venueDisplayName(slug: string): string {
  return OTHER_VENUE_META[slug]?.displayName ?? slug;
}
