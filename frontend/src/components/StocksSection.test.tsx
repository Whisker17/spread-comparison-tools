// @vitest-environment jsdom

/**
 * `/stocks` page wiring (WHI-810): two boards, the bStocks rebase footnote on
 * P0-A only, the market-hours badge, emphasized mid-source badges, and the
 * `instrument_type=perp` request shape the equity board depends on.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StocksSection } from "@/components/StocksSection";
import { TooltipProvider } from "@/components/ui/tooltip";

import {
  BSTOCKS_REBASE_FOOTNOTE,
  equityPerpsBoard,
  STOCKS_MID_SOURCE_HINT,
  tokenizedStocksBoard,
} from "@/config/sections/stocks";

const { useQuotesMatrixMock, fetchAssetsMock, replaceMock } = vi.hoisted(() => ({
  useQuotesMatrixMock: vi.fn(),
  fetchAssetsMock: vi.fn(),
  replaceMock: vi.fn(),
}));

vi.mock("@/hooks/useQuotes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useQuotes")>()),
  useQuotesMatrix: useQuotesMatrixMock,
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  fetchAssets: fetchAssetsMock,
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ replace: replaceMock }),
  usePathname: () => "/stocks",
}));

function fakeQuery(params: { asset: string }) {
  return {
    data: {
      asset: params.asset,
      pairs: [],
      mids: [
        {
          mid: "512.34",
          mid_source: "cex_tradfi_index",
          timestamp: "2026-08-03T15:00:00Z",
        },
      ],
      snapshotIds: ["snap-abcdef123456"],
    },
    isLoading: false,
    isError: false,
    error: null,
    isFetching: false,
    dataUpdatedAt: 0,
    refetch: vi.fn(),
  };
}

function Wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider>{children}</TooltipProvider>
    </QueryClientProvider>
  );
}

function instrumentTypeForAsset(asset: string): unknown {
  const call = useQuotesMatrixMock.mock.calls.find(
    ([params]) => (params as { asset: string }).asset === asset,
  );
  expect(call, `no /quotes request for ${asset}`).toBeDefined();
  return (call?.[0] as { instrument_type?: unknown }).instrument_type;
}

beforeEach(() => {
  useQuotesMatrixMock.mockReset();
  useQuotesMatrixMock.mockImplementation(fakeQuery);
  fetchAssetsMock.mockReset();
  fetchAssetsMock.mockResolvedValue([]);
  replaceMock.mockReset();
});

afterEach(cleanup);

describe("StocksSection (WHI-810)", () => {
  it("renders both boards with their assets", () => {
    render(<StocksSection />, { wrapper: Wrapper });

    const tokenized = screen.getByTestId("stocks-board-tokenized");
    const perps = screen.getByTestId("stocks-board-equity_perp");
    for (const asset of tokenizedStocksBoard.assets) {
      expect(within(tokenized).getByTestId(`asset-block-${asset}`)).toBeTruthy();
    }
    for (const asset of equityPerpsBoard.assets) {
      expect(within(perps).getByTestId(`asset-block-${asset}`)).toBeTruthy();
    }
  });

  it("shows the bStocks rebase footnote on P0-A only", () => {
    render(<StocksSection />, { wrapper: Wrapper });

    const footnotes = screen.getAllByTestId("bstocks-rebase-footnote");
    expect(footnotes).toHaveLength(1);
    expect(footnotes[0]?.textContent).toContain(BSTOCKS_REBASE_FOOTNOTE);
    expect(
      within(screen.getByTestId("stocks-board-tokenized")).getByTestId(
        "bstocks-rebase-footnote",
      ),
    ).toBeTruthy();
    expect(
      within(screen.getByTestId("stocks-board-equity_perp")).queryByTestId(
        "bstocks-rebase-footnote",
      ),
    ).toBeNull();
  });

  it("renders the US market-hours badge in the page header", () => {
    render(<StocksSection />, { wrapper: Wrapper });

    const badge = screen.getByTestId("us-market-hours");
    expect(badge.textContent).toMatch(/^US market (open|closed)$/);
    expect(badge.getAttribute("data-open")).toMatch(/^(true|false)$/);
  });

  it("emphasizes the mid source on every stock asset block", () => {
    render(<StocksSection />, { wrapper: Wrapper });

    for (const asset of [
      ...tokenizedStocksBoard.assets,
      ...equityPerpsBoard.assets,
    ]) {
      const badge = screen.getByTestId(`mid-source-badge-${asset}`);
      expect(badge.textContent).toContain("cex_tradfi_index");
      expect(badge.getAttribute("title")).toBe(STOCKS_MID_SOURCE_HINT);
    }
  });

  it("requests instrument_type=perp for equity perps and spot default for bStocks", () => {
    render(<StocksSection />, { wrapper: Wrapper });

    // Without this, CEX adapters resolve spot and TSLA/NVDA cells are all "—".
    expect(instrumentTypeForAsset("TSLA")).toBe("perp");
    expect(instrumentTypeForAsset("QQQB")).toBeUndefined();
  });

  it("drops the Binance row for NVDAON (no CEX spot listing)", () => {
    render(<StocksSection />, { wrapper: Wrapper });

    const nvdaon = within(screen.getByTestId("asset-block-NVDAON"));
    expect(nvdaon.queryAllByText(/Binance/)).toHaveLength(0);
    expect(nvdaon.getByText(/Tessera \(BSC\)/)).toBeTruthy();
  });

  it("renders one shared size selector and fetches all notionals per asset", () => {
    render(<StocksSection />, { wrapper: Wrapper });

    // Page-level selector only — no per-block duplicate.
    expect(screen.getAllByTestId("size-selector")).toHaveLength(1);

    // Both boards share size config so page-level ?size= is not board-skewed.
    expect(tokenizedStocksBoard.defaultNotional).toBe(
      equityPerpsBoard.defaultNotional,
    );
    expect(tokenizedStocksBoard.notionals).toEqual(equityPerpsBoard.notionals);

    const assets = [
      ...tokenizedStocksBoard.assets,
      ...equityPerpsBoard.assets,
    ];
    for (const asset of assets) {
      const call = useQuotesMatrixMock.mock.calls.find(
        ([params]) => (params as { asset: string }).asset === asset,
      );
      expect(call, `no /quotes request for ${asset}`).toBeDefined();
      const params = call?.[0] as { notionals: string[] };
      // WHI-843: full multi-tier package per asset (not a single focus tier).
      expect(params.notionals).toEqual([...tokenizedStocksBoard.notionals]);
    }
  });
});
