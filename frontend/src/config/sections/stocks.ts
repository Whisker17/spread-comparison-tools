import {
  DEFAULT_NOTIONAL_USD,
  NOTIONAL_TIERS_USD,
} from "@/config/notionals";
import {
  buildVenueRowLabels,
  buildVenueSummaryLabel,
  isOrderbookVenue,
  VENUE_META,
} from "@/config/sections/helpers";
// VENUE_META used by instrument-type inference in buildStockMatrixRows.
import type { SectionConfig } from "@/config/sections/types";
import type { AssetResponse, InstrumentType } from "@/lib/api";
import {
  formClassOf,
  makeRowKey,
  type FormClass,
} from "@/lib/pairIdentity";

/**
 * Stocks section (WHI-882): underlying-first.
 *
 * One matrix per underlying (NVDA, TSLA, …); rows are (venue, form) sharing
 * one reference mid. Spec: WHI-798 §6.2 v3 / WHI-799 §5.2 v3 / WHI-880.
 */

export const STOCKS_POLL_MS = 30_000;

/**
 * Stock underlyings (catalog order matches assets.py).
 * Phase-1 anchors + WHI-884 / WHI-883 P0 expansion.
 */
export const STOCK_UNDERLYINGS = [
  "NVDA",
  "TSLA",
  "AAPL",
  "MSFT",
  "QQQ",
  "SPCX",
  "CRCL",
  "GOOGL",
  "AMD",
  "PLTR",
  "META",
  "AMZN",
  "SPY",
  "MSTR",
] as const;

export type StockUnderlying = (typeof STOCK_UNDERLYINGS)[number];

/** Closed form vocabulary (WHI-798 §4.6). */
export type StockFormId =
  | "perp"
  | "bstock"
  | "ondo"
  | "xstock"
  | "xstock_cex";

/** Display badge text for form ids. */
export const FORM_BADGE_LABELS: Readonly<Record<StockFormId, string>> = {
  perp: "Perp",
  bstock: "bStocks",
  ondo: "Ondo",
  xstock: "xStocks",
  xstock_cex: "xStocks CEX",
};

/** Badge for a form id; unknown ids fall back to the raw id. */
export function formBadgeLabel(formId: string): string {
  const key = formId.toLowerCase() as StockFormId;
  return FORM_BADGE_LABELS[key] ?? formId;
}

/** Matrix column header for form-aware boards. */
export const STOCKS_MATRIX_ROW_HEADER = "Venue · form";

/** Best-highlight footnote for form_class grouping (WHI-799 §5.2 v3). */
export const STOCKS_BEST_NOTE =
  "stocks best is per form_class (perp vs tokenized)";

/** Preferred form display order within a matrix. */
export const FORM_DISPLAY_ORDER: readonly StockFormId[] = [
  "perp",
  "bstock",
  "ondo",
  "xstock_cex",
  "xstock",
];

export type StockFormDef = {
  id: StockFormId;
  form_class: FormClass;
  /** Venue slug → representation label. */
  representations: Readonly<Record<string, string>>;
  coverage: "live" | "unverified" | "absent";
};

/**
 * Static live-form fallback when `GET /assets` is unavailable.
 * Keep in lockstep with `spread_compare/assets.py` coverage=live forms.
 */
export const STOCK_FORMS_STATIC: Readonly<
  Record<StockUnderlying, readonly StockFormDef[]>
> = {
  NVDA: [
    {
      id: "perp",
      form_class: "perp",
      coverage: "live",
      representations: {
        binance: "NVDAUSDT",
        bybit: "NVDAUSDT",
        hyperliquid: "xyz:NVDA",
        lighter: "NVDA",
        apex: "NVDA-USDT",
      },
    },
    {
      id: "bstock",
      form_class: "tokenized",
      coverage: "live",
      representations: {
        binance: "NVDABUSDT",
        pancakeswap_bsc: "NVDAB",
        tessera_bsc: "NVDAB",
      },
    },
    {
      id: "ondo",
      form_class: "tokenized",
      coverage: "live",
      representations: {
        pancakeswap_bsc: "NVDAon",
        tessera_bsc: "NVDAon",
      },
    },
  ],
  TSLA: [
    {
      id: "perp",
      form_class: "perp",
      coverage: "live",
      representations: {
        binance: "TSLAUSDT",
        bybit: "TSLAUSDT",
        hyperliquid: "xyz:TSLA",
        lighter: "TSLA",
        apex: "TSLA-USDT",
      },
    },
  ],
  AAPL: [
    {
      id: "perp",
      form_class: "perp",
      coverage: "live",
      representations: {
        binance: "AAPLUSDT",
        bybit: "AAPLUSDT",
        hyperliquid: "xyz:AAPL",
        lighter: "AAPL",
        apex: "AAPL-USDT",
      },
    },
  ],
  MSFT: [
    {
      id: "perp",
      form_class: "perp",
      coverage: "live",
      representations: {
        binance: "MSFTUSDT",
        bybit: "MSFTUSDT",
        hyperliquid: "xyz:MSFT",
        lighter: "MSFT",
        apex: "MSFT-USDT",
      },
    },
  ],
  QQQ: [
    {
      id: "perp",
      form_class: "perp",
      coverage: "live",
      representations: {
        binance: "QQQUSDT",
        bybit: "QQQUSDT",
        lighter: "QQQ",
        apex: "QQQ-USDT",
      },
    },
    {
      id: "bstock",
      form_class: "tokenized",
      coverage: "live",
      representations: {
        binance: "QQQBUSDT",
        pancakeswap_bsc: "QQQB",
        tessera_bsc: "QQQB",
      },
    },
  ],
  SPCX: [
    {
      id: "bstock",
      form_class: "tokenized",
      coverage: "live",
      representations: {
        binance: "SPCXBUSDT",
        pancakeswap_bsc: "SPCXB",
        tessera_bsc: "SPCXB",
      },
    },
  ],
  CRCL: [
    {
      id: "perp",
      form_class: "perp",
      coverage: "live",
      representations: {
        binance: "CRCLUSDT",
        bybit: "CRCLUSDT",
        hyperliquid: "xyz:CRCL",
        lighter: "CRCL",
        apex: "CRCL-USDT",
      },
    },
    {
      id: "bstock",
      form_class: "tokenized",
      coverage: "live",
      representations: { binance: "CRCLBUSDT" },
    },
    {
      id: "xstock_cex",
      form_class: "tokenized",
      coverage: "live",
      representations: { bybit: "CRCLXUSDT" },
    },
  ],
  GOOGL: [
    {
      id: "perp",
      form_class: "perp",
      coverage: "live",
      representations: {
        binance: "GOOGLUSDT",
        bybit: "GOOGLUSDT",
        hyperliquid: "xyz:GOOGL",
        lighter: "GOOGL",
        apex: "GOOGL-USDT",
      },
    },
    {
      id: "bstock",
      form_class: "tokenized",
      coverage: "live",
      representations: { binance: "GOOGLBUSDT" },
    },
    {
      id: "xstock_cex",
      form_class: "tokenized",
      coverage: "live",
      representations: { bybit: "GOOGLXUSDT" },
    },
  ],
  AMD: [
    {
      id: "perp",
      form_class: "perp",
      coverage: "live",
      representations: {
        binance: "AMDUSDT",
        bybit: "AMDSTOCKUSDT",
        hyperliquid: "xyz:AMD",
        lighter: "AMD",
        apex: "AMD-USDT",
      },
    },
    {
      id: "bstock",
      form_class: "tokenized",
      coverage: "live",
      representations: { binance: "AMDBUSDT" },
    },
  ],
  PLTR: [
    {
      id: "perp",
      form_class: "perp",
      coverage: "live",
      representations: {
        binance: "PLTRUSDT",
        bybit: "PLTRUSDT",
        hyperliquid: "xyz:PLTR",
        lighter: "PLTR",
        apex: "PLTR-USDT",
      },
    },
    {
      id: "bstock",
      form_class: "tokenized",
      coverage: "live",
      representations: { binance: "PLTRBUSDT" },
    },
  ],
  META: [
    {
      id: "perp",
      form_class: "perp",
      coverage: "live",
      representations: {
        binance: "METAUSDT",
        bybit: "METAUSDT",
        hyperliquid: "xyz:META",
        lighter: "META",
        apex: "META-USDT",
      },
    },
    {
      id: "bstock",
      form_class: "tokenized",
      coverage: "live",
      representations: { binance: "METABUSDT" },
    },
    {
      id: "xstock_cex",
      form_class: "tokenized",
      coverage: "live",
      representations: { bybit: "METAXUSDT" },
    },
  ],
  AMZN: [
    {
      id: "perp",
      form_class: "perp",
      coverage: "live",
      representations: {
        binance: "AMZNUSDT",
        bybit: "AMZNUSDT",
        hyperliquid: "xyz:AMZN",
        lighter: "AMZN",
        apex: "AMZN-USDT",
      },
    },
    {
      id: "bstock",
      form_class: "tokenized",
      coverage: "live",
      representations: { binance: "AMZNBUSDT" },
    },
    {
      id: "xstock_cex",
      form_class: "tokenized",
      coverage: "live",
      representations: { bybit: "AMZNXUSDT" },
    },
  ],
  SPY: [
    {
      id: "perp",
      form_class: "perp",
      coverage: "live",
      representations: {
        binance: "SPYUSDT",
        bybit: "SPYUSDT",
        lighter: "SPY",
        apex: "SPY-USDT",
      },
    },
    {
      id: "bstock",
      form_class: "tokenized",
      coverage: "live",
      representations: { binance: "SPYBUSDT" },
    },
  ],
  MSTR: [
    {
      id: "perp",
      form_class: "perp",
      coverage: "live",
      representations: {
        binance: "MSTRUSDT",
        bybit: "MSTRUSDT",
        hyperliquid: "xyz:MSTR",
        lighter: "MSTR",
        apex: "MSTR-USDT",
      },
    },
    {
      id: "bstock",
      form_class: "tokenized",
      coverage: "live",
      representations: { binance: "MSTRBUSDT" },
    },
  ],
};

export const STOCK_ASSET_SUBTITLES: Readonly<Record<string, string>> = {
  NVDA: "NVIDIA · equity perp + bStocks + Ondo (shared mid)",
  TSLA: "Tesla · equity perp",
  AAPL: "Apple · equity perp",
  MSFT: "Microsoft · equity perp",
  QQQ: "Invesco QQQ · equity perp + bStocks (BSC)",
  SPCX: "SpaceX · bStocks (BSC)",
  CRCL: "Circle · equity perp + bStocks + xStocks CEX",
  GOOGL: "Alphabet · equity perp + bStocks + xStocks CEX",
  AMD: "AMD · equity perp (Bybit AMDSTOCKUSDT) + bStocks",
  PLTR: "Palantir · equity perp + bStocks",
  META: "Meta · equity perp + bStocks + xStocks CEX",
  AMZN: "Amazon · equity perp + bStocks + xStocks CEX",
  SPY: "SPDR S&P 500 · equity perp (no HL exact) + bStocks",
  MSTR: "MicroStrategy · equity perp + bStocks",
};

/**
 * Page-level header only (not a quote matrix config).
 * Live matrices use one board per underlying via `stocksBoard` + forms.
 */
export const stocksPageHeader = {
  id: "stocks",
  title: "Stocks",
  description:
    "One board per underlying — venue × form rows (perp, bStocks, Ondo, …) share a single reference mid so bps are comparable across tradable forms.",
} as const;

/**
 * Shared section shell: assets = underlyings; venues left empty so rows are
 * built from live forms (venue × form), not a flat venue list.
 */
export const stocksBoard: SectionConfig = {
  id: "stocks",
  title: "Stocks",
  description: stocksPageHeader.description,
  assets: [...STOCK_UNDERLYINGS],
  venues: [],
  notionals: [...NOTIONAL_TIERS_USD],
  defaultNotional: DEFAULT_NOTIONAL_USD,
  defaultSideView: "buy",
  cellMetric: "total_cost_bps",
  showTopOfBook: true,
  pollIntervalMs: STOCKS_POLL_MS,
  // No board-level instrumentType: form_class drives CEX spot vs perp (WHI-881).
};

/** One matrix row: venue + form. */
export type StockMatrixRow = {
  rowKey: string;
  venue: string;
  form: StockFormId;
  formClass: FormClass;
  representation: string;
  /** Instrument type for label chrome (perp form → perp, tokenized → spot on CEX). */
  instrumentType?: InstrumentType;
};

/** Parse live forms from GET /assets, falling back to static catalog. */
export function resolveStockForms(
  underlying: string,
  assets: readonly AssetResponse[] | undefined | null,
): StockFormDef[] {
  const key = underlying.toUpperCase();
  const fromApi = assets?.find((a) => a.id.toUpperCase() === key);
  if (fromApi?.forms != null) {
    // Catalog row present: use live forms only (may be empty if demoted).
    // Do NOT fall back to static when the API deliberately returns 0 live forms.
    // Unverified forms stay on GET /assets for discovery, not the matrix
    // (matches backend resolve_forms_filter → live).
    const live = fromApi.forms
      .filter((f) => f.coverage === "live")
      .map((f): StockFormDef | null => {
        const id = f.id.toLowerCase() as StockFormId;
        // Prefer wire form_class; fall back to closed vocabulary.
        const wireClass =
          f.form_class === "perp" || f.form_class === "tokenized"
            ? (f.form_class as FormClass)
            : formClassOf(id);
        if (!wireClass) return null;
        return {
          id,
          form_class: wireClass,
          coverage: "live",
          representations: f.representations ?? {},
        };
      })
      .filter((f): f is StockFormDef => f !== null);
    return sortForms(live);
  }
  // Underlying absent from GET /assets (or assets not loaded yet) → static.
  const staticForms =
    STOCK_FORMS_STATIC[key as StockUnderlying] ?? ([] as StockFormDef[]);
  return sortForms([...staticForms].filter((f) => f.coverage === "live"));
}

function sortForms(forms: StockFormDef[]): StockFormDef[] {
  const order = new Map(FORM_DISPLAY_ORDER.map((id, i) => [id, i]));
  return [...forms].sort(
    (a, b) => (order.get(a.id) ?? 99) - (order.get(b.id) ?? 99),
  );
}

/**
 * Expand live forms into matrix row keys, stable order:
 * form display order, then venue slug.
 */
export function buildStockMatrixRows(
  forms: readonly StockFormDef[],
): StockMatrixRow[] {
  const rows: StockMatrixRow[] = [];
  for (const form of forms) {
    const venues = Object.keys(form.representations).sort();
    for (const venue of venues) {
      const rep = form.representations[venue] ?? "";
      const instrumentType: InstrumentType | undefined =
        form.form_class === "perp"
          ? "perp"
          : VENUE_META[venue]?.venueClass === "cex"
            ? "spot"
            : undefined;
      rows.push({
        rowKey: makeRowKey(venue, form.id),
        venue,
        form: form.id,
        formClass: form.form_class,
        representation: rep,
        instrumentType,
      });
    }
  }
  return rows;
}

/** Union of venue slugs across live forms (for stream /quotes filter). */
export function venuesFromForms(forms: readonly StockFormDef[]): string[] {
  const set = new Set<string>();
  for (const form of forms) {
    for (const v of Object.keys(form.representations)) {
      set.add(v);
    }
  }
  return [...set].sort();
}

/** True when any live form is bstock (show rebase footnote). */
export function hasBstockForm(forms: readonly StockFormDef[]): boolean {
  return forms.some((f) => f.id === "bstock");
}

/**
 * Matrix / TOB row labels with form badge + venue symbol.
 * Keys are form-aware row keys (`venue|form`).
 */
export function buildStocksVenueLabels(
  rows: readonly StockMatrixRow[],
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const row of rows) {
    out[row.rowKey] = buildVenueRowLabels([row.venue], {
      representations: { [row.venue]: row.representation },
      instrumentType: row.instrumentType,
      includeOrderbookSymbol: true,
      formBadge: formBadgeLabel(row.form),
    })[row.venue]!;
  }
  return out;
}

/** Summary prose labels (shorter; still include form badge + symbol). */
export function stocksVenueSummaryLabels(
  rows: readonly StockMatrixRow[],
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const row of rows) {
    out[row.rowKey] = buildVenueSummaryLabel(row.venue, {
      representations: { [row.venue]: row.representation },
      instrumentType: row.instrumentType,
      includeOrderbookSymbol: true,
      formBadge: formBadgeLabel(row.form),
    });
  }
  return out;
}

/** Orderbook rows only (CEX / perp DEX) for TOB strip. */
export function orderbookRows(
  rows: readonly StockMatrixRow[],
): StockMatrixRow[] {
  return rows.filter((r) => isOrderbookVenue(r.venue));
}

/** Persistent bStocks footnote (WHI-798 §8 Q14). */
export const BSTOCKS_REBASE_FOOTNOTE =
  "bStocks handle dividends and splits by rebasing balances. Around rebase days, CEX spot and on-chain pool prices can jump relative to each other — treat large one-day basis moves with care.";

/** Tooltip for emphasized mid-source badge on stock boards (WHI-799 §3.3). */
export const STOCKS_MID_SOURCE_HINT =
  "Stock mid sources (cex_tradfi_index / proxy_perp_mark_median / CEX spot TOB) are weaker than crypto P0 index mids (WHI-799 §3.3).";
