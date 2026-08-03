import { describe, expect, it } from "vitest";

import type { SizeQuotePair } from "@/lib/api";
import {
  formatVenueSymbolNote,
  isNonTrivialVenueSymbol,
  venueSymbolsFromPairs,
} from "@/lib/venue-symbols";

function pair(
  venue: string,
  venue_symbol: string | null | undefined,
): SizeQuotePair {
  return {
    venue,
    notional_usd: "1000",
    buy:
      venue_symbol === undefined
        ? null
        : {
            venue,
            asset: "PEPE",
            side: "buy",
            status: "ok",
            notional_usd: "1000",
            instrument_type: "perp",
            effective_price: "0.00001",
            mid: "0.00001",
            mid_source: "binance",
            mid_timestamp: "2026-08-03T00:00:00Z",
            timestamp: "2026-08-03T00:00:00Z",
            spread_bps: "1",
            total_cost_bps: "2",
            fee_breakdown: {
              trading_fee_bps: "1",
              gas_bps: "0",
              gas_unknown: false,
              explicit_fee_bps: "1",
              embedded_in_price: false,
            },
            venue_symbol,
          },
    sell: null,
    top_of_book: null,
  } as SizeQuotePair;
}

describe("venueSymbolsFromPairs", () => {
  it("collects first non-null venue_symbol per venue within filter", () => {
    const pairs = [
      pair("hyperliquid", "kPEPE"),
      pair("binance", "1000PEPEUSDT"),
      pair("hyperliquid", "ignored-second"),
      pair("lighter", null),
      pair("humidifi", "should-not-appear"),
    ];
    expect(
      venueSymbolsFromPairs(pairs, ["hyperliquid", "binance", "lighter"]),
    ).toEqual({
      hyperliquid: "kPEPE",
      binance: "1000PEPEUSDT",
    });
  });
});

describe("isNonTrivialVenueSymbol", () => {
  it("drops bare and simple USDT labels without parsing multipliers", () => {
    expect(isNonTrivialVenueSymbol("PEPE", "PEPE")).toBe(false);
    expect(isNonTrivialVenueSymbol("PEPE", "PEPEUSDT")).toBe(false);
    expect(isNonTrivialVenueSymbol("PEPE", "PEPE-USDT")).toBe(false);
    expect(isNonTrivialVenueSymbol("PEPE", "kPEPE")).toBe(true);
    expect(isNonTrivialVenueSymbol("PEPE", "1000PEPEUSDT")).toBe(true);
  });
});

describe("formatVenueSymbolNote", () => {
  it("names scaled venue contracts and 1× unit", () => {
    const note = formatVenueSymbolNote(
      "PEPE",
      {
        hyperliquid: "kPEPE",
        binance: "1000PEPEUSDT",
        bybit: "PEPEUSDT",
      },
      {
        hyperliquid: "Hyperliquid",
        binance: "Binance",
        bybit: "Bybit",
      },
    );
    expect(note).toBe(
      "Hyperliquid quotes kPEPE contracts; Binance quotes 1000PEPEUSDT contracts; prices shown normalized to 1× PEPE.",
    );
    expect(note).not.toContain("Bybit");
    expect(note).not.toMatch(/\b1000×\b/);
  });

  it("returns null when only trivial symbols", () => {
    expect(
      formatVenueSymbolNote(
        "PEPE",
        { binance: "PEPEUSDT" },
        { binance: "Binance" },
      ),
    ).toBeNull();
  });
});
