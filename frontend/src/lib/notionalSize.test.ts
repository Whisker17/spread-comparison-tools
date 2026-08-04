import { describe, expect, it } from "vitest";

import { NOTIONAL_TIERS_USD } from "@/config/notionals";
import {
  isSizeAll,
  notionalsForSizeView,
  resolveNotionalSize,
  SIZE_ALL,
} from "@/lib/notionalSize";

describe("resolveNotionalSize (WHI-841 / WHI-843)", () => {
  const allowed = [...NOTIONAL_TIERS_USD];
  const defaultNotional = "1000";

  it("returns a valid size param when it is in the allowed set", () => {
    expect(resolveNotionalSize("10000", allowed, defaultNotional)).toBe(
      "10000",
    );
    expect(resolveNotionalSize("100", allowed, defaultNotional)).toBe("100");
    expect(resolveNotionalSize("1000000", allowed, defaultNotional)).toBe(
      "1000000",
    );
  });

  it("accepts the all multi-column sentinel", () => {
    expect(resolveNotionalSize(SIZE_ALL, allowed, defaultNotional)).toBe(
      SIZE_ALL,
    );
    expect(resolveNotionalSize(null, allowed, SIZE_ALL)).toBe(SIZE_ALL);
  });

  it("falls back to the config default when the param is absent", () => {
    expect(resolveNotionalSize(null, allowed, defaultNotional)).toBe("1000");
    expect(resolveNotionalSize(undefined, allowed, defaultNotional)).toBe(
      "1000",
    );
    expect(resolveNotionalSize("", allowed, defaultNotional)).toBe("1000");
  });

  it("falls back to the config default when the param is invalid", () => {
    expect(resolveNotionalSize("999", allowed, defaultNotional)).toBe("1000");
    expect(resolveNotionalSize("abc", allowed, defaultNotional)).toBe("1000");
    expect(resolveNotionalSize("1e3", allowed, defaultNotional)).toBe("1000");
  });

  it("falls back to the first allowed tier when the default is not allowed", () => {
    const subset = ["10000", "100000"] as const;
    expect(resolveNotionalSize(null, subset, "1000")).toBe("10000");
    expect(resolveNotionalSize("100", subset, "1000")).toBe("10000");
  });
});

describe("notionalsForSizeView", () => {
  const tiers = [...NOTIONAL_TIERS_USD];

  it("returns all tiers for all-view", () => {
    expect(notionalsForSizeView(SIZE_ALL, tiers)).toEqual(tiers);
    expect(isSizeAll(SIZE_ALL)).toBe(true);
  });

  it("returns a single focus tier", () => {
    expect(notionalsForSizeView("10000", tiers)).toEqual(["10000"]);
  });
});
