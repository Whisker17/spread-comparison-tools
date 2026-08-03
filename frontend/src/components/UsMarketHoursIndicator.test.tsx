// @vitest-environment jsdom

/**
 * Badge rendering for the static NYSE-session annotation (WHI-810).
 * Session/holiday logic itself is covered by `lib/usMarketHours.test.ts`.
 */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { UsMarketHoursIndicator } from "@/components/UsMarketHoursIndicator";

afterEach(cleanup);

describe("UsMarketHoursIndicator (WHI-810)", () => {
  it("renders an open badge during the regular session", () => {
    // Mon 2026-08-03 15:00 UTC = 11:00 ET.
    render(<UsMarketHoursIndicator now={new Date("2026-08-03T15:00:00Z")} />);

    const badge = screen.getByTestId("us-market-hours");
    expect(badge.textContent).toBe("US market open");
    expect(badge.getAttribute("data-open")).toBe("true");
    // Tooltip must keep saying tokenized stocks trade around the clock.
    expect(badge.getAttribute("title")).toContain("24/7");
  });

  it("renders a closed badge after the close", () => {
    // Mon 2026-08-03 21:00 UTC = 17:00 ET.
    render(<UsMarketHoursIndicator now={new Date("2026-08-03T21:00:00Z")} />);

    const badge = screen.getByTestId("us-market-hours");
    expect(badge.textContent).toBe("US market closed");
    expect(badge.getAttribute("data-open")).toBe("false");
    expect(badge.getAttribute("title")).toMatch(/24\/7/);
  });

  it("renders closed on a holiday inside session hours", () => {
    // Thanksgiving Thu 2026-11-26, 15:00 UTC = 10:00 ET.
    render(<UsMarketHoursIndicator now={new Date("2026-11-26T15:00:00Z")} />);

    const badge = screen.getByTestId("us-market-hours");
    expect(badge.getAttribute("data-open")).toBe("false");
    expect(badge.textContent).toBe("US market closed");
  });
});
