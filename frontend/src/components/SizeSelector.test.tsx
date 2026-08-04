// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SizeSelector } from "@/components/SizeSelector";
import { NOTIONAL_TIERS_USD } from "@/config/notionals";

afterEach(cleanup);

describe("SizeSelector (WHI-841)", () => {
  it("renders one button per tier from the props list (not a hardcoded set)", () => {
    render(
      <SizeSelector
        tiers={NOTIONAL_TIERS_USD}
        value="1000"
        onChange={() => {}}
      />,
    );

    for (const tier of NOTIONAL_TIERS_USD) {
      expect(screen.getByTestId(`size-option-${tier}`)).toBeTruthy();
    }
    // All five WHI-799 §4.1 tiers including $1M.
    expect(screen.getByTestId("size-option-1000000").textContent).toBe("$1M");
  });

  it("adds a sixth button when a sixth tier is passed — no component edit", () => {
    const tiers = [...NOTIONAL_TIERS_USD, "5000000"] as const;
    render(
      <SizeSelector tiers={tiers} value="1000" onChange={() => {}} />,
    );

    expect(screen.getByTestId("size-option-5000000").textContent).toBe("$5M");
    expect(
      screen.getByTestId("size-selector").querySelectorAll("button"),
    ).toHaveLength(6);
  });

  it("marks the selected tier as pressed and calls onChange", () => {
    const onChange = vi.fn();
    render(
      <SizeSelector
        tiers={NOTIONAL_TIERS_USD}
        value="1000"
        onChange={onChange}
      />,
    );

    expect(
      screen.getByTestId("size-option-1000").getAttribute("aria-pressed"),
    ).toBe("true");
    expect(
      screen.getByTestId("size-option-10000").getAttribute("aria-pressed"),
    ).toBe("false");

    fireEvent.click(screen.getByTestId("size-option-10000"));
    expect(onChange).toHaveBeenCalledWith("10000");
  });
});
