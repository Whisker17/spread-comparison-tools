// @vitest-environment jsdom

/**
 * AC5: amount keystrokes are debounced before POST /simulate fires.
 * Select changes are not covered here — they bypass debounce by design.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useSimulate } from "@/hooks/useSimulate";
import type { SimulateResponse } from "@/lib/api";

const { postSimulateMock } = vi.hoisted(() => ({
  postSimulateMock: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    postSimulate: postSimulateMock,
  };
});

const META = { stables: ["USDC"], assets: ["SOL", "BTC"] };

function emptyResponse(amount: string): SimulateResponse {
  return {
    snapshot_id: "s",
    sell_asset: "SOL",
    buy_asset: "USDC",
    amount,
    asset: "SOL",
    side: "sell",
    notional_usd: "150",
    mid: {
      snapshot_id: "s",
      asset: "SOL",
      mid: "150",
      mid_source: "binance_usdm_index",
      timestamp: "2026-08-03T12:00:00Z",
    },
    rows: [],
  };
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  postSimulateMock.mockReset();
  postSimulateMock.mockImplementation(async (body: { amount: string }) =>
    emptyResponse(String(body.amount)),
  );
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useSimulate debounce wiring (AC5)", () => {
  it("collapses rapid amount keystrokes into one POST after the delay", async () => {
    const { rerender } = renderHook(
      ({ amount }) =>
        useSimulate({
          sellAsset: "SOL",
          buyAsset: "USDC",
          amount,
          pairMeta: META,
          debounceMs: 400,
        }),
      {
        wrapper,
        initialProps: { amount: "1" },
      },
    );

    // Initial amount settles.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });
    await waitFor(() => expect(postSimulateMock).toHaveBeenCalled());
    const afterFirst = postSimulateMock.mock.calls.length;

    // Three valid keystrokes within the debounce window.
    rerender({ amount: "12" });
    rerender({ amount: "123" });
    rerender({ amount: "1234" });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(399);
    });
    // Still only the first settled request.
    expect(postSimulateMock.mock.calls.length).toBe(afterFirst);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    await waitFor(() => {
      expect(postSimulateMock.mock.calls.length).toBeGreaterThan(afterFirst);
    });
    const last = postSimulateMock.mock.calls.at(-1)?.[0] as { amount: string };
    expect(last.amount).toBe("1234");
    // Exactly one additional POST for the debounced final amount.
    expect(postSimulateMock.mock.calls.length).toBe(afterFirst + 1);
  });
});
