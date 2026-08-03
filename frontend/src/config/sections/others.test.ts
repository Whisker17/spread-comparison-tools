import { describe, expect, it } from "vitest";

import {
  OTHER_P0_ASSETS,
  OTHER_P1_SCALED_ASSETS,
  OTHER_P2_WATCHLIST,
  OTHER_VENUES,
  buildVenueLabels,
  isOrderbookVenue,
  isScaledContractAsset,
  othersSection,
  venueSummaryLabel,
} from "@/config/sections/others";
import { venuesForAsset } from "@/config/sections/helpers";

describe("others section config (WHI-811)", () => {
  it("lists the eight P0 assets then PEPE/BONK as expanded board", () => {
    expect(OTHER_P0_ASSETS).toEqual([
      "DOGE",
      "WIF",
      "XRP",
      "SUI",
      "LINK",
      "AVAX",
      "ADA",
      "BNB",
    ]);
    expect(OTHER_P1_SCALED_ASSETS).toEqual(["PEPE", "BONK"]);
    expect(othersSection.assets).toEqual([
      ...OTHER_P0_ASSETS,
      ...OTHER_P1_SCALED_ASSETS,
    ]);
  });

  it("uses only CEX + three perp DEXes (no prop AMM venues)", () => {
    expect(OTHER_VENUES).toEqual([
      "binance",
      "bybit",
      "hyperliquid",
      "lighter",
      "apex",
    ]);
    expect(othersSection.venues).toEqual([...OTHER_VENUES]);

    const propLike = [
      "humidifi",
      "tessera_solana",
      "tessera_base",
      "tessera_bsc",
      "bisonfi",
      "uniswap_eth",
      "aerodrome_base",
      "pancakeswap_bsc",
    ];
    for (const asset of othersSection.assets) {
      const venues = venuesForAsset(othersSection, asset);
      for (const p of propLike) {
        expect(venues).not.toContain(p);
      }
      expect(venues).toHaveLength(5);
    }
  });

  it("marks PEPE/BONK as scaled-contract assets for venue_symbol notes", () => {
    expect(isScaledContractAsset("PEPE")).toBe(true);
    expect(isScaledContractAsset("bonk")).toBe(true);
    expect(isScaledContractAsset("DOGE")).toBe(false);
  });

  it("defines P2 watchlist with coverage caveats, default-collapsed in UI", () => {
    expect(OTHER_P2_WATCHLIST.map((w) => w.id)).toEqual([
      "JUP",
      "AERO",
      "VIRTUAL",
      "EURC",
    ]);
    for (const row of OTHER_P2_WATCHLIST) {
      expect(row.caveat.length).toBeGreaterThan(10);
    }
    // Watchlist ids are not in the expanded section.assets board.
    for (const row of OTHER_P2_WATCHLIST) {
      expect(othersSection.assets).not.toContain(row.id);
    }
  });

  it("labels CEX as spot and perp DEX as perp with quote currency", () => {
    const labels = buildVenueLabels([...OTHER_VENUES]);
    expect(labels.binance).toMatch(/spot/i);
    expect(labels.binance).toMatch(/USDT/);
    expect(labels.hyperliquid).toMatch(/perp/i);
    expect(labels.hyperliquid).toMatch(/USDC/);
    expect(labels.apex).toMatch(/USDT/);
  });

  it("treats all five venues as orderbook-capable", () => {
    for (const v of OTHER_VENUES) {
      expect(isOrderbookVenue(v)).toBe(true);
    }
  });

  it("defaults poll interval to 30s", () => {
    expect(othersSection.pollIntervalMs).toBe(30_000);
  });

  it("summary labels include instrument type", () => {
    expect(venueSummaryLabel("binance")).toBe("Binance spot");
    expect(venueSummaryLabel("hyperliquid")).toBe("Hyperliquid perp");
  });
});
