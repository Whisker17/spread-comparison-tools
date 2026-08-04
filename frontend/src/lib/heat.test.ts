import { describe, expect, it } from "vitest";

import { heatClass, heatRange } from "@/lib/heat";

describe("heatRange", () => {
  it("ignores nullish and non-finite values", () => {
    expect(heatRange([1, null, undefined, Number.NaN, 5])).toEqual({
      min: 1,
      max: 5,
    });
  });

  it("returns null when no finite values", () => {
    expect(heatRange([null, undefined])).toBeNull();
  });
});

describe("heatClass", () => {
  it("maps best→green and worst→rose within a column range", () => {
    const range = { min: 5, max: 25 };
    expect(heatClass(5, range)).toBe("bg-emerald-500/25");
    expect(heatClass(25, range)).toBe("bg-rose-500/20");
  });

  it("is neutral when range is null (no comparable cells)", () => {
    expect(heatClass(300, null)).toBe("bg-transparent");
  });
});

describe("excessive-impact exclusion (WHI-845)", () => {
  /**
   * SpreadMatrix feeds heatRange only after includeInHeat (status=ok).
   * A 38k bps prop-AMM fill must not enter the range or it flattens the column.
   */
  it("documents that extreme outliers would flatten colour resolution", () => {
    const withOutlier = heatRange([3, 5, 8, 38283]);
    const without = heatRange([3, 5, 8]);
    expect(withOutlier).toEqual({ min: 3, max: 38283 });
    expect(without).toEqual({ min: 3, max: 8 });
    expect(heatClass(3, withOutlier)).toBe(heatClass(8, withOutlier));
    expect(heatClass(3, without)).not.toBe(heatClass(8, without));
  });
});

describe("per-column heat isolation (WHI-838)", () => {
  /**
   * Gas-dominated $100 L1 cell must not flatten $10k colour resolution.
   * Each column builds its own range; a 1500 bps outlier in column A does not
   * push column B's 5–15 bps cluster into a single colour band.
   */
  it("keeps mid-tier colour spread when another column has extreme gas", () => {
    const col100 = heatRange([8, 12, 1500]); // CEX + gas-dominated AMM
    const col10k = heatRange([5.2, 8.1, 12.4]); // normal blue-chip band

    expect(col100).toEqual({ min: 8, max: 1500 });
    expect(col10k).toEqual({ min: 5.2, max: 12.4 });

    // Within $10k, best and worst still get distinct bands.
    expect(heatClass(5.2, col10k)).toBe("bg-emerald-500/25");
    expect(heatClass(12.4, col10k)).toBe("bg-rose-500/20");
    // Mid values in $10k are not crushed toward one colour.
    expect(heatClass(8.1, col10k)).not.toBe(heatClass(5.2, col10k));
    expect(heatClass(8.1, col10k)).not.toBe(heatClass(12.4, col10k));

    // Matrix-wide range (anti-pattern) would crush $10k:
    const matrixWide = heatRange([8, 12, 1500, 5.2, 8.1, 12.4]);
    expect(heatClass(5.2, matrixWide)).toBe(heatClass(12.4, matrixWide));
  });
});
