import { describe, expect, it } from "vitest";

import { formatBps, formatNotional, parseDecimal } from "@/lib/format";

describe("formatBps", () => {
  it("rounds API 4-dp values to 2-dp display", () => {
    expect(formatBps("14.4000")).toBe("14.40");
    expect(formatBps(4.4)).toBe("4.40");
  });

  it("returns em-dash for nullish", () => {
    expect(formatBps(null)).toBe("—");
    expect(formatBps(undefined)).toBe("—");
  });
});

describe("formatNotional", () => {
  it("uses compact USD labels", () => {
    expect(formatNotional(1000)).toBe("$1k");
    expect(formatNotional("10000")).toBe("$10k");
    expect(formatNotional(1_000_000)).toBe("$1M");
  });

  it("rounds free-form sub-$1k notionals (simulate amount × mid)", () => {
    expect(formatNotional(183.42123456789)).toBe("$183.42");
  });
});

describe("formatDeltaVsBest", () => {
  it("signs trailing (positive absolute) as minus", async () => {
    const { formatDeltaVsBest } = await import("@/lib/format");
    expect(formatDeltaVsBest(0.35, 23.4, "USDC")).toMatch(/Δ −0\.35/);
    expect(formatDeltaVsBest(0.35, 23.4, "USDC")).toMatch(/vs ref/);
    expect(formatDeltaVsBest(-0.35, -23.4, "USDC")).toMatch(/Δ \+0\.35/);
  });
});

describe("parseDecimal", () => {
  it("parses finite strings", () => {
    expect(parseDecimal("12.5")).toBe(12.5);
    expect(parseDecimal("nope")).toBeNull();
  });
});
