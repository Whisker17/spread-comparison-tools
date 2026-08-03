import { describe, expect, it } from "vitest";

import {
  constrainSimulateSelection,
  defaultSimulatePair,
  isTradeableStable,
  isValidSimulateAmount,
  isValidSimulatePair,
  selectorOptionsFor,
  swapSimulatePair,
} from "@/lib/simulatePairs";

const META = {
  stables: ["USDC", "USDT"],
  assets: ["BTC", "ETH", "SOL", "WIF"],
} as const;

describe("isValidSimulatePair", () => {
  it("accepts stable × asset either direction", () => {
    expect(isValidSimulatePair("SOL", "USDC", META)).toBe(true);
    expect(isValidSimulatePair("USDC", "SOL", META)).toBe(true);
    expect(isValidSimulatePair("USDT", "BTC", META)).toBe(true);
  });

  it("rejects two stables, two assets, same leg, or unknown symbols", () => {
    expect(isValidSimulatePair("USDC", "USDT", META)).toBe(false);
    expect(isValidSimulatePair("SOL", "BTC", META)).toBe(false);
    expect(isValidSimulatePair("SOL", "SOL", META)).toBe(false);
    expect(isValidSimulatePair("NOTREAL", "USDC", META)).toBe(false);
    expect(isValidSimulatePair("SOL", "FAKE", META)).toBe(false);
  });

  it("is case-insensitive", () => {
    expect(isValidSimulatePair("sol", "usdc", META)).toBe(true);
    expect(isTradeableStable("usdc", META)).toBe(true);
  });
});

describe("defaultSimulatePair", () => {
  it("prefers SOL→first stable when SOL is catalogued", () => {
    expect(defaultSimulatePair(META)).toEqual({ sell: "SOL", buy: "USDC" });
  });

  it("falls back to first asset when SOL is absent", () => {
    expect(
      defaultSimulatePair({ stables: ["USDT"], assets: ["BTC", "ETH"] }),
    ).toEqual({ sell: "BTC", buy: "USDT" });
  });

  it("returns empty when either list is empty", () => {
    expect(defaultSimulatePair({ stables: [], assets: ["SOL"] })).toEqual({
      sell: "",
      buy: "",
    });
  });
});

describe("constrainSimulateSelection", () => {
  it("forces the other leg to a stable when sell becomes a non-stable", () => {
    const next = constrainSimulateSelection(
      { sell: "USDC", buy: "SOL" },
      "sell",
      "BTC",
      META,
    );
    expect(next).toEqual({ sell: "BTC", buy: "USDC" });
    expect(isValidSimulatePair(next.sell, next.buy, META)).toBe(true);
  });

  it("forces the other leg to an asset when sell becomes a stable", () => {
    const next = constrainSimulateSelection(
      { sell: "SOL", buy: "USDC" },
      "sell",
      "USDT",
      META,
    );
    expect(next.sell).toBe("USDT");
    expect(META.assets.map((a) => a)).toContain(next.buy);
    expect(isValidSimulatePair(next.sell, next.buy, META)).toBe(true);
  });

  it("keeps a still-valid other leg when possible", () => {
    const next = constrainSimulateSelection(
      { sell: "SOL", buy: "USDT" },
      "sell",
      "ETH",
      META,
    );
    expect(next).toEqual({ sell: "ETH", buy: "USDT" });
  });

  it("never yields two stables or two non-stables after a buy change", () => {
    const toAsset = constrainSimulateSelection(
      { sell: "SOL", buy: "USDC" },
      "buy",
      "BTC",
      META,
    );
    expect(isValidSimulatePair(toAsset.sell, toAsset.buy, META)).toBe(true);
    expect(isTradeableStable(toAsset.sell, META)).toBe(true);

    const toStable = constrainSimulateSelection(
      { sell: "USDC", buy: "SOL" },
      "buy",
      "USDT",
      META,
    );
    expect(isValidSimulatePair(toStable.sell, toStable.buy, META)).toBe(true);
  });
});

describe("selectorOptionsFor", () => {
  it("offers only assets when the other leg is a stable", () => {
    expect(selectorOptionsFor("USDC", META)).toEqual([
      "BTC",
      "ETH",
      "SOL",
      "WIF",
    ]);
  });

  it("offers only stables when the other leg is an asset", () => {
    expect(selectorOptionsFor("SOL", META)).toEqual(["USDC", "USDT"]);
  });
});

describe("swapSimulatePair / amount", () => {
  it("swaps legs", () => {
    expect(swapSimulatePair({ sell: "SOL", buy: "USDC" })).toEqual({
      sell: "USDC",
      buy: "SOL",
    });
  });

  it("validates positive free-form amounts", () => {
    expect(isValidSimulateAmount("1")).toBe(true);
    expect(isValidSimulateAmount("0.5")).toBe(true);
    expect(isValidSimulateAmount("0")).toBe(false);
    expect(isValidSimulateAmount("-1")).toBe(false);
    expect(isValidSimulateAmount("")).toBe(false);
    expect(isValidSimulateAmount("abc")).toBe(false);
  });
});
