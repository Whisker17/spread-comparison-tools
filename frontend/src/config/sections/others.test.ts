import { describe, expect, it } from "vitest";

import {
  OTHER_ASSET_GROUPS,
  OTHER_P0_ASSETS,
  OTHER_P1_SCALED_ASSETS,
  OTHER_P2_WATCHLIST,
  OTHER_VENUES,
  buildVenueLabels,
  expandedOtherAssets,
  isOrderbookVenue,
  otherVenuesDisplayList,
  otherVenuesQueryParam,
  othersSection,
  venueSummaryLabel,
} from "@/config/sections/others";
import { venuesForAsset } from "@/config/sections/helpers";

describe("others section config (WHI-811)", () => {
  it("lists the eight P0 assets then PEPE/BONK via OTHER_ASSET_GROUPS SSOT", () => {
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
    expect(othersSection.assets).toEqual(expandedOtherAssets());
    expect(othersSection.assets).toEqual([
      ...OTHER_P0_ASSETS,
      ...OTHER_P1_SCALED_ASSETS,
    ]);
    expect(OTHER_ASSET_GROUPS.flatMap((g) => [...g.assets])).toEqual(
      othersSection.assets,
    );
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
    expect(otherVenuesQueryParam()).toBe(
      "binance,bybit,hyperliquid,lighter,apex",
    );
    expect(otherVenuesDisplayList()).toBe(
      "Binance · Bybit · Hyperliquid · Lighter · ApeX",
    );

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
      expect(venues.join(",")).toBe(otherVenuesQueryParam());
    }
  });

  it("marks P1 group as preferPerp + venue_symbol notes", () => {
    const p1 = OTHER_ASSET_GROUPS.find((g) => g.id === "p1");
    expect(p1?.preferPerp).toBe(true);
    expect(p1?.showVenueSymbolNote).toBe(true);
  });

  it("defines P2 watchlist with caveats outside live board assets", () => {
    expect(OTHER_P2_WATCHLIST.map((w) => w.id)).toEqual([
      "JUP",
      "AERO",
      "VIRTUAL",
      "EURC",
    ]);
    for (const row of OTHER_P2_WATCHLIST) {
      expect(row.caveat.length).toBeGreaterThan(10);
      expect(othersSection.assets).not.toContain(row.id);
    }
  });

  it("labels CEX as spot by default and perp when forced", () => {
    const spot = buildVenueLabels("DOGE", [...OTHER_VENUES]);
    expect(spot.binance).toMatch(/spot/i);
    expect(spot.binance).toMatch(/USDT/);
    expect(spot.hyperliquid).toMatch(/perp/i);
    expect(spot.hyperliquid).toMatch(/USDC/);
    expect(spot.binance.split(" · ")).toHaveLength(3);

    const perp = buildVenueLabels("PEPE", [...OTHER_VENUES], {
      instrument: "perp",
    });
    expect(perp.binance).toMatch(/perp/i);
    expect(perp.hyperliquid).toMatch(/perp/i);
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
    expect(venueSummaryLabel("binance", { instrument: "perp" })).toBe(
      "Binance perp",
    );
    expect(venueSummaryLabel("hyperliquid")).toBe("Hyperliquid perp");
  });
});
