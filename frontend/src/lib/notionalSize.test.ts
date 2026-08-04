import { describe, expect, it } from "vitest";

import { NOTIONAL_TIERS_USD } from "@/config/notionals";
import { resolveNotionalSize } from "@/lib/notionalSize";

describe("resolveNotionalSize (WHI-841)", () => {
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
