import { describe, expect, it } from "vitest";

import type { Quote } from "@/lib/api";
import {
  decideCellRender,
  includeQuoteInHeat,
  isEligibleForBest,
} from "@/lib/status";

function q(partial: Partial<Quote> & Pick<Quote, "status">): Quote {
  return {
    snapshot_id: "s",
    venue: "mock",
    asset: "BTC",
    instrument_type: "spot",
    side: "buy",
    notional_usd: "1000",
    mid: "100",
    mid_source: "binance_usdm_index",
    mid_timestamp: "2026-08-03T12:00:00Z",
    mid_stale: false,
    quote_stale: false,
    timestamp: "2026-08-03T12:00:00Z",
    fee_breakdown: {
      embedded_in_price: false,
      platform_fee_bps: "0",
      gas_unknown: false,
    },
    ...partial,
  };
}

describe("decideCellRender", () => {
  it('maps no_quote and unsupported_asset to dash "—"', () => {
    expect(decideCellRender(q({ status: "no_quote" })).kind).toBe("dash");
    expect(decideCellRender(q({ status: "unsupported_asset" })).label).toBe(
      "—",
    );
  });

  it("maps insufficient_liquidity to badge kind", () => {
    const d = decideCellRender(q({ status: "insufficient_liquidity" }));
    expect(d.kind).toBe("insufficient_liquidity");
    expect(d.badge).toMatch(/liquidity/i);
  });

  it("maps error to badge with retry hint", () => {
    const d = decideCellRender(
      q({ status: "error", error_code: "timeout" }),
    );
    expect(d.kind).toBe("error");
    expect(d.hint).toMatch(/retry/i);
  });

  it("maps not_sampled to muted not-sampled badge, never best (WHI-865)", () => {
    const d = decideCellRender(
      q({ status: "not_sampled", error_code: "not_sampled" }),
    );
    expect(d.kind).toBe("not_sampled");
    expect(d.badge).toBe("not sampled");
    expect(d.badgeVariant).toBe("muted");
    expect(d.hint).toBeUndefined();
    expect(d.eligibleForBest).toBe(false);
  });

  it("maps error+not_initialized to muted unavailable (WHI-840)", () => {
    const d = decideCellRender(
      q({ status: "error", error_code: "not_initialized" }),
    );
    expect(d.kind).toBe("dash");
    expect(d.badge).toBe("unavailable");
    expect(d.eligibleForBest).toBe(false);
  });

  it("maps rate_limited to distinct RATE LIMITED badge (WHI-844)", () => {
    const d = decideCellRender(
      q({ status: "rate_limited", error_code: "rate_limited" }),
    );
    expect(d.kind).toBe("rate_limited");
    expect(d.badge).toBe("RATE LIMITED");
    expect(d.eligibleForBest).toBe(false);
  });

  it("maps excessive_impact to number + badge, never best (WHI-845)", () => {
    const d = decideCellRender(
      q({
        status: "excessive_impact",
        error_code: "excessive_impact",
        effective_price: "344641.67",
        spread_bps: "44011.18",
        total_cost_bps: "38283",
        qty_base: "2.9",
        price_impact_bps: "8100",
        fee_breakdown: {
          embedded_in_price: true,
          platform_fee_bps: "0",
          gas_unknown: false,
          explicit_fee_bps: "0",
          gas_bps: "0",
        },
      }),
      { formattedMetric: "38283.00", metricKey: "total_cost_bps" },
    );
    expect(d.kind).toBe("excessive_impact");
    expect(d.label).toBe("38283.00");
    expect(d.badge).toMatch(/excessive impact/i);
    expect(d.eligibleForBest).toBe(false);
  });

  it("maps gas_unknown ok quotes to cost_incomplete for total_cost metric", () => {
    const d = decideCellRender(
      q({
        status: "ok",
        spread_bps: "4.4",
        total_cost_bps: null,
        effective_price: "100",
        qty_base: "1",
        fee_breakdown: {
          embedded_in_price: true,
          platform_fee_bps: "0",
          gas_unknown: true,
        },
      }),
      { formattedMetric: "—", metricKey: "total_cost_bps" },
    );
    expect(d.kind).toBe("cost_incomplete");
    expect(d.eligibleForBest).toBe(false);
  });

  it("still shows spread_bps value when gas_unknown (cost incomplete only for total)", () => {
    const d = decideCellRender(
      q({
        status: "ok",
        spread_bps: "4.4",
        total_cost_bps: null,
        effective_price: "100",
        qty_base: "1",
        fee_breakdown: {
          embedded_in_price: true,
          platform_fee_bps: "0",
          gas_unknown: true,
        },
      }),
      { formattedMetric: "4.40", metricKey: "spread_bps" },
    );
    expect(d.kind).toBe("value");
    expect(d.label).toBe("4.40");
    // Best-venue eligibility still requires total_cost (independent of display metric).
    expect(d.eligibleForBest).toBe(false);
  });

  it("surfaces mid_stale independently of status", () => {
    const d = decideCellRender(
      q({
        status: "ok",
        mid_stale: true,
        total_cost_bps: "10",
        spread_bps: "5",
        effective_price: "100",
        qty_base: "1",
        fee_breakdown: {
          embedded_in_price: false,
          platform_fee_bps: "0",
          gas_unknown: false,
          trading_fee_bps: "5",
          explicit_fee_bps: "5",
          gas_bps: "0",
        },
      }),
      { formattedMetric: "10.00" },
    );
    expect(d.midStale).toBe(true);
    expect(d.kind).toBe("value");
    expect(d.eligibleForBest).toBe(true);
  });
});

describe("isEligibleForBest", () => {
  it("excludes quote_stale even when status=ok (WHI-846)", () => {
    expect(
      isEligibleForBest(
        q({
          status: "ok",
          total_cost_bps: "1",
          quote_stale: true,
          effective_price: "100",
          spread_bps: "1",
          qty_base: "1",
          fee_breakdown: {
            embedded_in_price: false,
            platform_fee_bps: "0",
            gas_unknown: false,
            trading_fee_bps: "1",
            explicit_fee_bps: "1",
            gas_bps: "0",
          },
        }),
      ),
    ).toBe(false);
  });

  it("requires status=ok and non-null total_cost_bps", () => {
    expect(
      isEligibleForBest(
        q({
          status: "ok",
          total_cost_bps: "1",
          fee_breakdown: {
            embedded_in_price: false,
            platform_fee_bps: "0",
            gas_unknown: false,
          },
        }),
      ),
    ).toBe(true);
    expect(isEligibleForBest(q({ status: "no_quote" }))).toBe(false);
    expect(isEligibleForBest(q({ status: "rate_limited" }))).toBe(false);
    expect(
      isEligibleForBest(
        q({ status: "not_sampled", error_code: "not_sampled" }),
      ),
    ).toBe(false);
    expect(
      isEligibleForBest(
        q({
          status: "excessive_impact",
          total_cost_bps: "38283",
          price_impact_bps: "8100",
        }),
      ),
    ).toBe(false);
    expect(
      isEligibleForBest(
        q({
          status: "ok",
          total_cost_bps: null,
          fee_breakdown: {
            embedded_in_price: true,
            platform_fee_bps: "0",
            gas_unknown: true,
          },
        }),
      ),
    ).toBe(false);
  });
});

describe("includeQuoteInHeat", () => {
  it("excludes excessive_impact so extreme bps cannot enter heat range (WHI-845)", () => {
    expect(
      includeQuoteInHeat(
        q({
          status: "excessive_impact",
          total_cost_bps: "38283",
          price_impact_bps: "8100",
        }),
      ),
    ).toBe(false);
    expect(
      includeQuoteInHeat(
        q({
          status: "ok",
          total_cost_bps: "5",
          fee_breakdown: {
            embedded_in_price: false,
            platform_fee_bps: "0",
            gas_unknown: false,
          },
        }),
      ),
    ).toBe(true);
  });
});
