// @vitest-environment jsdom

/**
 * `/stocks` page wiring (WHI-882): one board per underlying, form badges,
 * bStocks rebase footnote when any bstock form is live, mid-source emphasis,
 * and no board-level instrument_type pin (form expansion on the backend).
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StocksSection } from "@/components/StocksSection";
import { TooltipProvider } from "@/components/ui/tooltip";

import {
  BSTOCKS_REBASE_FOOTNOTE,
  STOCK_UNDERLYINGS,
  STOCKS_MID_SOURCE_HINT,
  stocksBoard,
} from "@/config/sections/stocks";
import { makeRowKey } from "@/lib/pairIdentity";

const { useQuotesMatrixMock, fetchAssetsMock, replaceMock } = vi.hoisted(() => ({
  useQuotesMatrixMock: vi.fn(),
  fetchAssetsMock: vi.fn(),
  replaceMock: vi.fn(),
}));

vi.mock("@/hooks/useQuotes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useQuotes")>()),
  useQuotesMatrix: useQuotesMatrixMock,
}));

// WHI-848: passthrough stream so AssetSpreadBlock still exercises the HTTP mock.
vi.mock("@/hooks/useQuotesStream", () => ({
  QuotesStreamProvider: ({ children }: { children: ReactNode }) => children,
  useQuotesStream: () => ({
    status: "live" as const,
    byAsset: {},
    matrixFor: () => undefined,
    resnapshot: vi.fn(),
    lastError: null,
    hasAsset: () => false,
  }),
  useQuotesStreamOptional: () => null,
  useStreamAssetQuotes: () => ({
    data: undefined,
    isLoading: false,
    isFetching: false,
    isError: false,
    error: null,
    status: "live" as const,
    refetch: vi.fn(),
    dataUpdatedAt: 0,
  }),
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

function matrixParamsFor(asset: string): {
  instrument_type?: unknown;
  forms?: readonly string[];
  notionals: string[];
} {
  const call = useQuotesMatrixMock.mock.calls.find(
    ([params]) => (params as { asset: string }).asset === asset,
  );
  expect(call, `no /quotes request for ${asset}`).toBeDefined();
  return call?.[0] as {
    instrument_type?: unknown;
    forms?: readonly string[];
    notionals: string[];
  };
}

beforeEach(() => {
  useQuotesMatrixMock.mockReset();
  useQuotesMatrixMock.mockImplementation(fakeQuery);
  fetchAssetsMock.mockReset();
  fetchAssetsMock.mockResolvedValue([]);
  replaceMock.mockReset();
});

afterEach(cleanup);

describe("StocksSection (WHI-882)", () => {
  it("renders one board per underlying", () => {
    render(<StocksSection />, { wrapper: Wrapper });

    for (const underlying of STOCK_UNDERLYINGS) {
      expect(screen.getByTestId(`stocks-board-${underlying}`)).toBeTruthy();
      expect(screen.getByTestId(`asset-block-${underlying}`)).toBeTruthy();
    }
    // Legacy token ids must not appear as boards.
    expect(screen.queryByTestId("asset-block-NVDAB")).toBeNull();
    expect(screen.queryByTestId("asset-block-NVDAON")).toBeNull();
    expect(screen.queryByTestId("stocks-board-tokenized")).toBeNull();
    expect(screen.queryByTestId("stocks-board-equity_perp")).toBeNull();
  });

  it("NVDA matrix includes perp and token form rows with distinct badges", () => {
    render(<StocksSection />, { wrapper: Wrapper });

    const nvda = within(screen.getByTestId("asset-block-NVDA"));
    const matrix = nvda.getByTestId("spread-matrix");
    // Form-aware row keys on the matrix.
    const bstockRow = matrix.querySelector(
      `[data-row-key="${makeRowKey("tessera_bsc", "bstock")}"]`,
    );
    const ondoRow = matrix.querySelector(
      `[data-row-key="${makeRowKey("tessera_bsc", "ondo")}"]`,
    );
    expect(
      matrix.querySelector(`[data-row-key="${makeRowKey("binance", "perp")}"]`),
    ).toBeTruthy();
    expect(bstockRow).toBeTruthy();
    expect(ondoRow).toBeTruthy();
    // Form badges distinguish the two tessera rows on the same venue.
    expect(bstockRow?.textContent).toMatch(/bStocks/i);
    expect(bstockRow?.textContent).toContain("NVDAB");
    expect(ondoRow?.textContent).toMatch(/Ondo/i);
    expect(ondoRow?.textContent).toContain("NVDAon");
  });

  it("attaches the bStocks rebase footnote only to boards with bstock forms", () => {
    render(<StocksSection />, { wrapper: Wrapper });

    // NVDA / QQQ / SPCX have live bstock; TSLA / AAPL / MSFT do not.
    expect(
      within(screen.getByTestId("stocks-board-NVDA")).getByTestId(
        "bstocks-rebase-footnote",
      ).textContent,
    ).toContain(BSTOCKS_REBASE_FOOTNOTE);
    expect(
      within(screen.getByTestId("stocks-board-QQQ")).getByTestId(
        "bstocks-rebase-footnote",
      ),
    ).toBeTruthy();
    expect(
      within(screen.getByTestId("stocks-board-TSLA")).queryByTestId(
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

  it("emphasizes the mid source on every underlying block", () => {
    render(<StocksSection />, { wrapper: Wrapper });

    for (const underlying of STOCK_UNDERLYINGS) {
      const badge = screen.getByTestId(`mid-source-badge-${underlying}`);
      expect(badge.textContent).toContain("cex_tradfi_index");
      expect(badge.getAttribute("title")).toBe(STOCKS_MID_SOURCE_HINT);
    }
  });

  it("does not pin instrument_type; passes live forms for NVDA", () => {
    render(<StocksSection />, { wrapper: Wrapper });

    const nvda = matrixParamsFor("NVDA");
    // form_class drives CEX spot vs perp — do not force board-level perp.
    expect(nvda.instrument_type).toBeUndefined();
    expect([...(nvda.forms ?? [])].sort()).toEqual(
      ["bstock", "ondo", "perp"].sort(),
    );

    const tsla = matrixParamsFor("TSLA");
    expect(tsla.instrument_type).toBeUndefined();
    expect(tsla.forms).toEqual(["perp"]);
  });

  it("renders one shared size selector and fetches only the selected tier", () => {
    render(<StocksSection />, { wrapper: Wrapper });

    expect(screen.getAllByTestId("size-selector")).toHaveLength(1);
    expect(screen.queryByTestId("size-option-all")).toBeNull();

    for (const underlying of STOCK_UNDERLYINGS) {
      const params = matrixParamsFor(underlying);
      expect(params.notionals).toEqual([stocksBoard.defaultNotional]);
    }
  });
});
