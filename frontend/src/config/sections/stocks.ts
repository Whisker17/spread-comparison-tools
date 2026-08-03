import { NOTIONAL_TIERS_USD } from "@/config/notionals";
import {
  ON_CHAIN_VENUE_CLASSES,
  ORDERBOOK_VENUE_CLASSES,
} from "@/config/sections/helpers";
import type {
  SectionConfig,
  VenueClass,
  VenueMeta,
} from "@/config/sections/types";

export { ON_CHAIN_VENUE_CLASSES, ORDERBOOK_VENUE_CLASSES };

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

export const STOCKS_VENUE_META: Readonly<Record<string, VenueMeta>> = {
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
  pancakeswap_bsc: {
    displayName: "PancakeSwap (BSC)",
    venueClass: "amm_dex",
    quoteCurrency: "USDT",
  },
  tessera_bsc: {
    displayName: "Tessera (BSC)",
    venueClass: "prop_amm",
    quoteCurrency: "USDT",
  },
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
 * Page-level header only (not a quote matrix config).
 * Live matrices use `tokenizedStocksBoard` / `equityPerpsBoard` — never pass
 * this object into AssetSpreadBlock (empty venues would drop the filter).
 */
export const stocksSection = {
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
 * CEX/perp instrument label for matrix rows. Prefer `section.instrumentType`
 * (same field that drives GET /quotes) so labels cannot disagree with the
 * request shape.
 */
function instrumentTypeFor(
  venueClass: VenueClass | undefined,
  sectionInstrument: SectionConfig["instrumentType"] | undefined,
): string | undefined {
  if (venueClass === "perp_dex") return "perp";
  if (venueClass === "cex") {
    if (sectionInstrument === "perp" || sectionInstrument === "spot") {
      return sectionInstrument;
    }
    // Default CEX books are spot when the board does not pin instrumentType.
    return "spot";
  }
  return undefined;
}

export type BuildStocksVenueLabelsOptions = {
  board: StocksBoardKind;
  /** Forward `section.instrumentType` so CEX labels match the quotes request. */
  instrumentType?: SectionConfig["instrumentType"];
  representationOverrides?: Readonly<Record<string, string>>;
};

function staticRepsFor(
  asset: string,
  board: StocksBoardKind,
): Readonly<Record<string, string>> {
  if (board === "tokenized") {
    return (
      TOKENIZED_REPRESENTATIONS[asset as TokenizedStockAsset] ??
      ({} as Readonly<Record<string, string>>)
    );
  }
  return (
    EQUITY_PERP_REPRESENTATIONS[asset as EquityPerpAsset] ??
    ({} as Readonly<Record<string, string>>)
  );
}

/**
 * Matrix / TOB row labels.
 * - Tokenized on-chain: display + token symbol + USDT
 * - CEX tokenized: display + spot + USDT (+ symbol)
 * - Equity perp: display + perp + quote (+ xyz: coin for HL)
 */
export function buildStocksVenueLabels(
  asset: string,
  venues: readonly string[],
  options: BuildStocksVenueLabelsOptions,
): Record<string, string> {
  const staticReps = staticRepsFor(asset, options.board);
  const reps = { ...staticReps, ...options.representationOverrides };
  const out: Record<string, string> = {};

  for (const slug of venues) {
    const meta = STOCKS_VENUE_META[slug];
    const display = meta?.displayName ?? slug;
    const quote = meta?.quoteCurrency;
    const venueClass = meta?.venueClass;
    const rep = reps[slug];
    const instrument = instrumentTypeFor(venueClass, options.instrumentType);

    const parts: string[] = [display];

    if (venueClass && ON_CHAIN_VENUE_CLASSES.has(venueClass)) {
      if (rep) parts.push(rep);
    } else if (venueClass === "cex" || venueClass === "perp_dex") {
      if (instrument) parts.push(instrument);
      // Venue symbol / HIP-3 coin so representation is not dropped from the row.
      if (rep) parts.push(rep);
    }

    if (quote) parts.push(quote);
    out[slug] = parts.join(" · ");
  }

  return out;
}

export function stocksVenueSummaryLabel(
  slug: string,
  options: {
    board: StocksBoardKind;
    asset?: string;
    instrumentType?: SectionConfig["instrumentType"];
    representationOverrides?: Readonly<Record<string, string>>;
  },
): string {
  const meta = STOCKS_VENUE_META[slug];
  const name = meta?.displayName ?? slug;
  if (!meta) return name;

  if (meta.venueClass === "cex") {
    const inst = instrumentTypeFor("cex", options.instrumentType) ?? "spot";
    if (options.asset) {
      const staticRep = staticRepsFor(options.asset, options.board)[slug];
      const rep = options.representationOverrides?.[slug] ?? staticRep;
      if (rep) return `${name} ${inst} (${rep})`;
    }
    return `${name} ${inst}`;
  }
  if (meta.venueClass === "perp_dex") {
    if (options.asset) {
      const staticRep = staticRepsFor(options.asset, options.board)[slug];
      const rep = options.representationOverrides?.[slug] ?? staticRep;
      if (rep) return `${name} perp (${rep})`;
    }
    return `${name} perp`;
  }
  if (options.asset && ON_CHAIN_VENUE_CLASSES.has(meta.venueClass)) {
    const staticRep = staticRepsFor(options.asset, options.board)[slug];
    const rep = options.representationOverrides?.[slug] ?? staticRep;
    if (rep) return `${name} (${rep})`;
  }
  return name;
}

export function isStocksOrderbookVenue(slug: string): boolean {
  const cls = STOCKS_VENUE_META[slug]?.venueClass;
  return cls !== undefined && ORDERBOOK_VENUE_CLASSES.has(cls);
}

/** Persistent P0-A footnote (WHI-798 §8 Q14). */
export const BSTOCKS_REBASE_FOOTNOTE =
  "bStocks handle dividends and splits by rebasing balances. Around rebase days, CEX spot and on-chain pool prices can jump relative to each other — treat large one-day basis moves with care.";

/** Tooltip for emphasized mid-source badge on stock boards (WHI-799 §3.3). */
export const STOCKS_MID_SOURCE_HINT =
  "Stock mid sources (cex_tradfi_index / proxy_perp_mark_median / CEX spot TOB) are weaker than crypto P0 index mids (WHI-799 §3.3).";
