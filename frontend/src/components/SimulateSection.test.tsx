// @vitest-environment jsdom

/**
 * `/simulate` acceptance coverage (WHI-815):
 * - ranked rows + delta-vs-best + best flag from backend
 * - skeleton while in flight; error rows in place
 * - selectors constrained by GET /simulate/pairs (no hardcoded stables)
 * - not_supported collapsed section; structured 422 reasons
 * - debounce: no per-keystroke POST
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type { ReactNode } from "react";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import { SimulateSection } from "@/components/SimulateSection";
import { TooltipProvider } from "@/components/ui/tooltip";
import type {
  SimulateResponse,
  SimulateRowResponse,
  VenueResponse,
} from "@/lib/api";
import { ApiError } from "@/lib/api";

const {
  fetchSimulatePairsMock,
  postSimulateMock,
  fetchVenuesMock,
  fetchAssetsMock,
} = vi.hoisted(() => ({
  fetchSimulatePairsMock: vi.fn(),
  postSimulateMock: vi.fn(),
  fetchVenuesMock: vi.fn(),
  fetchAssetsMock: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    fetchSimulatePairs: fetchSimulatePairsMock,
    postSimulate: postSimulateMock,
    fetchVenues: fetchVenuesMock,
    fetchAssets: fetchAssetsMock,
  };
});

// Fast debounce in tests so we don't wait 400ms per assertion.
vi.mock("@/hooks/useSimulate", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/useSimulate")>();
  return {
    ...actual,
    // Re-export useSimulate but force debounceMs=0 via wrapper? Better: mock
    // SIMULATE_DEBOUNCE_MS constant used by the section text only, and pass
    // debounce through by mocking useDebouncedValue to be identity.
    SIMULATE_DEBOUNCE_MS: 0,
  };
});

vi.mock("@/hooks/useDebouncedValue", () => ({
  useDebouncedValue: <T,>(value: T) => value,
}));

const PAIRS = {
  stables: ["USDC", "USDT"],
  assets: ["BTC", "ETH", "SOL", "WIF"],
};

const VENUES: VenueResponse[] = [
  {
    slug: "humidifi",
    display_name: "HumidiFi",
    venue_class: "prop_amm",
    chain: "solana",
    adapter_registered: true,
  },
  {
    slug: "binance",
    display_name: "Binance",
    venue_class: "cex",
    chain: null,
    adapter_registered: true,
  },
  {
    slug: "apex",
    display_name: "ApeX",
    venue_class: "perp_dex",
    chain: null,
    adapter_registered: true,
  },
];

function row(
  partial: Partial<SimulateRowResponse> &
    Pick<SimulateRowResponse, "venue" | "status">,
): SimulateRowResponse {
  return {
    instrument_type: "prop_amm",
    expected_output: null,
    effective_price: null,
    spread_bps: null,
    fee_breakdown: {
      embedded_in_price: true,
      trading_fee_bps: "0",
      platform_fee_bps: "0",
      gas_unknown: false,
      gas_bps: "0.5",
    },
    total_cost_bps: null,
    timestamp: "2026-08-03T12:00:00Z",
    best: false,
    error_code: null,
    error_message: null,
    mid_stale: false, quote_stale: false,
    venue_symbol: null,
    ...partial,
  };
}

function solUsdcResponse(): SimulateResponse {
  return {
    snapshot_id: "snap-sim-1",
    sell_asset: "SOL",
    buy_asset: "USDC",
    amount: "1",
    asset: "SOL",
    side: "sell",
    notional_usd: "150",
    mid: {
      snapshot_id: "snap-sim-1",
      asset: "SOL",
      mid: "150",
      mid_source: "binance_usdm_index",
      timestamp: "2026-08-03T12:00:00Z",
    },
    rows: [
      row({
        venue: "humidifi",
        status: "ok",
        expected_output: "149.85",
        effective_price: "149.85",
        spread_bps: "2.1",
        total_cost_bps: "2.6",
        best: true,
        venue_symbol: "SOL/USDC",
        instrument_type: "prop_amm",
      }),
      row({
        venue: "binance",
        status: "ok",
        expected_output: "149.5",
        effective_price: "149.5",
        spread_bps: "3.0",
        total_cost_bps: "8.0",
        instrument_type: "spot",
        fee_breakdown: {
          embedded_in_price: false,
          trading_fee_bps: "5",
          platform_fee_bps: "0",
          gas_unknown: false,
          gas_bps: "0",
        },
      }),
      row({
        venue: "err_v",
        status: "error",
        error_code: "timeout",
        error_message: "upstream timeout",
        instrument_type: "spot",
      }),
      row({
        venue: "apex",
        status: "not_supported",
        instrument_type: "perp",
      }),
    ],
  };
}

function Wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
    },
  });
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider>{children}</TooltipProvider>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  fetchSimulatePairsMock.mockReset();
  postSimulateMock.mockReset();
  fetchVenuesMock.mockReset();
  fetchAssetsMock.mockReset();

  fetchSimulatePairsMock.mockResolvedValue(PAIRS);
  fetchVenuesMock.mockResolvedValue(VENUES);
  fetchAssetsMock.mockResolvedValue([
    {
      id: "SOL",
      category: "blue_chip",
      representations: { humidifi: "wSOL", binance: "SOL" },
    },
  ]);
  postSimulateMock.mockResolvedValue(solUsdcResponse());
});

afterEach(() => {
  cleanup();
});

describe("SimulateSection (WHI-815)", () => {
  it("renders SOL→USDC ranked rows with best highlight and delta vs best", async () => {
    render(
      <Wrapper>
        <SimulateSection />
      </Wrapper>,
    );

    await waitFor(() => {
      expect(postSimulateMock).toHaveBeenCalled();
    });

    const lastCall = postSimulateMock.mock.calls.at(-1)?.[0] as {
      sell_asset: string;
      buy_asset: string;
      amount: string;
    };
    expect(lastCall.sell_asset).toBe("SOL");
    expect(lastCall.buy_asset).toBe("USDC");

    await screen.findByTestId("simulate-results");

    const bestRow = screen.getByTestId("simulate-row-humidifi");
    expect(bestRow.getAttribute("data-best")).toBe("true");
    expect(within(bestRow).getByTestId("best-badge")).toBeTruthy();

    const binance = screen.getByTestId("simulate-row-binance");
    expect(binance.getAttribute("data-best")).toBe("false");
    expect(screen.getByTestId("delta-binance").textContent).toMatch(/Δ/);

    // Error row stays in place, not dropped.
    expect(screen.getByTestId("simulate-row-err_v").getAttribute("data-status")).toBe(
      "error",
    );
  });

  it("shows skeleton while the single-shot request is in flight", async () => {
    let resolveSim!: (v: SimulateResponse) => void;
    postSimulateMock.mockImplementation(
      () =>
        new Promise<SimulateResponse>((resolve) => {
          resolveSim = resolve;
        }),
    );

    render(
      <Wrapper>
        <SimulateSection />
      </Wrapper>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("simulate-skeleton")).toBeTruthy();
    });

    resolveSim(solUsdcResponse());
    await screen.findByTestId("simulate-results");
    expect(screen.queryByTestId("simulate-skeleton")).toBeNull();
  });

  it("lists not_supported venues in the collapsed unavailable section", async () => {
    render(
      <Wrapper>
        <SimulateSection />
      </Wrapper>,
    );
    await screen.findByTestId("simulate-results");

    const section = screen.getByTestId("unavailable-section");
    // Collapsed by default — expand to see venues.
    expect(screen.queryByTestId("unavailable-apex")).toBeNull();
    fireEvent.click(within(section).getByRole("button"));
    expect(screen.getByTestId("unavailable-apex")).toBeTruthy();
  });

  it("expands a row to show the fee breakdown", async () => {
    render(
      <Wrapper>
        <SimulateSection />
      </Wrapper>,
    );
    await screen.findByTestId("simulate-results");

    expect(screen.queryByTestId("breakdown-humidifi")).toBeNull();
    fireEvent.click(screen.getByTestId("simulate-row-humidifi").querySelector("button")!);
    expect(screen.getByTestId("breakdown-humidifi").textContent).toMatch(
      /Cost breakdown/i,
    );
    expect(screen.getByTestId("breakdown-humidifi").textContent).toMatch(
      /embedded/i,
    );
  });

  it("constrains selectors so two non-stables cannot be composed", async () => {
    render(
      <Wrapper>
        <SimulateSection />
      </Wrapper>,
    );
    await screen.findByTestId("simulate-form");

    // Wait for pair meta + default SOL→USDC seed.
    await waitFor(() => {
      const sell = screen.getByTestId("sell-select") as HTMLSelectElement;
      expect(sell.value).toBe("SOL");
    });

    const buy = screen.getByTestId("buy-select") as HTMLSelectElement;
    // Buy options while sell=SOL should be stables only.
    const buyValues = Array.from(buy.options).map((o) => o.value);
    expect(buyValues).toEqual(["USDC", "USDT"]);
    expect(buyValues).not.toContain("BTC");
  });

  it("surfaces structured 422 cross_pair as a distinct inline error", async () => {
    postSimulateMock.mockRejectedValue(
      new ApiError("fail", 422, {
        detail: {
          message: "cross pair: both legs non-stable",
          reason: "cross_pair",
        },
      }),
    );

    render(
      <Wrapper>
        <SimulateSection />
      </Wrapper>,
    );

    const alert = await screen.findByTestId("simulate-error");
    expect(alert.getAttribute("data-error-kind")).toBe("cross_pair");
    expect(alert.textContent?.toLowerCase()).toMatch(/cross|stable/);
  });

  it("surfaces unknown_asset 422 distinctly from cross_pair", async () => {
    postSimulateMock.mockRejectedValue(
      new ApiError("fail", 422, {
        detail: { message: "unknown asset: FOO", reason: "unknown_asset" },
      }),
    );

    render(
      <Wrapper>
        <SimulateSection />
      </Wrapper>,
    );

    const alert = await screen.findByTestId("simulate-error");
    expect(alert.getAttribute("data-error-kind")).toBe("unknown_asset");
  });

  it("does not fire a new simulation on each amount keystroke before debounce settles", async () => {
    // Identity debounce mock is active for this file — verify the amount
    // gate: intermediate invalid amounts never POST; a final valid amount does.
    // Real timer debounce is covered by useDebouncedValue.test.ts (AC5).
    postSimulateMock.mockClear();

    render(
      <Wrapper>
        <SimulateSection />
      </Wrapper>,
    );

    await waitFor(() => expect(postSimulateMock).toHaveBeenCalled());
    const baseline = postSimulateMock.mock.calls.length;

    const input = screen.getByTestId("amount-input") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "0" } });
    fireEvent.change(input, { target: { value: "0." } });
    fireEvent.change(input, { target: { value: "0.0" } });

    // Invalid amounts must not trigger additional POSTs.
    expect(postSimulateMock.mock.calls.length).toBe(baseline);

    fireEvent.change(input, { target: { value: "2" } });
    await waitFor(() => {
      expect(postSimulateMock.mock.calls.length).toBeGreaterThan(baseline);
    });
    const last = postSimulateMock.mock.calls.at(-1)?.[0] as { amount: string };
    expect(last.amount).toBe("2");
  });

  it("manual refresh re-runs the simulation", async () => {
    render(
      <Wrapper>
        <SimulateSection />
      </Wrapper>,
    );
    await screen.findByTestId("simulate-results");
    await waitFor(() => {
      expect(
        (screen.getByTestId("refresh-button") as HTMLButtonElement).disabled,
      ).toBe(false);
    });
    const baseline = postSimulateMock.mock.calls.length;

    fireEvent.click(screen.getByTestId("refresh-button"));
    await waitFor(() => {
      expect(postSimulateMock.mock.calls.length).toBeGreaterThan(baseline);
    });
  });

  it("loads pair legs from GET /simulate/pairs (not a hardcoded stable list)", async () => {
    fetchSimulatePairsMock.mockResolvedValue({
      stables: ["USDC"],
      assets: ["JUP"],
    });
    postSimulateMock.mockResolvedValue({
      ...solUsdcResponse(),
      sell_asset: "JUP",
      buy_asset: "USDC",
      asset: "JUP",
      amount: "1",
      rows: [],
    });

    render(
      <Wrapper>
        <SimulateSection />
      </Wrapper>,
    );

    await waitFor(() => {
      expect(fetchSimulatePairsMock).toHaveBeenCalled();
    });

    await waitFor(() => {
      const sell = screen.getByTestId("sell-select") as HTMLSelectElement;
      expect(Array.from(sell.options).map((o) => o.value)).toContain("JUP");
    });

    // USDT must not appear — only what the API returned.
    const buy = screen.getByTestId("buy-select") as HTMLSelectElement;
    expect(Array.from(buy.options).map((o) => o.value)).toEqual(["USDC"]);
  });
});
