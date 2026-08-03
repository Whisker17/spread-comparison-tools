import { describe, expect, it } from "vitest";

import type { SizeQuotePair } from "@/lib/api";
import {
  bestVenueMap,
  bestVenuePerTier,
  metricForPair,
} from "@/lib/summary";
import type { Quote } from "@/lib/api";

function quote(
  overrides: Partial<Quote> & Pick<Quote, "venue" | "status">,
): Quote {
  const gasUnknown = overrides.fee_breakdown?.gas_unknown ?? false;
  return {
    snapshot_id: "s1",
    asset: "BTC",
    instrument_type: "spot",
    side: "buy",
    notional_usd: "10000",
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
    total_cost_bps:
      overrides.status === "ok" && !gasUnknown ? "20" : null,
    qty_base: overrides.status === "ok" ? "0.1" : null,
    ...overrides,
  };
}

function pair(
  venue: string,
  notional: string,
  buy: Quote | null,
  extras: Partial<SizeQuotePair> = {},
): SizeQuotePair {
  return {
    snapshot_id: "s1",
    venue,
    asset: "BTC",
    instrument_type: "spot",
    notional_usd: notional,
    buy,
    sell: null,
    ...extras,
  };
}

describe("bestVenuePerTier", () => {
  it("picks lowest total_cost_bps among eligible quotes", () => {
    const pairs = [
      pair(
        "binance",
        "1000",
        quote({ venue: "binance", status: "ok", total_cost_bps: "30" }),
      ),
      pair(
        "bybit",
        "1000",
        quote({ venue: "bybit", status: "ok", total_cost_bps: "12" }),
      ),
      pair(
        "mock",
        "1000",
        quote({ venue: "mock", status: "ok", total_cost_bps: "18" }),
      ),
    ];
    const picks = bestVenuePerTier(pairs, { side: "buy" });
    expect(picks).toHaveLength(1);
    expect(picks[0]).toMatchObject({
      venue: "bybit",
      valueBps: 12,
      empty: false,
    });
  });

  it("excludes gas_unknown from best ranking (WHI-799 §5.2)", () => {
    const pairs = [
      pair(
        "uniswap_eth",
        "1000",
        quote({
          venue: "uniswap_eth",
          status: "ok",
          total_cost_bps: null,
          spread_bps: "1",
          fee_breakdown: {
            embedded_in_price: true,
            platform_fee_bps: "0",
            gas_unknown: true,
            explicit_fee_bps: null,
            gas_bps: null,
          },
        }),
      ),
      pair(
        "binance",
        "1000",
        quote({ venue: "binance", status: "ok", total_cost_bps: "25" }),
      ),
    ];
    const map = bestVenueMap(pairs);
    expect(map["1000"]).toBe("binance");
  });

  it("excludes non-ok statuses", () => {
    const pairs = [
      pair(
        "humidifi",
        "1000",
        quote({ venue: "humidifi", status: "no_quote" }),
      ),
      pair(
        "binance",
        "1000",
        quote({ venue: "binance", status: "error" }),
      ),
    ];
    const picks = bestVenuePerTier(pairs);
    expect(picks[0]?.empty).toBe(true);
  });

  it("honors hiddenVenues and venues allow-list", () => {
    const pairs = [
      pair(
        "binance",
        "1000",
        quote({ venue: "binance", status: "ok", total_cost_bps: "5" }),
      ),
      pair(
        "bybit",
        "1000",
        quote({ venue: "bybit", status: "ok", total_cost_bps: "50" }),
      ),
    ];
    expect(
      bestVenueMap(pairs, { hiddenVenues: ["binance"] })["1000"],
    ).toBe("bybit");
    expect(bestVenueMap(pairs, { venues: ["bybit"] })["1000"]).toBe("bybit");
  });

  it("groups by notional tier", () => {
    const pairs = [
      pair(
        "binance",
        "1000",
        quote({
          venue: "binance",
          status: "ok",
          total_cost_bps: "10",
          notional_usd: "1000",
        }),
      ),
      pair(
        "bybit",
        "10000",
        quote({
          venue: "bybit",
          status: "ok",
          total_cost_bps: "8",
          notional_usd: "10000",
        }),
      ),
    ];
    const map = bestVenueMap(pairs);
    expect(map["1000"]).toBe("binance");
    expect(map["10000"]).toBe("bybit");
  });
});

describe("metricForPair round_trip", () => {
  it("uses round_trip_total_cost_bps when both legs eligible", () => {
    const buy = quote({
      venue: "binance",
      status: "ok",
      side: "buy",
      total_cost_bps: "10",
    });
    const sell = quote({
      venue: "binance",
      status: "ok",
      side: "sell",
      total_cost_bps: "12",
    });
    const p = pair("binance", "1000", buy, {
      sell,
      round_trip_total_cost_bps: "22",
    });
    expect(metricForPair(p, "round_trip")).toBe(22);
  });
});

describe("bestVenuePerTier metric=spread_bps", () => {
  it("ranks by spread when requested", () => {
    const pairs = [
      pair(
        "binance",
        "1000",
        quote({
          venue: "binance",
          status: "ok",
          total_cost_bps: "5",
          spread_bps: "20",
        }),
      ),
      pair(
        "bybit",
        "1000",
        quote({
          venue: "bybit",
          status: "ok",
          total_cost_bps: "50",
          spread_bps: "3",
        }),
      ),
    ];
    expect(bestVenueMap(pairs, { metric: "spread_bps" })["1000"]).toBe("bybit");
    expect(bestVenueMap(pairs, { metric: "total_cost_bps" })["1000"]).toBe(
      "binance",
    );
  });
});
