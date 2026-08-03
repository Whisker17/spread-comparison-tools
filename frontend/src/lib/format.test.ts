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
});

describe("parseDecimal", () => {
  it("parses finite strings", () => {
    expect(parseDecimal("12.5")).toBe(12.5);
    expect(parseDecimal("nope")).toBeNull();
  });
});
