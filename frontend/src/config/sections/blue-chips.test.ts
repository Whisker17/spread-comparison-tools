import { describe, expect, it } from "vitest";

import {
  BLUE_CHIP_VENUES,
  blueChipsSection,
  buildVenueLabels,
  EVM_AMM_VENUES,
  hiddenVenuesForAsset,
  ON_CHAIN_VENUE_CLASSES,
  REPRESENTATIONS,
  BLUE_CHIP_VENUE_META,
  TESSERA_EVM_VENUES,
  venuesForAsset,
} from "@/config/sections/blue-chips";

describe("blue-chips section config (WHI-809)", () => {
  it("covers exactly BTC, ETH, SOL", () => {
    expect(blueChipsSection.assets).toEqual(["BTC", "ETH", "SOL"]);
  });

  it("hides EVM AMM and Tessera EVM for SOL; hides Tessera BSC for ETH", () => {
    const solHidden = hiddenVenuesForAsset(blueChipsSection, "SOL");
    expect(solHidden).toEqual(
      expect.arrayContaining([...EVM_AMM_VENUES, ...TESSERA_EVM_VENUES]),
    );
    expect(hiddenVenuesForAsset(blueChipsSection, "BTC")).toEqual([]);
    expect(hiddenVenuesForAsset(blueChipsSection, "ETH")).toEqual([
      "tessera_bsc",
    ]);

    const solVenues = venuesForAsset(blueChipsSection, "SOL");
    for (const v of [...EVM_AMM_VENUES, ...TESSERA_EVM_VENUES]) {
      expect(solVenues).not.toContain(v);
    }
    expect(venuesForAsset(blueChipsSection, "BTC")).toEqual([
      ...BLUE_CHIP_VENUES,
    ]);
    expect(venuesForAsset(blueChipsSection, "ETH")).not.toContain(
      "tessera_bsc",
    );
  });

  it("labels on-chain rows with wrapper representation, never bare logical", () => {
    const btc = buildVenueLabels("BTC", [
      "uniswap_eth",
      "humidifi",
      "pancakeswap_bsc",
      "binance",
      "hyperliquid",
    ]);
    expect(btc.uniswap_eth).toContain("WBTC");
    expect(btc.humidifi).toContain("cbBTC");
    expect(btc.pancakeswap_bsc).toContain("BTCB");
    expect(btc.binance).toMatch(/spot/i);
    expect(btc.hyperliquid).toMatch(/perp/i);
    expect(btc.uniswap_eth).not.toBe("BTC");
    expect(btc.humidifi).not.toBe("BTC");

    const eth = buildVenueLabels("ETH", [
      "humidifi",
      "uniswap_eth",
      "pancakeswap_bsc",
    ]);
    expect(eth.humidifi).toContain("Wormhole WETH");
    expect(eth.uniswap_eth).toContain("WETH");
    expect(eth.pancakeswap_bsc).toContain("BSC ETH");
    // Must not render as bare logical ETH for on-chain wrappers.
    expect(eth.pancakeswap_bsc.split(" · ")).not.toContain("ETH");
  });

  it("annotates quote currency correctly (HL/Lighter USDC)", () => {
    const labels = buildVenueLabels("ETH", [
      "humidifi",
      "binance",
      "hyperliquid",
      "lighter",
      "apex",
    ]);
    expect(labels.humidifi).toMatch(/USDC/);
    expect(labels.binance).toMatch(/USDT/);
    expect(labels.hyperliquid).toMatch(/USDC/);
    expect(labels.lighter).toMatch(/USDC/);
    expect(labels.apex).toMatch(/USDT/);
  });

  it("includes Tessera Base/BSC in BTC venue set for prop coverage", () => {
    const btc = venuesForAsset(blueChipsSection, "BTC");
    expect(btc).toContain("tessera_base");
    expect(btc).toContain("tessera_bsc");
    expect(REPRESENTATIONS.BTC.tessera_base).toBe("cbBTC");
    expect(REPRESENTATIONS.BTC.tessera_bsc).toBe("BTCB");
  });

  it("has a representation for every visible on-chain venue×asset", () => {
    for (const asset of blueChipsSection.assets) {
      const venues = venuesForAsset(blueChipsSection, asset);
      for (const slug of venues) {
        const cls = BLUE_CHIP_VENUE_META[slug]?.venueClass;
        if (!cls || !ON_CHAIN_VENUE_CLASSES.has(cls)) continue;
        const rep = REPRESENTATIONS[asset as "BTC" | "ETH" | "SOL"]?.[slug];
        expect(
          rep,
          `missing representation for ${asset} @ ${slug}`,
        ).toBeTruthy();
        // On-chain representation must not be the bare logical ticker alone.
        expect(rep).not.toBe(asset);
      }
    }
  });

  it("defaults poll interval to 30s on the section config", () => {
    expect(blueChipsSection.pollIntervalMs).toBe(30_000);
  });
});
