import { describe, expect, it } from "vitest";

import type { Quote, SizeQuotePair } from "@/lib/api";
import { detailFromPair, feeSummary } from "@/lib/matrixDetail";

function quote(
  overrides: Partial<Quote> & Pick<Quote, "venue" | "status">,
): Quote {
  const gasUnknown = overrides.fee_breakdown?.gas_unknown ?? false;
  return {
    snapshot_id: "s1",
    asset: "BTC",
    instrument_type: "spot",
    side: "buy",
    notional_usd: "1000",
    mid: "100000",
    mid_source: "binance_usdm_index",
    mid_timestamp: "2026-08-03T12:00:00Z",
    mid_stale: false,
    timestamp: "2026-08-03T12:00:01Z",
    fee_breakdown: {
      embedded_in_price: false,
      platform_fee_bps: "0",
      gas_unknown: gasUnknown,
      explicit_fee_bps: gasUnknown ? null : "10",
      trading_fee_bps: gasUnknown ? null : "10",
      gas_bps: gasUnknown ? null : "0",
    },
    effective_price: overrides.status === "ok" ? "100100" : null,
    spread_bps: overrides.status === "ok" ? "10" : null,
    total_cost_bps: overrides.status === "ok" && !gasUnknown ? "20" : null,
    qty_base: overrides.status === "ok" ? "0.1" : null,
    ...overrides,
  };
}

function pair(
  venue: string,
  buy: Quote | null,
  extras: Partial<SizeQuotePair> = {},
): SizeQuotePair {
  return {
    snapshot_id: "s1",
    venue,
    asset: "BTC",
    instrument_type: "spot",
    notional_usd: "1000",
    buy,
    sell: null,
    ...extras,
  };
}

describe("detailFromPair (WHI-841)", () => {
  it("surfaces effective price and compact fees for an ok buy leg", () => {
    const p = pair(
      "binance",
      quote({ venue: "binance", status: "ok", total_cost_bps: "20" }),
    );
    const d = detailFromPair(p, "buy");
    // Locale-dependent separators; assert numeric content, not exact string.
    expect(d.effective.replace(/[^\d.]/g, "")).toMatch(/^100100/);
    expect(d.fees).toBe("10.00f · 0.00g");
    expect(d.feesTitle).toContain("trading fee 10.00 bps");
  });

  it("marks gas_unknown in the fees cell without a fake —f trading token", () => {
    const p = pair(
      "uniswap_eth",
      quote({
        venue: "uniswap_eth",
        status: "ok",
        total_cost_bps: null,
        fee_breakdown: {
          embedded_in_price: true,
          platform_fee_bps: "0",
          gas_unknown: true,
          explicit_fee_bps: null,
          trading_fee_bps: null,
          gas_bps: null,
        },
      }),
    );
    const d = detailFromPair(p, "buy");
    expect(d.fees).toBe("gas? · in price");
    expect(d.fees).not.toContain("—f");
    expect(d.feesTitle).toContain("gas unknown");
  });

  it("returns dashes for missing / non-ok quotes", () => {
    expect(detailFromPair(undefined, "buy")).toEqual({
      effective: "—",
      fees: "—",
      feesTitle: undefined,
    });
    const p = pair(
      "binance",
      quote({ venue: "binance", status: "error", error_code: "timeout" }),
    );
    expect(detailFromPair(p, "buy").effective).toBe("—");
  });
});

describe("feeSummary", () => {
  it("includes platform fee in the title when non-zero", () => {
    const q = quote({
      venue: "binance",
      status: "ok",
      fee_breakdown: {
        embedded_in_price: false,
        platform_fee_bps: "1.5",
        gas_unknown: false,
        explicit_fee_bps: "10",
        trading_fee_bps: "10",
        gas_bps: "0",
      },
    });
    expect(feeSummary(q).title).toContain("platform 1.50 bps");
  });
});
