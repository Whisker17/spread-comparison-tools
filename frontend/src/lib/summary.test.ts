import { describe, expect, it } from "vitest";

import type { SizeQuotePair } from "@/lib/api";
import {
  bestVenueMap,
  bestVenuePerTier,
  formatSnapshotSummary,
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
  it("excludes quote_stale from best ranking (WHI-846)", () => {
    const pairs = [
      pair(
        "humidifi",
        "1000",
        quote({
          venue: "humidifi",
          status: "ok",
          total_cost_bps: "5",
          quote_stale: true,
        }),
      ),
      pair(
        "binance",
        "1000",
        quote({ venue: "binance", status: "ok", total_cost_bps: "20" }),
      ),
    ];
    const picks = bestVenuePerTier(pairs, { side: "buy" });
    expect(picks).toHaveLength(1);
    expect(picks[0]).toMatchObject({ venue: "binance", valueBps: 20, empty: false });
  });

  it("mixed-age fixture: stale store row never wins best (WHI-848 push path)", () => {
    // Simulates a pushed view: poller sweep (stale age) beside a live book row.
    const staleBuy = quote({
      venue: "humidifi",
      status: "ok",
      total_cost_bps: "3",
      quote_stale: true,
      age_sec: 45,
      snapshot_id: "sweep-old",
    });
    const liveBuy = quote({
      venue: "binance",
      status: "ok",
      total_cost_bps: "18",
      quote_stale: false,
      age_sec: null,
      snapshot_id: "live-now",
    });
    const pairs = [
      pair("humidifi", "10000", staleBuy, { snapshot_id: "sweep-old" }),
      pair("binance", "10000", liveBuy, { snapshot_id: "live-now" }),
    ];
    // Client must not assume one snapshot_id per asset.
    expect(new Set(pairs.map((p) => p.snapshot_id)).size).toBe(2);
    const picks = bestVenuePerTier(pairs, { side: "buy" });
    expect(picks[0]).toMatchObject({
      venue: "binance",
      valueBps: 18,
      empty: false,
    });
  });

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

describe("formatSnapshotSummary", () => {
  it("builds point-in-time prose from best eligible venues", () => {
    const pairs = [
      pair(
        "humidifi",
        "10000",
        quote({
          venue: "humidifi",
          status: "ok",
          total_cost_bps: "2.1",
          notional_usd: "10000",
        }),
      ),
      pair(
        "binance",
        "10000",
        quote({
          venue: "binance",
          status: "ok",
          total_cost_bps: "8",
          notional_usd: "10000",
        }),
      ),
      pair(
        "binance",
        "1000000",
        quote({
          venue: "binance",
          status: "ok",
          total_cost_bps: "4.4",
          notional_usd: "1000000",
          instrument_type: "perp",
        }),
      ),
      pair(
        "humidifi",
        "1000000",
        quote({
          venue: "humidifi",
          status: "ok",
          total_cost_bps: "12",
          notional_usd: "1000000",
        }),
      ),
    ];
    const text = formatSnapshotSummary(pairs, {
      asset: "BTC",
      side: "buy",
      venueLabels: {
        humidifi: "HumidiFi",
        binance: "Binance perp",
      },
    });
    expect(text).toBe(
      "At $10k, HumidiFi has the lowest total cost to buy BTC (2.1 bps); at $1M, Binance perp (4.4 bps).",
    );
  });

  it("mentions sell / round-trip side in the first clause", () => {
    const buy = quote({
      venue: "binance",
      status: "ok",
      side: "buy",
      total_cost_bps: "9",
    });
    const sell = quote({
      venue: "binance",
      status: "ok",
      side: "sell",
      total_cost_bps: "11",
    });
    const pairs = [
      pair("binance", "1000", buy, {
        sell,
        round_trip_total_cost_bps: "20",
      }),
    ];
    expect(
      formatSnapshotSummary(pairs, {
        asset: "BTC",
        side: "sell",
        venueLabels: { binance: "Binance spot" },
      }),
    ).toContain("to sell BTC");
    expect(
      formatSnapshotSummary(pairs, {
        asset: "BTC",
        side: "round_trip",
        venueLabels: { binance: "Binance spot" },
      }),
    ).toContain("to round-trip BTC");
  });

  it("never names non-ok or gas_unknown venues (WHI-799 §5.2)", () => {
    const pairs = [
      pair(
        "uniswap_eth",
        "1000",
        quote({
          venue: "uniswap_eth",
          status: "ok",
          total_cost_bps: null,
          spread_bps: "0.5",
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
        "hyperliquid",
        "1000",
        quote({ venue: "hyperliquid", status: "insufficient_liquidity" }),
      ),
      pair(
        "humidifi",
        "1000",
        quote({ venue: "humidifi", status: "no_quote" }),
      ),
      pair(
        "bybit",
        "1000",
        quote({ venue: "bybit", status: "error", error_code: "timeout" }),
      ),
      pair(
        "binance",
        "1000",
        quote({ venue: "binance", status: "ok", total_cost_bps: "15" }),
      ),
    ];
    const text = formatSnapshotSummary(pairs, {
      asset: "ETH",
      venueLabels: {
        uniswap_eth: "Uniswap",
        hyperliquid: "Hyperliquid",
        humidifi: "HumidiFi",
        bybit: "Bybit",
        binance: "Binance spot",
      },
    });
    expect(text).toContain("Binance spot");
    expect(text).toContain("15.0 bps");
    expect(text).not.toMatch(/Uniswap|Hyperliquid|HumidiFi|Bybit/);
  });

  it("returns empty string when no eligible picks", () => {
    const pairs = [
      pair(
        "humidifi",
        "1000",
        quote({ venue: "humidifi", status: "no_quote" }),
      ),
    ];
    expect(formatSnapshotSummary(pairs, { asset: "SOL" })).toBe("");
  });

  it("names the selected size explicitly for a single-tier view (WHI-841)", () => {
    // One tier of data (what the size selector actually fetches).
    const pairs = [
      pair(
        "humidifi",
        "10000",
        quote({
          venue: "humidifi",
          status: "ok",
          total_cost_bps: "2.1",
          notional_usd: "10000",
        }),
      ),
      pair(
        "binance",
        "10000",
        quote({
          venue: "binance",
          status: "ok",
          total_cost_bps: "8",
          notional_usd: "10000",
        }),
      ),
      // Ineligible rows must never win (WHI-799 §5.2).
      pair(
        "uniswap_eth",
        "10000",
        quote({
          venue: "uniswap_eth",
          status: "ok",
          total_cost_bps: null,
          spread_bps: "0.1",
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
        "bybit",
        "10000",
        quote({ venue: "bybit", status: "error", error_code: "timeout" }),
      ),
    ];
    const text = formatSnapshotSummary(pairs, {
      asset: "BTC",
      side: "buy",
      venueLabels: {
        humidifi: "HumidiFi",
        binance: "Binance spot",
        uniswap_eth: "Uniswap",
        bybit: "Bybit",
      },
    });
    // Size is explicit so the number is never read as size-independent.
    expect(text).toBe(
      "At $10k, HumidiFi has the lowest total cost to buy BTC (2.1 bps).",
    );
    expect(text).not.toMatch(/Uniswap|Bybit|Binance spot/);
  });
});
