import { NOTIONAL_TIERS_USD } from "@/config/notionals";
import type {
  SectionConfig,
  VenueMeta,
} from "@/config/sections/types";

/**
 * Crypto blue chips section (WHI-809).
 *
 * Assets + venue coverage + representation labels are fixed by
 * `docs/research/WHI-798-asset-category-inventory.md` §3 / §7.1.
 * Keep in lockstep with backend `spread_compare/assets.py` (GET /assets).
 */

/** EVM public AMMs — no native SOL market (WHI-798 §3.1). */
export const EVM_AMM_VENUES = [
  "uniswap_eth",
  "aerodrome_base",
  "pancakeswap_bsc",
] as const;

/** Tessera EVM instances — SOL has Solana-only prop coverage (WHI-798 §3.1). */
export const TESSERA_EVM_VENUES = ["tessera_base", "tessera_bsc"] as const;

/**
 * Canonical row order: CEX → perp DEX → public AMM → prop AMM.
 * Includes Tessera Base/BSC for BTC/ETH prop coverage (WHI-798 v2).
 */
export const BLUE_CHIP_VENUES = [
  "binance",
  "bybit",
  "hyperliquid",
  "lighter",
  "apex",
  "uniswap_eth",
  "aerodrome_base",
  "pancakeswap_bsc",
  "humidifi",
  "tessera_solana",
  "tessera_base",
  "tessera_bsc",
  "bisonfi",
] as const;

export type BlueChipAsset = "BTC" | "ETH" | "SOL";

/**
 * Static venue metadata for labels / quote-currency annotation.
 * Display names mirror `spread_compare/venues.py`; quote currency is FE
 * annotation only (WHI-798 §7.1) — not re-derived from adapters.
 */
export const BLUE_CHIP_VENUE_META: Readonly<Record<string, VenueMeta>> = {
  binance: {
    slug: "binance",
    displayName: "Binance",
    venueClass: "cex",
    quoteCurrency: "USDT",
  },
  bybit: {
    slug: "bybit",
    displayName: "Bybit",
    venueClass: "cex",
    quoteCurrency: "USDT",
  },
  hyperliquid: {
    slug: "hyperliquid",
    displayName: "Hyperliquid",
    venueClass: "perp_dex",
    // USDC-margined perps (not USDT).
    quoteCurrency: "USDC",
  },
  lighter: {
    slug: "lighter",
    displayName: "Lighter",
    venueClass: "perp_dex",
    quoteCurrency: "USDC",
  },
  apex: {
    slug: "apex",
    displayName: "ApeX",
    venueClass: "perp_dex",
    quoteCurrency: "USDT",
  },
  uniswap_eth: {
    slug: "uniswap_eth",
    displayName: "Uniswap (Ethereum)",
    venueClass: "amm_dex",
    quoteCurrency: "USDC",
    chain: "ethereum",
  },
  aerodrome_base: {
    slug: "aerodrome_base",
    displayName: "Aerodrome (Base)",
    venueClass: "amm_dex",
    quoteCurrency: "USDC",
    chain: "base",
  },
  pancakeswap_bsc: {
    slug: "pancakeswap_bsc",
    displayName: "PancakeSwap (BSC)",
    venueClass: "amm_dex",
    quoteCurrency: "USDT",
    chain: "bsc",
  },
  humidifi: {
    slug: "humidifi",
    displayName: "HumidiFi",
    venueClass: "prop_amm",
    quoteCurrency: "USDC",
    chain: "solana",
  },
  tessera_solana: {
    slug: "tessera_solana",
    displayName: "Tessera (Solana)",
    venueClass: "prop_amm",
    quoteCurrency: "USDC",
    chain: "solana",
  },
  tessera_base: {
    slug: "tessera_base",
    displayName: "Tessera (Base)",
    venueClass: "prop_amm",
    quoteCurrency: "USDC",
    chain: "base",
  },
  tessera_bsc: {
    slug: "tessera_bsc",
    displayName: "Tessera (BSC)",
    venueClass: "prop_amm",
    quoteCurrency: "USDT",
    chain: "bsc",
  },
  bisonfi: {
    slug: "bisonfi",
    displayName: "BisonFi",
    venueClass: "prop_amm",
    quoteCurrency: "USDC",
    chain: "solana",
  },
};

/**
 * Per-asset venue → representation label (WHI-798 §3.3).
 * On-chain wrappers are different assets with different bridge/peg risk —
 * never render bare "BTC" / "ETH" / "SOL" for those rows.
 * Solana prop ETH uses Wormhole WETH (distinct from canonical WETH on EVM).
 */
export const REPRESENTATIONS: Readonly<
  Record<BlueChipAsset, Readonly<Record<string, string>>>
> = {
  BTC: {
    binance: "BTCUSDT",
    bybit: "BTCUSDT",
    hyperliquid: "BTC",
    lighter: "BTC",
    apex: "BTC-USDT",
    humidifi: "cbBTC",
    tessera_solana: "cbBTC",
    bisonfi: "cbBTC",
    tessera_base: "cbBTC",
    tessera_bsc: "BTCB",
    uniswap_eth: "WBTC",
    aerodrome_base: "cbBTC",
    pancakeswap_bsc: "BTCB",
  },
  ETH: {
    binance: "ETHUSDT",
    bybit: "ETHUSDT",
    hyperliquid: "ETH",
    lighter: "ETH",
    apex: "ETH-USDT",
    // Solana prop: Wormhole-bridged WETH (WHI-798 §3.3), not canonical ETH WETH.
    humidifi: "Wormhole WETH",
    tessera_solana: "Wormhole WETH",
    bisonfi: "Wormhole WETH",
    tessera_base: "WETH",
    // tessera_bsc: no ETH main market — hidden via hiddenVenuesByAsset
    uniswap_eth: "WETH",
    aerodrome_base: "WETH",
    // BSC bridged ETH — must not render as bare logical "ETH".
    pancakeswap_bsc: "BSC ETH",
  },
  SOL: {
    binance: "SOLUSDT",
    bybit: "SOLUSDT",
    hyperliquid: "SOL",
    lighter: "SOL",
    apex: "SOL-USDT",
    humidifi: "wSOL",
    tessera_solana: "wSOL",
    bisonfi: "wSOL",
  },
};

/** Orderbook venue classes that can produce TopOfBook (WHI-799 §6.3). */
export const ORDERBOOK_VENUE_CLASSES = new Set(["cex", "perp_dex"]);

/** On-chain venue classes that need wrapper representation labels. */
export const ON_CHAIN_VENUE_CLASSES = new Set(["amm_dex", "prop_amm"]);

export const BLUE_CHIP_POLL_MS = 30_000;

export const blueChipsSection: SectionConfig = {
  id: "blue-chips",
  title: "Crypto blue chips",
  description:
    "BTC / ETH / SOL across CEX, perp DEX, public AMM, and prop AMM. Where is it cheapest to buy at your size right now?",
  assets: ["BTC", "ETH", "SOL"],
  venues: [...BLUE_CHIP_VENUES],
  // SOL: Solana-only prop + no EVM AMM (WHI-798 §3.1).
  // ETH: no Tessera BSC market (WHI-797/798).
  hiddenVenuesByAsset: {
    SOL: [...EVM_AMM_VENUES, ...TESSERA_EVM_VENUES],
    ETH: ["tessera_bsc"],
  },
  notionals: [...NOTIONAL_TIERS_USD],
  defaultSideView: "buy",
  cellMetric: "total_cost_bps",
  showTopOfBook: true,
  pollIntervalMs: BLUE_CHIP_POLL_MS,
};

/** Merge section-level + per-asset hidden venues for one asset. */
export function hiddenVenuesForAsset(
  section: SectionConfig,
  asset: string,
): string[] {
  const global = section.hiddenVenues ?? [];
  const perAsset = section.hiddenVenuesByAsset?.[asset] ?? [];
  return [...new Set([...global, ...perAsset])];
}

/**
 * Visible venue row order for an asset: section venues minus hidden, stable
 * order from `section.venues` (or BLUE_CHIP_VENUES fallback).
 */
export function venuesForAsset(
  section: SectionConfig,
  asset: string,
): string[] {
  const hidden = new Set(hiddenVenuesForAsset(section, asset));
  const ordered =
    section.venues.length > 0 ? section.venues : [...BLUE_CHIP_VENUES];
  return ordered.filter((v) => !hidden.has(v));
}

function defaultInstrumentType(venueClass: string | undefined): string | undefined {
  if (venueClass === "perp_dex") return "perp";
  if (venueClass === "cex") return "spot";
  return undefined;
}

/**
 * Build display labels for matrix rows.
 *
 * - On-chain (AMM / prop AMM): display name + representation + quote currency
 * - CEX / perp: display name + instrument type + quote currency
 * - Representation never collapses to bare logical ticker for wrappers
 */
export function buildVenueLabels(
  asset: string,
  venues: readonly string[],
  /**
   * Live instrument_type from pairs when available (defaults: CEX=spot,
   * perp_dex=perp). Keyed by venue slug.
   */
  instrumentByVenue?: Readonly<Record<string, string | undefined>>,
): Record<string, string> {
  const reps =
    REPRESENTATIONS[asset as BlueChipAsset] ??
    ({} as Readonly<Record<string, string>>);
  const out: Record<string, string> = {};

  for (const slug of venues) {
    const meta = BLUE_CHIP_VENUE_META[slug];
    const display = meta?.displayName ?? slug;
    const quote = meta?.quoteCurrency;
    const venueClass = meta?.venueClass;
    const rep = reps[slug];
    const instrument =
      instrumentByVenue?.[slug] ?? defaultInstrumentType(venueClass);

    const parts: string[] = [display];

    if (venueClass && ON_CHAIN_VENUE_CLASSES.has(venueClass)) {
      if (rep) {
        parts.push(rep);
      }
    } else if (venueClass === "cex" || venueClass === "perp_dex") {
      if (instrument) {
        parts.push(instrument);
      }
    }

    if (quote) {
      parts.push(quote);
    }

    out[slug] = parts.join(" · ");
  }

  return out;
}

/**
 * Annotate summary venue with instrument type when CEX/perp, matching the
 * example shape "Binance perp".
 */
export function venueSummaryLabel(
  slug: string,
  instrumentType?: string | null,
): string {
  const meta = BLUE_CHIP_VENUE_META[slug];
  const name = meta?.displayName ?? slug;
  if (!meta) return name;
  if (meta.venueClass === "cex") {
    const itype = instrumentType ?? "spot";
    return `${name} ${itype}`;
  }
  if (meta.venueClass === "perp_dex") {
    return `${name} perp`;
  }
  // On-chain: display name only; representation is for matrix rows.
  return name;
}

export function isOrderbookVenue(slug: string): boolean {
  const cls = BLUE_CHIP_VENUE_META[slug]?.venueClass;
  return cls !== undefined && ORDERBOOK_VENUE_CLASSES.has(cls);
}

/** Representation for an asset×venue, or undefined if not listed. */
export function representationFor(
  asset: string,
  venue: string,
): string | undefined {
  return REPRESENTATIONS[asset as BlueChipAsset]?.[venue];
}
