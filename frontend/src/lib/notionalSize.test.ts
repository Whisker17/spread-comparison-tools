import { describe, expect, it } from "vitest";

import { NOTIONAL_TIERS_USD } from "@/config/notionals";
import {
  notionalsForSizeView,
  resolveNotionalSize,
} from "@/lib/notionalSize";

describe("resolveNotionalSize", () => {
  const allowed = NOTIONAL_TIERS_USD;
  const defaultNotional = "1000";

  it("accepts a valid tier param", () => {
    expect(resolveNotionalSize("10000", allowed, defaultNotional)).toBe(
      "10000",
    );
    expect(resolveNotionalSize("100", allowed, defaultNotional)).toBe("100");
    expect(resolveNotionalSize("1000000", allowed, defaultNotional)).toBe(
      "1000000",
    );
  });

  it("rejects legacy all and unknown values, falling back to default", () => {
    // WHI-864: multi-column all is no longer a valid size view.
    expect(resolveNotionalSize("all", allowed, defaultNotional)).toBe(
      defaultNotional,
    );
    expect(resolveNotionalSize(null, allowed, defaultNotional)).toBe("1000");
    expect(resolveNotionalSize(undefined, allowed, defaultNotional)).toBe(
      "1000",
    );
    expect(resolveNotionalSize("", allowed, defaultNotional)).toBe("1000");
    expect(resolveNotionalSize("999", allowed, defaultNotional)).toBe("1000");
    expect(resolveNotionalSize("abc", allowed, defaultNotional)).toBe("1000");
    expect(resolveNotionalSize("1e3", allowed, defaultNotional)).toBe("1000");
  });

  it("falls back to first allowed when default is invalid", () => {
    expect(resolveNotionalSize(null, allowed, "all")).toBe(allowed[0]);
  });
});

describe("notionalsForSizeView", () => {
  const tiers = NOTIONAL_TIERS_USD;

  it("returns a single focus tier", () => {
    expect(notionalsForSizeView("10000", tiers)).toEqual(["10000"]);
    expect(notionalsForSizeView("1000", tiers)).toEqual(["1000"]);
  });

  it("falls back to first tier for unknown sizes (including legacy all)", () => {
    expect(notionalsForSizeView("all", tiers)).toEqual([tiers[0]]);
    expect(notionalsForSizeView("999", tiers)).toEqual([tiers[0]]);
  });
});
