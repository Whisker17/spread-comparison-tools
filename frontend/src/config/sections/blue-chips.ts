import { NOTIONAL_TIERS_USD } from "@/config/notionals";
import type {
  SectionConfig,
  VenueClass,
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
 * Display names mirror `spread_compare/venues.py` (GET /venues). Quote
 * currency is FE-only annotation (WHI-798 §7.1). Representation labels
 * prefer `GET /assets` when BlueChipsSection has fetched them; the
 * static `REPRESENTATIONS` table is the offline / test fallback kept in
 * lockstep with `spread_compare/assets.py`.
 */
export const BLUE_CHIP_VENUE_META: Readonly<Record<string, VenueMeta>> = {
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
    // USDC-margined perps (not USDT).
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
  uniswap_eth: {
    displayName: "Uniswap (Ethereum)",
    venueClass: "amm_dex",
    quoteCurrency: "USDC",
  },
  aerodrome_base: {
    displayName: "Aerodrome (Base)",
    venueClass: "amm_dex",
    quoteCurrency: "USDC",
  },
  pancakeswap_bsc: {
    displayName: "PancakeSwap (BSC)",
    venueClass: "amm_dex",
    quoteCurrency: "USDT",
  },
  humidifi: {
    displayName: "HumidiFi",
    venueClass: "prop_amm",
    quoteCurrency: "USDC",
  },
  tessera_solana: {
    displayName: "Tessera (Solana)",
    venueClass: "prop_amm",
    quoteCurrency: "USDC",
  },
  tessera_base: {
    displayName: "Tessera (Base)",
    venueClass: "prop_amm",
    quoteCurrency: "USDC",
  },
  tessera_bsc: {
    displayName: "Tessera (BSC)",
    venueClass: "prop_amm",
    quoteCurrency: "USDT",
  },
  bisonfi: {
    displayName: "BisonFi",
    venueClass: "prop_amm",
    quoteCurrency: "USDC",
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
export const ORDERBOOK_VENUE_CLASSES: ReadonlySet<VenueClass> = new Set([
  "cex",
  "perp_dex",
]);

/** On-chain venue classes that need wrapper representation labels. */
export const ON_CHAIN_VENUE_CLASSES: ReadonlySet<VenueClass> = new Set([
  "amm_dex",
  "prop_amm",
]);

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

function defaultInstrumentType(
  venueClass: VenueClass | undefined,
): string | undefined {
  if (venueClass === "perp_dex") return "perp";
  if (venueClass === "cex") return "spot";
  return undefined;
}

export type BuildVenueLabelsOptions = {
  /**
   * Representation map from `GET /assets` (preferred). Merged over the
   * static `REPRESENTATIONS` fallback so the backend catalog stays SSOT
   * when the API is available.
   */
  representationOverrides?: Readonly<Record<string, string>>;
};

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
  options: BuildVenueLabelsOptions = {},
): Record<string, string> {
  const staticReps =
    REPRESENTATIONS[asset as BlueChipAsset] ??
    ({} as Readonly<Record<string, string>>);
  const reps = { ...staticReps, ...options.representationOverrides };
  const out: Record<string, string> = {};

  for (const slug of venues) {
    const meta = BLUE_CHIP_VENUE_META[slug];
    const display = meta?.displayName ?? slug;
    const quote = meta?.quoteCurrency;
    const venueClass = meta?.venueClass;
    const rep = reps[slug];
    const instrument = defaultInstrumentType(venueClass);

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
 * example shape "Binance perp". On-chain winners include the wrapper
 * representation so bridge/peg risk is not dropped from the prose.
 */
export function venueSummaryLabel(
  slug: string,
  options: {
    asset?: string;
    /** From GET /assets when available. */
    representationOverrides?: Readonly<Record<string, string>>;
  } = {},
): string {
  const meta = BLUE_CHIP_VENUE_META[slug];
  const name = meta?.displayName ?? slug;
  if (!meta) return name;
  if (meta.venueClass === "cex") {
    return `${name} ${defaultInstrumentType("cex") ?? "spot"}`;
  }
  if (meta.venueClass === "perp_dex") {
    return `${name} perp`;
  }
  if (options.asset && ON_CHAIN_VENUE_CLASSES.has(meta.venueClass)) {
    const staticRep = REPRESENTATIONS[options.asset as BlueChipAsset]?.[slug];
    const rep = options.representationOverrides?.[slug] ?? staticRep;
    if (rep) return `${name} (${rep})`;
  }
  return name;
}

export function isOrderbookVenue(slug: string): boolean {
  const cls = BLUE_CHIP_VENUE_META[slug]?.venueClass;
  return cls !== undefined && ORDERBOOK_VENUE_CLASSES.has(cls);
}
