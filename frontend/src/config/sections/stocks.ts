import {
  DEFAULT_NOTIONAL_USD,
  NOTIONAL_TIERS_USD,
} from "@/config/notionals";
import {
  buildVenueRowLabels,
  buildVenueSummaryLabel,
} from "@/config/sections/helpers";
import type { SectionConfig } from "@/config/sections/types";
import type { InstrumentType } from "@/lib/api";

/**
 * Stocks section (WHI-810): two sub-boards.
 *
 * P0-A — bStocks BSC three-way (CEX spot × Pancake × Tessera BSC)
 * P0-B — equity perps across five orderbook venues
 *
 * Asset plan: `docs/research/WHI-798-asset-category-inventory.md` §4 / §6.2.
 * Keep representation labels in lockstep with `spread_compare/assets.py`.
 */

export const STOCKS_POLL_MS = 30_000;

/** P0-A tokenized board assets (backend id NVDAON; UI labels Ondo). */
export const TOKENIZED_STOCK_ASSETS = [
  "QQQB",
  "SPCXB",
  "NVDAB",
  "NVDAON",
] as const;

export type TokenizedStockAsset = (typeof TOKENIZED_STOCK_ASSETS)[number];

/** P0-A venues: Binance spot × Pancake BSC × Tessera BSC (all USDT quote). */
export const TOKENIZED_STOCK_VENUES = [
  "binance",
  "pancakeswap_bsc",
  "tessera_bsc",
] as const;

/** P0-B equity-perp assets — exact ticker on five venues (no SPY/QQQ). */
export const EQUITY_PERP_ASSETS = ["TSLA", "NVDA", "AAPL", "MSFT"] as const;

export type EquityPerpAsset = (typeof EQUITY_PERP_ASSETS)[number];

export const EQUITY_PERP_VENUES = [
  "binance",
  "bybit",
  "hyperliquid",
  "lighter",
  "apex",
] as const;

/** Display titles for logical asset ids (NVDAON → Ondo annotation). */
export const STOCK_ASSET_TITLES: Readonly<Record<string, string>> = {
  QQQB: "QQQB",
  SPCXB: "SPCXB",
  NVDAB: "NVDAB",
  NVDAON: "NVDAON · Ondo",
  TSLA: "TSLA",
  NVDA: "NVDA",
  AAPL: "AAPL",
  MSFT: "MSFT",
};

export const STOCK_ASSET_SUBTITLES: Readonly<Record<string, string>> = {
  QQQB: "Invesco QQQ · bStocks (BSC)",
  SPCXB: "SpaceX · bStocks (BSC)",
  NVDAB: "NVIDIA · bStocks (BSC)",
  NVDAON: "NVIDIA Ondo representation — not the same mint as NVDAB",
  TSLA: "Equity perp · exact ticker on five venues",
  NVDA: "Equity perp · exact ticker on five venues",
  AAPL: "Equity perp · exact ticker on five venues",
  MSFT: "Equity perp · exact ticker on five venues",
};

/**
 * Static representation fallbacks (GET /assets is preferred at runtime).
 * On-chain rows must not collapse to a bare unrelated ticker.
 */
export const TOKENIZED_REPRESENTATIONS: Readonly<
  Record<TokenizedStockAsset, Readonly<Record<string, string>>>
> = {
  QQQB: {
    binance: "QQQBUSDT",
    pancakeswap_bsc: "QQQB",
    tessera_bsc: "QQQB",
  },
  SPCXB: {
    binance: "SPCXBUSDT",
    pancakeswap_bsc: "SPCXB",
    tessera_bsc: "SPCXB",
  },
  NVDAB: {
    binance: "NVDABUSDT",
    pancakeswap_bsc: "NVDAB",
    tessera_bsc: "NVDAB",
  },
  NVDAON: {
    pancakeswap_bsc: "NVDAon",
    tessera_bsc: "NVDAon",
  },
};

export const EQUITY_PERP_REPRESENTATIONS: Readonly<
  Record<EquityPerpAsset, Readonly<Record<string, string>>>
> = {
  TSLA: {
    binance: "TSLAUSDT",
    bybit: "TSLAUSDT",
    hyperliquid: "xyz:TSLA",
    lighter: "TSLA",
    apex: "TSLA-USDT",
  },
  NVDA: {
    binance: "NVDAUSDT",
    bybit: "NVDAUSDT",
    hyperliquid: "xyz:NVDA",
    lighter: "NVDA",
    apex: "NVDA-USDT",
  },
  AAPL: {
    binance: "AAPLUSDT",
    bybit: "AAPLUSDT",
    hyperliquid: "xyz:AAPL",
    lighter: "AAPL",
    apex: "AAPL-USDT",
  },
  MSFT: {
    binance: "MSFTUSDT",
    bybit: "MSFTUSDT",
    hyperliquid: "xyz:MSFT",
    lighter: "MSFT",
    apex: "MSFT-USDT",
  },
};

/**
 * Page-level header only (not a quote matrix config / not a SectionConfig).
 * Live matrices use `tokenizedStocksBoard` / `equityPerpsBoard`.
 */
export const stocksPageHeader = {
  id: "stocks",
  title: "Stocks",
  description:
    "bStocks BSC three-way (CEX spot × AMM × prop AMM) plus equity perps across five orderbook venues. Where is it cheapest to buy the same exposure at your size?",
} as const;

/**
 * P0-A: tokenized three-way on BSC.
 * NVDAON has no Binance spot — hide that row (WHI-798 §6.2 / assets.py).
 */
export const tokenizedStocksBoard: SectionConfig = {
  id: "stocks-tokenized",
  title: "bStocks BSC three-way",
  description:
    "Same tokenized equity across Binance spot, PancakeSwap v3, and Tessera prop AMM — all on BSC, USDT quote leg.",
  assets: [...TOKENIZED_STOCK_ASSETS],
  venues: [...TOKENIZED_STOCK_VENUES],
  hiddenVenuesByAsset: {
    NVDAON: ["binance"],
  },
  notionals: [...NOTIONAL_TIERS_USD],
  defaultNotional: DEFAULT_NOTIONAL_USD,
  defaultSideView: "buy",
  cellMetric: "total_cost_bps",
  showTopOfBook: true,
  pollIntervalMs: STOCKS_POLL_MS,
};

/** P0-B: equity perps — exact tickers only (no SPY/QQQ HL proxies). */
export const equityPerpsBoard: SectionConfig = {
  id: "stocks-equity-perps",
  title: "Equity perps",
  description:
    "TSLA / NVDA / AAPL / MSFT across Binance TradFi, Bybit, Hyperliquid HIP-3 (xyz:), Lighter, and ApeX.",
  assets: [...EQUITY_PERP_ASSETS],
  venues: [...EQUITY_PERP_VENUES],
  notionals: [...NOTIONAL_TIERS_USD],
  defaultNotional: DEFAULT_NOTIONAL_USD,
  defaultSideView: "buy",
  cellMetric: "total_cost_bps",
  showTopOfBook: true,
  pollIntervalMs: STOCKS_POLL_MS,
  // CEX symbols for these assets are perp-only (WHI-826); without this the
  // aggregator defaults CEX to spot and every Binance/Bybit cell is "—".
  instrumentType: "perp",
};

export type StocksBoardKind = "tokenized" | "equity_perp";

/**
 * Everything the label builders need about *where* a row is rendered — one
 * object instead of the same four fields threaded through every call site.
 */
export type StocksLabelContext = {
  /** Which sub-board (picks the representation table). */
  board: StocksBoardKind;
  /** Logical asset id, e.g. "QQQB" / "TSLA". */
  asset: string;
  /**
   * Forward `section.instrumentType` so CEX labels match the quotes request
   * (equity perps pin "perp"; the tokenized board leaves CEX on spot).
   */
  instrumentType?: InstrumentType;
  /** Representations from `GET /assets`, merged over the static fallback. */
  representationOverrides?: Readonly<Record<string, string>>;
};

/** Static per-board table merged under `GET /assets` overrides. */
function representationsFor(
  ctx: StocksLabelContext,
): Readonly<Record<string, string>> {
  const staticReps =
    ctx.board === "tokenized"
      ? TOKENIZED_REPRESENTATIONS[ctx.asset as TokenizedStockAsset]
      : EQUITY_PERP_REPRESENTATIONS[ctx.asset as EquityPerpAsset];
  return { ...(staticReps ?? {}), ...ctx.representationOverrides };
}

/**
 * Matrix / TOB row labels. Shape lives in `helpers.buildVenueRowLabels`;
 * this section only supplies the representation data.
 *
 * - Tokenized on-chain: display + token symbol + USDT
 * - CEX tokenized: display + spot + venue symbol
 * - Equity perp: display + perp + venue symbol / `xyz:` coin (+ quote when
 *   the symbol does not already end in it)
 */
export function buildStocksVenueLabels(
  venues: readonly string[],
  ctx: StocksLabelContext,
): Record<string, string> {
  return buildVenueRowLabels(venues, {
    representations: representationsFor(ctx),
    instrumentType: ctx.instrumentType,
    // Stock boards show the venue symbol: the logical id (NVDAB vs NVDAon,
    // xyz:TSLA) does not identify the traded instrument on its own.
    includeOrderbookSymbol: true,
  });
}

export function stocksVenueSummaryLabel(
  slug: string,
  ctx: StocksLabelContext,
): string {
  return buildVenueSummaryLabel(slug, {
    representations: representationsFor(ctx),
    instrumentType: ctx.instrumentType,
    includeOrderbookSymbol: true,
  });
}

/** Persistent P0-A footnote (WHI-798 §8 Q14). */
export const BSTOCKS_REBASE_FOOTNOTE =
  "bStocks handle dividends and splits by rebasing balances. Around rebase days, CEX spot and on-chain pool prices can jump relative to each other — treat large one-day basis moves with care.";

/** Tooltip for emphasized mid-source badge on stock boards (WHI-799 §3.3). */
export const STOCKS_MID_SOURCE_HINT =
  "Stock mid sources (cex_tradfi_index / proxy_perp_mark_median / CEX spot TOB) are weaker than crypto P0 index mids (WHI-799 §3.3).";
