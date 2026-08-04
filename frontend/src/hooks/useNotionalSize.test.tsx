// @vitest-environment jsdom

/**
 * URL round-trip for the size selector (WHI-841).
 * Pure resolve rules are covered in lib/notionalSize.test.ts; this checks the
 * hook writes `?size=` and re-reads it.
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SizeSelector } from "@/components/SizeSelector";
import { NOTIONAL_TIERS_USD } from "@/config/notionals";
import { useNotionalSize } from "@/hooks/useNotionalSize";
import { SIZE_QUERY_PARAM } from "@/lib/notionalSize";

const { replaceMock, searchParamsState } = vi.hoisted(() => ({
  replaceMock: vi.fn(),
  searchParamsState: { current: new URLSearchParams() },
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => searchParamsState.current,
  useRouter: () => ({ replace: replaceMock }),
  usePathname: () => "/blue-chips",
}));

function Harness({
  defaultNotional = "1000",
  allowed = NOTIONAL_TIERS_USD as readonly string[],
}: {
  defaultNotional?: string;
  allowed?: readonly string[];
}) {
  const { notional, setNotional } = useNotionalSize({
    allowed,
    defaultNotional,
  });
  return (
    <div>
      <span data-testid="resolved">{notional}</span>
      <SizeSelector
        tiers={allowed}
        value={notional}
        onChange={setNotional}
      />
    </div>
  );
}

beforeEach(() => {
  replaceMock.mockReset();
  searchParamsState.current = new URLSearchParams();
});

afterEach(cleanup);

describe("useNotionalSize + SizeSelector URL round-trip (WHI-841)", () => {
  it("falls back to the config default when ?size= is absent", () => {
    render(<Harness defaultNotional="1000" />);
    expect(screen.getByTestId("resolved").textContent).toBe("1000");
    expect(
      screen.getByTestId("size-option-1000").getAttribute("aria-pressed"),
    ).toBe("true");
  });

  it("restores a valid size from the URL", () => {
    searchParamsState.current = new URLSearchParams("size=10000");
    render(<Harness />);
    expect(screen.getByTestId("resolved").textContent).toBe("10000");
    expect(
      screen.getByTestId("size-option-10000").getAttribute("aria-pressed"),
    ).toBe("true");
  });

  it("falls back to the config default when ?size= is invalid", () => {
    searchParamsState.current = new URLSearchParams("size=not-a-tier");
    render(<Harness defaultNotional="1000" />);
    expect(screen.getByTestId("resolved").textContent).toBe("1000");
  });

  it("writes ?size= when the user selects a tier", () => {
    render(<Harness />);
    fireEvent.click(screen.getByTestId("size-option-100000"));
    expect(replaceMock).toHaveBeenCalledWith(
      `/blue-chips?${SIZE_QUERY_PARAM}=100000`,
      { scroll: false },
    );
  });

  it("preserves other query params when updating size", () => {
    searchParamsState.current = new URLSearchParams("foo=bar&size=1000");
    render(<Harness />);
    fireEvent.click(screen.getByTestId("size-option-100"));
    const url = replaceMock.mock.calls[0]?.[0] as string;
    expect(url).toContain("foo=bar");
    expect(url).toContain(`${SIZE_QUERY_PARAM}=100`);
  });
});
