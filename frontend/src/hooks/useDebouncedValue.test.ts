// @vitest-environment jsdom

import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useDebouncedValue } from "@/hooks/useDebouncedValue";

describe("useDebouncedValue", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not update until the delay elapses (no per-keystroke fire)", () => {
    const { result, rerender } = renderHook(
      ({ value }) => useDebouncedValue(value, 400),
      { initialProps: { value: "1" } },
    );
    expect(result.current).toBe("1");

    rerender({ value: "12" });
    rerender({ value: "123" });
    // Still the previous value before the timer fires.
    expect(result.current).toBe("1");

    act(() => {
      vi.advanceTimersByTime(399);
    });
    expect(result.current).toBe("1");

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current).toBe("123");
  });
});
