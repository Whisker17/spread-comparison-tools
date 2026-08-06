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

/** Form-level coverage (mirrors GET /assets FormInfo.coverage / WHI-799 §6.1.1). */
export type FormCoverage = "live" | "unverified" | "absent";

export type StockFormDef = {
  id: StockFormId;
  form_class: FormClass;
  /** Venue slug → representation label. */
  representations: Readonly<Record<string, string>>;
  coverage: FormCoverage;
};

/**
 * Synthetic venue slug for venue-less forms (summary row only).
 * Never sent to /quotes or stream filters (WHI-892 §6.1.1).
 */
export const CATALOG_SUMMARY_VENUE = "catalog" as const;

/** Non-live forms never win §5.2 best (WHI-892). Live-only eligibility. */
export function isBestEligibleCoverage(coverage: FormCoverage): boolean {
  return coverage === "live";
}

/** Human chrome for form coverage on row labels (SSOT for coverage copy). */
export function coverageBadgeLabel(coverage: FormCoverage): string | null {
  if (coverage === "unverified") return "unverified";
  if (coverage === "absent") return "no route";
  return null;
}

/** Representation text for venue-less summary rows (SSOT with badge labels). */
export function coverageSummaryRepresentation(
  coverage: FormCoverage,
): string {
  if (coverage === "absent") return "no route (surveyed)";
  if (coverage === "unverified") return "not verified";
  return "—";
}

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
    {
      id: "bstock",
      form_class: "tokenized",
      coverage: "live",
      // WHI-891: Pancake Phase A; Tessera absent (WHI-890).
      representations: {
        binance: "TSLABUSDT",
        pancakeswap_bsc: "TSLAB",
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
    {
      id: "bstock",
      form_class: "tokenized",
      coverage: "live",
      representations: {
        binance: "AAPLBUSDT",
        pancakeswap_bsc: "AAPLB",
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
    {
      id: "bstock",
      form_class: "tokenized",
      coverage: "live",
      representations: {
        binance: "MSFTBUSDT",
        pancakeswap_bsc: "MSFTB",
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
      representations: {
        binance: "GOOGLBUSDT",
        pancakeswap_bsc: "GOOGLB",
      },
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
      representations: {
        binance: "METABUSDT",
        pancakeswap_bsc: "METAB",
      },
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
      representations: {
        binance: "AMZNBUSDT",
        pancakeswap_bsc: "AMZNB",
      },
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
      representations: {
        binance: "SPYBUSDT",
        pancakeswap_bsc: "SPYB",
      },
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
  TSLA: "Tesla · equity perp + bStocks (BN + Pancake)",
  AAPL: "Apple · equity perp + bStocks (BN + Pancake)",
  MSFT: "Microsoft · equity perp + bStocks (BN + Pancake)",
  QQQ: "Invesco QQQ · equity perp + bStocks (BSC)",
  SPCX: "SpaceX · bStocks (BSC)",
  CRCL: "Circle · equity perp + bStocks",
  GOOGL: "Alphabet · equity perp + bStocks (BN + Pancake) + xStocks CEX",
  AMD: "AMD · equity perp (Bybit AMDSTOCKUSDT)",
  PLTR: "Palantir · equity perp",
  META: "Meta · equity perp + bStocks (BN + Pancake) + xStocks CEX",
  AMZN: "Amazon · equity perp + bStocks (BN + Pancake) + xStocks CEX",
  SPY: "SPDR S&P 500 · equity perp (no HL exact) + bStocks (BN + Pancake)",
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
  coverage: FormCoverage;
  /** Instrument type for label chrome (perp form → perp, tokenized → spot on CEX). */
  instrumentType?: InstrumentType;
  /** True when this is a venue-less form summary row (no adapter). */
  isCatalogSummary: boolean;
};

function parseCoverage(raw: string | undefined | null): FormCoverage {
  if (raw === "unverified" || raw === "absent" || raw === "live") return raw;
  // Unknown wire values fail closed to unverified (never silently live).
  return "unverified";
}

function mapWireForm(f: {
  id: string;
  form_class?: string;
  coverage?: string;
  representations?: Record<string, string> | null;
}): StockFormDef | null {
  const id = f.id.toLowerCase() as StockFormId;
  const wireClass =
    f.form_class === "perp" || f.form_class === "tokenized"
      ? (f.form_class as FormClass)
      : formClassOf(id);
  if (!wireClass) return null;
  return {
    id,
    form_class: wireClass,
    // Carry wire coverage through — never stamp "live" (WHI-892 defect 2).
    coverage: parseCoverage(f.coverage),
    representations: f.representations ?? {},
  };
}

/**
 * Parse forms from GET /assets (all coverages), falling back to static live.
 *
 * WHI-892: list, do not omit — unverified/absent forms render with badges.
 * Static fallback stays live-only (offline shell) when the assets query has
 * not loaded; once the API responds, wire forms replace static entirely.
 */
export function resolveStockForms(
  underlying: string,
  assets: readonly AssetResponse[] | undefined | null,
): StockFormDef[] {
  const key = underlying.toUpperCase();
  const fromApi = assets?.find((a) => a.id.toUpperCase() === key);
  if (fromApi?.forms != null) {
    // Catalog row present: use every form the wire lists (may be empty).
    // Do NOT fall back to static when the API returns forms (even 0 live).
    const mapped = fromApi.forms
      .map((f) => mapWireForm(f))
      .filter((f): f is StockFormDef => f !== null);
    return sortForms(mapped);
  }
  // Underlying absent from GET /assets (or assets not loaded yet) → static live.
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
 * Expand forms into matrix row keys, stable order: form display order, then
 * venue slug. Venue-less forms get one ``catalog|<form>`` summary row
 * (WHI-892 §6.1.1) so "no route" / "unverified" are visible.
 */
export function buildStockMatrixRows(
  forms: readonly StockFormDef[],
): StockMatrixRow[] {
  const rows: StockMatrixRow[] = [];
  for (const form of forms) {
    const venues = Object.keys(form.representations).sort();
    if (venues.length === 0) {
      rows.push({
        rowKey: makeRowKey(CATALOG_SUMMARY_VENUE, form.id),
        venue: CATALOG_SUMMARY_VENUE,
        form: form.id,
        formClass: form.form_class,
        representation: coverageSummaryRepresentation(form.coverage),
        coverage: form.coverage,
        isCatalogSummary: true,
      });
      continue;
    }
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
        coverage: form.coverage,
        instrumentType,
        isCatalogSummary: false,
      });
    }
  }
  return rows;
}

/**
 * Real venue slugs for stream /quotes filters.
 * Excludes the synthetic catalog summary venue.
 */
export function venuesFromForms(forms: readonly StockFormDef[]): string[] {
  const set = new Set<string>();
  for (const form of forms) {
    for (const v of Object.keys(form.representations)) {
      set.add(v);
    }
  }
  return [...set].sort();
}

/**
 * Live form ids with at least one real venue — default quote fan-out only.
 * Unverified/absent stay matrix chrome (badge / summary row) without stream
 * requests (WHI-799 §6.1.1 default fan-out = live; WHI-892 out of scope to
 * widen sampling).
 */
export function liveQuoteableFormIds(forms: readonly StockFormDef[]): string[] {
  return forms
    .filter(
      (f) =>
        f.coverage === "live" && Object.keys(f.representations).length > 0,
    )
    .map((f) => f.id);
}

/** Row keys that must never win §5.2 best (non-live coverage). */
export function nonLiveRowKeys(rows: readonly StockMatrixRow[]): string[] {
  return rows
    .filter((r) => !isBestEligibleCoverage(r.coverage))
    .map((r) => r.rowKey);
}

/** True when any form is bstock (show rebase footnote). */
export function hasBstockForm(forms: readonly StockFormDef[]): boolean {
  return forms.some((f) => f.id === "bstock");
}

function rowFormBadge(row: StockMatrixRow): string {
  const form = formBadgeLabel(row.form);
  const cov = coverageBadgeLabel(row.coverage);
  return cov ? `${form} · ${cov}` : form;
}

/**
 * Matrix / TOB row labels with form badge + venue symbol + coverage chrome.
 * Keys are form-aware row keys (`venue|form`).
 */
export function buildStocksVenueLabels(
  rows: readonly StockMatrixRow[],
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const row of rows) {
    if (row.isCatalogSummary) {
      out[row.rowKey] = `${rowFormBadge(row)} · ${row.representation}`;
      continue;
    }
    out[row.rowKey] = buildVenueRowLabels([row.venue], {
      representations: { [row.venue]: row.representation },
      instrumentType: row.instrumentType,
      includeOrderbookSymbol: true,
      formBadge: rowFormBadge(row),
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
    if (row.isCatalogSummary) {
      out[row.rowKey] = `${rowFormBadge(row)} · ${row.representation}`;
      continue;
    }
    out[row.rowKey] = buildVenueSummaryLabel(row.venue, {
      representations: { [row.venue]: row.representation },
      instrumentType: row.instrumentType,
      includeOrderbookSymbol: true,
      formBadge: rowFormBadge(row),
    });
  }
  return out;
}

/** Orderbook rows only (CEX / perp DEX) for TOB strip. */
export function orderbookRows(
  rows: readonly StockMatrixRow[],
): StockMatrixRow[] {
  return rows.filter(
    (r) => !r.isCatalogSummary && isOrderbookVenue(r.venue),
  );
}

/** Persistent bStocks footnote (WHI-798 §8 Q14). */
export const BSTOCKS_REBASE_FOOTNOTE =
  "bStocks handle dividends and splits by rebasing balances. Around rebase days, CEX spot and on-chain pool prices can jump relative to each other — treat large one-day basis moves with care.";

/** Tooltip for emphasized mid-source badge on stock boards (WHI-799 §3.3). */
export const STOCKS_MID_SOURCE_HINT =
  "Stock mid sources (cex_tradfi_index / proxy_perp_mark_median / CEX spot TOB) are weaker than crypto P0 index mids (WHI-799 §3.3).";
