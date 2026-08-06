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

/** Phase-1 underlyings (catalog order matches assets.py / WHI-798 §6.2.1). */
export const STOCK_UNDERLYINGS = [
  "NVDA",
  "TSLA",
  "AAPL",
  "MSFT",
  "QQQ",
  "SPCX",
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
};

export const STOCK_ASSET_TITLES: Readonly<Record<string, string>> = {
  NVDA: "NVDA",
  TSLA: "TSLA",
  AAPL: "AAPL",
  MSFT: "MSFT",
  QQQ: "QQQ",
  SPCX: "SPCX",
};

export const STOCK_ASSET_SUBTITLES: Readonly<Record<string, string>> = {
  NVDA: "NVIDIA · equity perp + bStocks + Ondo (shared mid)",
  TSLA: "Tesla · equity perp",
  AAPL: "Apple · equity perp",
  MSFT: "Microsoft · equity perp",
  QQQ: "Invesco QQQ · bStocks (BSC)",
  SPCX: "SpaceX · bStocks (BSC)",
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
  if (fromApi?.forms && fromApi.forms.length > 0) {
    const live = fromApi.forms
      .filter((f) => f.coverage === "live")
      .map((f): StockFormDef | null => {
        const id = f.id.toLowerCase() as StockFormId;
        if (!(id in FORM_BADGE_LABELS)) return null;
        const fc = formClassOf(id);
        if (!fc) return null;
        return {
          id,
          form_class: fc,
          coverage: "live",
          representations: f.representations ?? {},
        };
      })
      .filter((f): f is StockFormDef => f !== null);
    if (live.length > 0) return sortForms(live);
  }
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
    const badge = FORM_BADGE_LABELS[row.form] ?? row.form;
    // Reuse helper shape per form (instrument + rep) then inject form badge.
    const base = buildVenueRowLabels([row.venue], {
      representations: { [row.venue]: row.representation },
      instrumentType: row.instrumentType,
      includeOrderbookSymbol: true,
    })[row.venue];
    // Insert form badge after display name: "Binance · Perp · NVDAUSDT"
    // base is already "Binance · perp · NVDAUSDT" — replace instrument word
    // with the product form badge when present, else prepend badge.
    const label = injectFormBadge(base ?? row.venue, badge, row);
    out[row.rowKey] = label;
  }
  return out;
}

function injectFormBadge(
  baseLabel: string,
  badge: string,
  row: StockMatrixRow,
): string {
  // Prefer swapping CEX/perp instrument word for the form badge so we do not
  // double up ("perp · Perp"). On-chain labels get the badge after display name.
  const meta = VENUE_META[row.venue];
  if (!meta) {
    return `${baseLabel} · ${badge}`;
  }
  if (meta.venueClass === "cex" || meta.venueClass === "perp_dex") {
    // "Binance · perp · NVDAUSDT" → "Binance · Perp · NVDAUSDT"
    return baseLabel.replace(
      new RegExp(`^${escapeRegExp(meta.displayName)} · (?:perp|spot)`),
      `${meta.displayName} · ${badge}`,
    );
  }
  // On-chain: "Tessera (BSC) · NVDAB · USDT" → "Tessera (BSC) · bStocks · NVDAB · USDT"
  if (row.representation && baseLabel.includes(row.representation)) {
    return baseLabel.replace(
      row.representation,
      `${badge} · ${row.representation}`,
    );
  }
  return `${baseLabel} · ${badge}`;
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Summary prose labels (shorter; still include form badge + symbol). */
export function stocksVenueSummaryLabels(
  rows: readonly StockMatrixRow[],
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const row of rows) {
    const badge = FORM_BADGE_LABELS[row.form] ?? row.form;
    const base = buildVenueSummaryLabel(row.venue, {
      representations: { [row.venue]: row.representation },
      instrumentType: row.instrumentType,
      includeOrderbookSymbol: true,
    });
    // "Binance perp (NVDAUSDT)" → "Binance Perp (NVDAUSDT)" with form badge
    const meta = VENUE_META[row.venue];
    if (meta && (meta.venueClass === "cex" || meta.venueClass === "perp_dex")) {
      out[row.rowKey] = base
        .replace(/ perp\b/i, ` ${badge}`)
        .replace(/ spot\b/i, ` ${badge}`);
    } else if (row.representation) {
      out[row.rowKey] = base.includes(row.representation)
        ? base.replace(
            `(${row.representation})`,
            `(${badge} ${row.representation})`,
          )
        : `${base} (${badge})`;
    } else {
      out[row.rowKey] = `${base} (${badge})`;
    }
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
