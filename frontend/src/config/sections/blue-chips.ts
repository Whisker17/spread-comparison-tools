import {
  DEFAULT_SIZE_VIEW,
  NOTIONAL_TIERS_USD,
} from "@/config/notionals";
import {
  buildVenueRowLabels,
  buildVenueSummaryLabel,
  isOrderbookVenue,
  ON_CHAIN_VENUE_CLASSES,
  ORDERBOOK_VENUE_CLASSES,
  VENUE_META,
} from "@/config/sections/helpers";
import type { SectionConfig } from "@/config/sections/types";

/**
 * Re-exported for callers that already import section config from here.
 * The SSOT is `config/sections/helpers.ts` — do not redefine venue metadata
 * or venue-class sets per section.
 */
export {
  isOrderbookVenue,
  ON_CHAIN_VENUE_CLASSES,
  ORDERBOOK_VENUE_CLASSES,
  VENUE_META,
};

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
  defaultNotional: DEFAULT_SIZE_VIEW,
  defaultSideView: "buy",
  cellMetric: "total_cost_bps",
  showTopOfBook: true,
  pollIntervalMs: BLUE_CHIP_POLL_MS,
};

export type BuildVenueLabelsOptions = {
  /**
   * Representation map from `GET /assets` (preferred). Merged over the
   * static `REPRESENTATIONS` fallback so the backend catalog stays SSOT
   * when the API is available.
   */
  representationOverrides?: Readonly<Record<string, string>>;
};

/** Static fallback merged under `GET /assets` overrides for one asset. */
function representationsFor(
  asset: string,
  overrides?: Readonly<Record<string, string>>,
): Readonly<Record<string, string>> {
  return { ...(REPRESENTATIONS[asset as BlueChipAsset] ?? {}), ...overrides };
}

/**
 * Matrix / TOB row labels. Shape lives in `helpers.buildVenueRowLabels`;
 * this section only supplies its representation data. Crypto blue chips omit
 * the CEX/perp venue symbol — it just repeats the logical ticker.
 */
export function buildVenueLabels(
  asset: string,
  venues: readonly string[],
  options: BuildVenueLabelsOptions = {},
): Record<string, string> {
  return buildVenueRowLabels(venues, {
    representations: representationsFor(
      asset,
      options.representationOverrides,
    ),
  });
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
  return buildVenueSummaryLabel(slug, {
    representations: options.asset
      ? representationsFor(options.asset, options.representationOverrides)
      : undefined,
  });
}
