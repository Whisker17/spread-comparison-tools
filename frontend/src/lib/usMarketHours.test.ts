import { describe, expect, it } from "vitest";

import {
  isUsEquityMarketOpen,
  nyCivilParts,
  usMarketHoursStatus,
  US_EQUITY_HOLIDAYS,
} from "@/lib/usMarketHours";

describe("usMarketHours (WHI-810)", () => {
  it("resolves America/New_York civil parts for a known UTC instant", () => {
    // 2026-03-10 14:00 UTC = 10:00 ET (EDT after spring-forward on Mar 8 2026)
    const parts = nyCivilParts(new Date("2026-03-10T14:00:00Z"));
    expect(parts.date).toBe("2026-03-10");
    expect(parts.weekday).toBe(2); // Tuesday
    expect(parts.minutes).toBe(10 * 60);
  });

  it("is open mid-session on a regular weekday", () => {
    // 15:00 UTC = 10:00 ET on 2026-03-10 (Tue)
    expect(isUsEquityMarketOpen(new Date("2026-03-10T15:00:00Z"))).toBe(true);
    expect(usMarketHoursStatus(new Date("2026-03-10T15:00:00Z")).label).toBe(
      "US market open",
    );
  });

  it("is closed before open, after close, on weekend, and on holiday", () => {
    // 13:00 UTC = 09:00 ET — before 09:30
    expect(isUsEquityMarketOpen(new Date("2026-03-10T13:00:00Z"))).toBe(false);
    // 21:00 UTC = 17:00 ET — after 16:00
    expect(isUsEquityMarketOpen(new Date("2026-03-10T21:00:00Z"))).toBe(false);
    // Saturday
    expect(isUsEquityMarketOpen(new Date("2026-03-14T15:00:00Z"))).toBe(false);
    // Thanksgiving 2026-11-26 — 15:00 UTC ≈ 10:00 ET
    expect(US_EQUITY_HOLIDAYS.has("2026-11-26")).toBe(true);
    expect(isUsEquityMarketOpen(new Date("2026-11-26T15:00:00Z"))).toBe(false);
    expect(usMarketHoursStatus(new Date("2026-11-26T15:00:00Z")).label).toBe(
      "US market closed",
    );
  });
});
