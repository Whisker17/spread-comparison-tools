import { describe, expect, it } from "vitest";

import {
  BLUE_CHIP_VENUES,
  blueChipsSection,
  buildVenueLabels,
  EVM_AMM_VENUES,
  hiddenVenuesForAsset,
  REPRESENTATIONS,
  venuesForAsset,
} from "@/config/sections/blue-chips";

describe("blue-chips section config (WHI-809)", () => {
  it("covers exactly BTC, ETH, SOL", () => {
    expect(blueChipsSection.assets).toEqual(["BTC", "ETH", "SOL"]);
  });

  it("hides EVM AMM venues only for SOL", () => {
    expect(hiddenVenuesForAsset(blueChipsSection, "SOL")).toEqual(
      expect.arrayContaining([...EVM_AMM_VENUES]),
    );
    expect(hiddenVenuesForAsset(blueChipsSection, "BTC")).toEqual([]);
    expect(hiddenVenuesForAsset(blueChipsSection, "ETH")).toEqual([]);

    const solVenues = venuesForAsset(blueChipsSection, "SOL");
    for (const v of EVM_AMM_VENUES) {
      expect(solVenues).not.toContain(v);
    }
    expect(venuesForAsset(blueChipsSection, "BTC")).toEqual([
      ...BLUE_CHIP_VENUES,
    ]);
  });

  it("labels on-chain rows with wrapper representation, never bare BTC", () => {
    const labels = buildVenueLabels("BTC", [
      "uniswap_eth",
      "humidifi",
      "pancakeswap_bsc",
      "binance",
      "hyperliquid",
    ]);
    expect(labels.uniswap_eth).toContain("WBTC");
    expect(labels.humidifi).toContain("cbBTC");
    expect(labels.pancakeswap_bsc).toContain("BTCB");
    // CEX/perp show instrument type, not bare logical alone as the only tag.
    expect(labels.binance).toMatch(/spot|perp/i);
    expect(labels.hyperliquid).toMatch(/perp/i);
    // Must not render as just "BTC" for wrappers.
    expect(labels.uniswap_eth).not.toBe("BTC");
    expect(labels.humidifi).not.toBe("BTC");
  });

  it("annotates quote currency on venue labels", () => {
    const labels = buildVenueLabels("ETH", ["humidifi", "binance", "hyperliquid"]);
    expect(labels.humidifi).toMatch(/USDC/);
    expect(labels.binance).toMatch(/USDT/);
    expect(labels.hyperliquid).toMatch(/USDT/);
  });

  it("includes Tessera Base/BSC in BTC venue set for prop coverage", () => {
    const btc = venuesForAsset(blueChipsSection, "BTC");
    expect(btc).toContain("tessera_base");
    expect(btc).toContain("tessera_bsc");
    expect(REPRESENTATIONS.BTC.tessera_base).toBe("cbBTC");
    expect(REPRESENTATIONS.BTC.tessera_bsc).toBe("BTCB");
  });

  it("defaults poll interval to 30s", () => {
    expect(blueChipsSection.pollIntervalMs).toBe(30_000);
  });
});
