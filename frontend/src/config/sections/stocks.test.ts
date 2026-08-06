import { describe, expect, it } from "vitest";

import {
  BSTOCKS_REBASE_FOOTNOTE,
  buildStockMatrixRows,
  buildStocksVenueLabels,
  FORM_BADGE_LABELS,
  hasBstockForm,
  resolveStockForms,
  STOCK_FORMS_STATIC,
  STOCK_UNDERLYINGS,
  stocksBoard,
  stocksVenueSummaryLabels,
  venuesFromForms,
} from "@/config/sections/stocks";
import { isOrderbookVenue } from "@/config/sections/helpers";
import type { AssetResponse, Quote, SizeQuotePair } from "@/lib/api";
import { makeRowKey } from "@/lib/pairIdentity";
import { bestVenuePerTier, formatSnapshotSummary } from "@/lib/summary";

function quote(
  overrides: Partial<Quote> & Pick<Quote, "venue" | "status">,
): Quote {
  const gasUnknown = overrides.fee_breakdown?.gas_unknown ?? false;
  return {
    snapshot_id: "s1",
    asset: "NVDA",
    instrument_type: "spot",
    side: "buy",
    notional_usd: "10000",
    mid: "500",
    mid_source: "binance_spot_tob",
    mid_timestamp: "2026-08-03T12:00:00Z",
    mid_stale: false,
    quote_stale: false,
    timestamp: "2026-08-03T12:00:01Z",
    fee_breakdown: {
      embedded_in_price: false,
      platform_fee_bps: "0",
      gas_unknown: gasUnknown,
      explicit_fee_bps: gasUnknown ? null : "10",
      trading_fee_bps: gasUnknown ? null : "10",
      gas_bps: gasUnknown ? null : "0",
    },
    effective_price: overrides.status === "ok" ? "501" : null,
    spread_bps: overrides.status === "ok" ? "10" : null,
    total_cost_bps: overrides.status === "ok" && !gasUnknown ? "20" : null,
    qty_base: overrides.status === "ok" ? "20" : null,
    ...overrides,
  };
}

function pair(
  venue: string,
  notional: string,
  buy: Quote | null,
  form?: string | null,
): SizeQuotePair {
  return {
    snapshot_id: "s1",
    venue,
    asset: "NVDA",
    instrument_type: form === "perp" ? "perp" : "spot",
    form: form ?? null,
    notional_usd: notional,
    buy,
    sell: null,
  };
}

describe("stocks section config (WHI-882 underlying-first)", () => {
  it("lists Phase-1 underlyings (no legacy token ids)", () => {
    expect(stocksBoard.assets).toEqual([...STOCK_UNDERLYINGS]);
    expect(stocksBoard.assets).toContain("NVDA");
    expect(stocksBoard.assets).toContain("QQQ");
    expect(stocksBoard.assets).toContain("SPCX");
    expect(stocksBoard.assets).not.toContain("NVDAB");
    expect(stocksBoard.assets).not.toContain("NVDAON");
    expect(stocksBoard.assets).not.toContain("QQQB");
  });

  it("does not pin board-level instrumentType (form_class drives CEX)", () => {
    expect(stocksBoard.instrumentType).toBeUndefined();
  });

  it("NVDA static live forms cover perp + bstock + ondo", () => {
    const forms = resolveStockForms("NVDA", null);
    expect(forms.map((f) => f.id).sort()).toEqual(
      ["bstock", "ondo", "perp"].sort(),
    );
    const rows = buildStockMatrixRows(forms);
    const keys = rows.map((r) => r.rowKey);
    expect(keys).toContain(makeRowKey("binance", "perp"));
    expect(keys).toContain(makeRowKey("binance", "bstock"));
    expect(keys).toContain(makeRowKey("tessera_bsc", "bstock"));
    expect(keys).toContain(makeRowKey("tessera_bsc", "ondo"));
    expect(keys).toContain(makeRowKey("pancakeswap_bsc", "ondo"));
    // Two tessera rows are distinct by form.
    expect(
      keys.filter((k) => k.startsWith("tessera_bsc|")).sort(),
    ).toEqual(["tessera_bsc|bstock", "tessera_bsc|ondo"]);
  });

  it("labels include form badges so NVDAB vs NVDAon are distinct", () => {
    const forms = resolveStockForms("NVDA", null);
    const rows = buildStockMatrixRows(forms);
    const labels = buildStocksVenueLabels(rows);
    expect(labels[makeRowKey("tessera_bsc", "bstock")]).toMatch(/bStocks/i);
    expect(labels[makeRowKey("tessera_bsc", "bstock")]).toContain("NVDAB");
    expect(labels[makeRowKey("tessera_bsc", "ondo")]).toMatch(/Ondo/i);
    expect(labels[makeRowKey("tessera_bsc", "ondo")]).toContain("NVDAon");
    expect(labels[makeRowKey("binance", "perp")]).toMatch(/Perp/i);
    expect(labels[makeRowKey("binance", "perp")]).toContain("NVDAUSDT");
    expect(labels[makeRowKey("binance", "bstock")]).toMatch(/bStocks/i);
    expect(labels[makeRowKey("binance", "bstock")]).toContain("NVDABUSDT");
    expect(FORM_BADGE_LABELS.ondo).toBe("Ondo");
  });

  it("prefers GET /assets nested forms over static fallback", () => {
    const assets: AssetResponse[] = [
      {
        id: "TSLA",
        category: "stock",
        representations: null,
        forms: [
          {
            id: "perp",
            form_class: "perp",
            coverage: "live",
            representations: {
              binance: "TSLAUSDT",
              bybit: "TSLAUSDT",
            },
          },
          {
            id: "bstock",
            form_class: "tokenized",
            coverage: "unverified",
            representations: { binance: "TSLABUSDT" },
          },
        ],
      },
    ];
    const forms = resolveStockForms("TSLA", assets);
    // Only live forms.
    expect(forms.map((f) => f.id)).toEqual(["perp"]);
    expect(venuesFromForms(forms)).toEqual(["binance", "bybit"]);
  });

  it("does not resurrect static forms when the API returns zero live forms", () => {
    const assets: AssetResponse[] = [
      {
        id: "NVDA",
        category: "stock",
        representations: null,
        forms: [
          {
            id: "perp",
            form_class: "perp",
            coverage: "unverified",
            representations: { binance: "NVDAUSDT" },
          },
        ],
      },
    ];
    expect(resolveStockForms("NVDA", assets)).toEqual([]);
  });

  it("marks only orderbook venues for TOB rows", () => {
    const forms = resolveStockForms("NVDA", null);
    const rows = buildStockMatrixRows(forms);
    for (const row of rows) {
      if (row.form === "perp") {
        expect(isOrderbookVenue(row.venue)).toBe(true);
      }
      if (row.venue === "pancakeswap_bsc" || row.venue === "tessera_bsc") {
        expect(isOrderbookVenue(row.venue)).toBe(false);
      }
    }
  });

  it("summary labels keep form badge + symbol", () => {
    const forms = resolveStockForms("NVDA", null);
    const rows = buildStockMatrixRows(forms);
    const labels = stocksVenueSummaryLabels(rows);
    expect(labels[makeRowKey("hyperliquid", "perp")]).toMatch(/Perp/i);
    expect(labels[makeRowKey("hyperliquid", "perp")]).toContain("xyz:NVDA");
    expect(labels[makeRowKey("tessera_bsc", "ondo")]).toMatch(/Ondo/i);
  });

  it("detects bstock forms for the rebase footnote", () => {
    expect(hasBstockForm(resolveStockForms("NVDA", null))).toBe(true);
    expect(hasBstockForm(resolveStockForms("TSLA", null))).toBe(false);
    expect(hasBstockForm(STOCK_FORMS_STATIC.QQQ)).toBe(true);
  });

  it("ships a persistent bStocks rebase footnote", () => {
    expect(BSTOCKS_REBASE_FOOTNOTE.toLowerCase()).toMatch(/rebase/);
  });

  it("defaults poll interval to 30s", () => {
    expect(stocksBoard.pollIntervalMs).toBe(30_000);
  });
});

describe("stocks form_class best (WHI-799 §5.2 / WHI-882)", () => {
  it("picks one best per form_class (perp vs tokenized)", () => {
    const pairs = [
      pair(
        "binance",
        "10000",
        quote({
          venue: "binance",
          status: "ok",
          total_cost_bps: "15",
          form: "perp",
          instrument_type: "perp",
        }),
        "perp",
      ),
      pair(
        "hyperliquid",
        "10000",
        quote({
          venue: "hyperliquid",
          status: "ok",
          total_cost_bps: "8",
          form: "perp",
          instrument_type: "perp",
        }),
        "perp",
      ),
      pair(
        "binance",
        "10000",
        quote({
          venue: "binance",
          status: "ok",
          total_cost_bps: "25",
          form: "bstock",
        }),
        "bstock",
      ),
      pair(
        "tessera_bsc",
        "10000",
        quote({
          venue: "tessera_bsc",
          status: "ok",
          total_cost_bps: "12",
          form: "bstock",
        }),
        "bstock",
      ),
    ];

    const picks = bestVenuePerTier(pairs, { side: "buy" });
    expect(picks).toHaveLength(2);
    const perp = picks.find((p) => p.formClass === "perp");
    const tok = picks.find((p) => p.formClass === "tokenized");
    expect(perp?.venue).toBe("hyperliquid");
    expect(perp?.rowKey).toBe("hyperliquid|perp");
    expect(tok?.venue).toBe("tessera_bsc");
    expect(tok?.rowKey).toBe("tessera_bsc|bstock");
  });

  it("Tessera no_quote never wins; dash remains non-fatal", () => {
    const pairs = [
      pair(
        "binance",
        "10000",
        quote({ venue: "binance", status: "ok", total_cost_bps: "25", form: "bstock" }),
        "bstock",
      ),
      pair(
        "tessera_bsc",
        "10000",
        quote({
          venue: "tessera_bsc",
          status: "no_quote",
          total_cost_bps: null,
          form: "bstock",
        }),
        "bstock",
      ),
    ];
    const picks = bestVenuePerTier(pairs);
    expect(picks).toHaveLength(1);
    expect(picks[0]?.venue).toBe("binance");
    expect(picks[0]?.formClass).toBe("tokenized");
  });

  it("gas_unknown on-chain row is excluded from best ranking", () => {
    const pairs = [
      pair(
        "tessera_bsc",
        "1000",
        quote({
          venue: "tessera_bsc",
          status: "ok",
          total_cost_bps: null,
          spread_bps: "2",
          form: "bstock",
          fee_breakdown: {
            embedded_in_price: true,
            platform_fee_bps: "0",
            gas_unknown: true,
            explicit_fee_bps: null,
            gas_bps: null,
          },
        }),
        "bstock",
      ),
      pair(
        "binance",
        "1000",
        quote({
          venue: "binance",
          status: "ok",
          total_cost_bps: "18",
          form: "bstock",
        }),
        "bstock",
      ),
    ];
    const picks = bestVenuePerTier(pairs);
    expect(picks[0]?.venue).toBe("binance");

    const prose = formatSnapshotSummary(pairs, {
      asset: "NVDA",
      venueLabels: {
        "binance|bstock": "Binance bStocks",
        "tessera_bsc|bstock": "Tessera (BSC) bStocks",
      },
    });
    expect(prose).toMatch(/Binance bStocks/);
    expect(prose).not.toMatch(/Tessera/);
    expect(prose).toMatch(/tokenized/);
  });
});
