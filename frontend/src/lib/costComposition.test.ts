import { describe, expect, it } from "vitest";

import type { Quote, SizeQuotePair } from "@/lib/api";
import {
  costCompositionFromQuote,
  formatFeesConclusion,
  rankCostComposition,
  sumKnownSegments,
} from "@/lib/costComposition";

function quote(
  overrides: Partial<Quote> & Pick<Quote, "venue" | "status">,
): Quote {
  const gasUnknown = overrides.fee_breakdown?.gas_unknown ?? false;
  const embedded = overrides.fee_breakdown?.embedded_in_price ?? false;
  return {
    snapshot_id: "s1",
    asset: "BTC",
    instrument_type: embedded ? "prop_amm" : "spot",
    side: "buy",
    notional_usd: "10000",
    mid: "100000",
    mid_source: "binance_usdm_index",
    mid_timestamp: "2026-08-03T12:00:00Z",
    mid_stale: false,
    timestamp: "2026-08-03T12:00:01Z",
    fee_breakdown: {
      embedded_in_price: embedded,
      platform_fee_bps: "0",
      gas_unknown: gasUnknown,
      explicit_fee_bps: gasUnknown ? null : embedded ? "0" : "10",
      trading_fee_bps: gasUnknown ? null : embedded ? null : "10",
      gas_bps: gasUnknown ? null : "0",
    },
    effective_price: overrides.status === "ok" ? "100100" : null,
    spread_bps: overrides.status === "ok" ? "4.4" : null,
    total_cost_bps:
      overrides.status === "ok" && !gasUnknown
        ? embedded
          ? "4.4"
          : "14.4"
        : null,
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
    instrument_type: buy?.instrument_type ?? "spot",
    notional_usd: "10000",
    buy,
    sell: null,
    ...extras,
  };
}

describe("costCompositionFromQuote", () => {
  it("segments sum to total_cost_bps for explicit-fee CEX (WHI-799 §5.2)", () => {
    const q = quote({
      venue: "binance",
      status: "ok",
      spread_bps: "4.4",
      total_cost_bps: "14.4",
      fee_breakdown: {
        embedded_in_price: false,
        trading_fee_bps: "10",
        platform_fee_bps: "0",
        gas_bps: "0",
        gas_unknown: false,
        explicit_fee_bps: "10",
      },
    });
    const c = costCompositionFromQuote(q);
    expect(c.rankable).toBe(true);
    expect(c.feeEmbeddedInPrice).toBe(false);
    expect(c.segments).toEqual([
      { id: "spread_bps", bps: 4.4 },
      { id: "trading_component_bps", bps: 10 },
      { id: "platform_fee_bps", bps: 0 },
      { id: "gas_bps", bps: 0 },
    ]);
    expect(sumKnownSegments(c.segments)).toBe(14.4);
    expect(c.totalCostBps).toBe(14.4);
    expect(sumKnownSegments(c.segments)).toBe(c.totalCostBps);
  });

  it("embedded-fee venue has zero trading segment (fee lives in spread)", () => {
    const q = quote({
      venue: "humidifi",
      status: "ok",
      instrument_type: "prop_amm",
      spread_bps: "4.4",
      total_cost_bps: "4.4",
      fee_breakdown: {
        embedded_in_price: true,
        trading_fee_bps: null,
        platform_fee_bps: "0",
        gas_bps: "0",
        gas_unknown: false,
        explicit_fee_bps: "0",
      },
    });
    const c = costCompositionFromQuote(q);
    expect(c.feeEmbeddedInPrice).toBe(true);
    expect(c.segments.find((s) => s.id === "trading_component_bps")?.bps).toBe(
      0,
    );
    expect(sumKnownSegments(c.segments)).toBe(4.4);
    expect(sumKnownSegments(c.segments)).toBe(c.totalCostBps);
  });

  it("gas_unknown leaves total null, gas segment null (not 0), not rankable", () => {
    const q = quote({
      venue: "uniswap_eth",
      status: "ok",
      instrument_type: "amm_pool",
      spread_bps: "4.4",
      total_cost_bps: null,
      fee_breakdown: {
        embedded_in_price: true,
        trading_fee_bps: null,
        platform_fee_bps: "0",
        gas_bps: null,
        gas_unknown: true,
        explicit_fee_bps: null,
      },
    });
    const c = costCompositionFromQuote(q);
    expect(c.gasUnknown).toBe(true);
    expect(c.totalCostBps).toBeNull();
    expect(sumKnownSegments(c.segments)).toBeNull();
    expect(c.rankable).toBe(false);
    expect(c.segments.find((s) => s.id === "gas_bps")?.bps).toBeNull();
  });

  it("preserves negative spread (better than mid) in segment identity", () => {
    const q = quote({
      venue: "humidifi",
      status: "ok",
      instrument_type: "prop_amm",
      spread_bps: "-1.5",
      total_cost_bps: "-1.5",
      fee_breakdown: {
        embedded_in_price: true,
        trading_fee_bps: null,
        platform_fee_bps: "0",
        gas_bps: "0",
        gas_unknown: false,
        explicit_fee_bps: "0",
      },
    });
    const c = costCompositionFromQuote(q);
    expect(c.segments.find((s) => s.id === "spread_bps")?.bps).toBe(-1.5);
    expect(sumKnownSegments(c.segments)).toBe(-1.5);
    expect(sumKnownSegments(c.segments)).toBe(c.totalCostBps);
  });
});

describe("rankCostComposition", () => {
  it("sorts rankable rows by ascending total_cost_bps", () => {
    const pairs = [
      pair(
        "binance",
        quote({
          venue: "binance",
          status: "ok",
          total_cost_bps: "14.4",
          fee_breakdown: {
            embedded_in_price: false,
            trading_fee_bps: "10",
            platform_fee_bps: "0",
            gas_bps: "0",
            gas_unknown: false,
            explicit_fee_bps: "10",
          },
        }),
      ),
      pair(
        "humidifi",
        quote({
          venue: "humidifi",
          status: "ok",
          instrument_type: "prop_amm",
          total_cost_bps: "4.4",
          fee_breakdown: {
            embedded_in_price: true,
            trading_fee_bps: null,
            platform_fee_bps: "0",
            gas_bps: "0",
            gas_unknown: false,
            explicit_fee_bps: "0",
          },
        }),
      ),
      pair(
        "bybit",
        quote({
          venue: "bybit",
          status: "ok",
          total_cost_bps: "12.0",
          fee_breakdown: {
            embedded_in_price: false,
            trading_fee_bps: "10",
            platform_fee_bps: "0",
            gas_bps: "0",
            gas_unknown: false,
            explicit_fee_bps: "10",
          },
        }),
      ),
    ];
    const { ranked } = rankCostComposition(pairs);
    expect(ranked.map((r) => r.venue)).toEqual([
      "humidifi",
      "bybit",
      "binance",
    ]);
  });

  it("puts gas_unknown in incomplete group and never ranks it best (WHI-799 §5.2)", () => {
    const pairs = [
      pair(
        "uniswap_eth",
        quote({
          venue: "uniswap_eth",
          status: "ok",
          instrument_type: "amm_pool",
          spread_bps: "1",
          total_cost_bps: null,
          fee_breakdown: {
            embedded_in_price: true,
            trading_fee_bps: null,
            platform_fee_bps: "0",
            gas_bps: null,
            gas_unknown: true,
            explicit_fee_bps: null,
          },
        }),
      ),
      pair(
        "binance",
        quote({
          venue: "binance",
          status: "ok",
          total_cost_bps: "30",
          fee_breakdown: {
            embedded_in_price: false,
            trading_fee_bps: "10",
            platform_fee_bps: "0",
            gas_bps: "0",
            gas_unknown: false,
            explicit_fee_bps: "10",
          },
        }),
      ),
    ];
    const { ranked, incomplete } = rankCostComposition(pairs);
    expect(ranked.map((r) => r.venue)).toEqual(["binance"]);
    expect(ranked[0]?.totalCostBps).toBe(30);
    expect(incomplete.map((r) => r.venue)).toEqual(["uniswap_eth"]);
    expect(incomplete.every((r) => !r.rankable)).toBe(true);
  });

  it("keeps non-ok quotes out of ranked and incomplete", () => {
    const pairs = [
      pair("humidifi", quote({ venue: "humidifi", status: "no_quote" })),
      pair(
        "binance",
        quote({
          venue: "binance",
          status: "ok",
          total_cost_bps: "14.4",
        }),
      ),
    ];
    const { ranked, incomplete, other } = rankCostComposition(pairs);
    expect(ranked.map((r) => r.venue)).toEqual(["binance"]);
    expect(incomplete).toHaveLength(0);
    expect(other.map((r) => r.venue)).toEqual(["humidifi"]);
  });

  it("conclusion uses the same ranked list as the bars (no second rank)", () => {
    const pairs = [
      pair(
        "humidifi",
        quote({
          venue: "humidifi",
          status: "ok",
          instrument_type: "prop_amm",
          total_cost_bps: "2.1",
          fee_breakdown: {
            embedded_in_price: true,
            trading_fee_bps: null,
            platform_fee_bps: "0",
            gas_bps: "0",
            gas_unknown: false,
            explicit_fee_bps: "0",
          },
        }),
      ),
      pair(
        "binance",
        quote({
          venue: "binance",
          status: "ok",
          total_cost_bps: "14.4",
          fee_breakdown: {
            embedded_in_price: false,
            trading_fee_bps: "10",
            platform_fee_bps: "0",
            gas_bps: "0",
            gas_unknown: false,
            explicit_fee_bps: "10",
          },
        }),
      ),
    ];
    const { ranked } = rankCostComposition(pairs, {
      venues: ["binance"],
      venueLabels: { binance: "Binance", humidifi: "HumidiFi" },
    });
    const prose = formatFeesConclusion(ranked, {
      asset: "BTC",
      notionalUsd: "10000",
    });
    expect(prose).toContain("Binance");
    expect(prose).not.toContain("HumidiFi");
  });
});

describe("formatFeesConclusion", () => {
  it("names lowest total and cheapest explicit-fee venue from ranked rows", () => {
    const pairs = [
      pair(
        "humidifi",
        quote({
          venue: "humidifi",
          status: "ok",
          instrument_type: "prop_amm",
          total_cost_bps: "2.1",
          fee_breakdown: {
            embedded_in_price: true,
            trading_fee_bps: null,
            platform_fee_bps: "0",
            gas_bps: "0",
            gas_unknown: false,
            explicit_fee_bps: "0",
          },
        }),
      ),
      pair(
        "binance",
        quote({
          venue: "binance",
          status: "ok",
          total_cost_bps: "14.4",
          fee_breakdown: {
            embedded_in_price: false,
            trading_fee_bps: "10",
            platform_fee_bps: "0",
            gas_bps: "0",
            gas_unknown: false,
            explicit_fee_bps: "10",
          },
        }),
      ),
    ];
    const { ranked } = rankCostComposition(pairs, {
      venueLabels: { humidifi: "HumidiFi", binance: "Binance" },
    });
    const prose = formatFeesConclusion(ranked, {
      asset: "BTC",
      notionalUsd: "10000",
    });
    expect(prose).toBe(
      "For a $10k BTC buy right now, total cost is lowest on HumidiFi (2.10 bps); the cheapest explicit-fee venue is Binance (14.40 bps).",
    );
  });

  it("returns empty when no rankable rows", () => {
    expect(
      formatFeesConclusion([], { asset: "BTC", notionalUsd: "10000" }),
    ).toBe("");
  });
});
