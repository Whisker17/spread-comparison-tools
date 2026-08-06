// @vitest-environment jsdom

/**
 * Render contract for the shared asset block (WHI-808) as used by the stocks
 * boards (WHI-810): the emphasized mid-source badge is opt-in and its tooltip
 * copy comes from the section, never hardcoded in the component.
 *
 * WHI-841: block fetches exactly one notional (the selected size).
 */

import { cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AssetSpreadBlock } from "@/components/AssetSpreadBlock";
import { TooltipProvider } from "@/components/ui/tooltip";
import {
  STOCKS_MID_SOURCE_HINT,
  stocksBoard,
} from "@/config/sections/stocks";

const { useQuotesMatrixMock } = vi.hoisted(() => ({
  useQuotesMatrixMock: vi.fn(),
}));

vi.mock("@/hooks/useQuotes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useQuotes")>()),
  useQuotesMatrix: useQuotesMatrixMock,
}));

type FakeMid = { mid: string; mid_source: string; timestamp: string };

const MID: FakeMid = {
  mid: "512.34",
  mid_source: "cex_tradfi_index",
  timestamp: "2026-08-03T15:00:00Z",
};

function fakeQuery(mid?: FakeMid) {
  return {
    data: {
      asset: "QQQ",
      pairs: [],
      mids: mid ? [mid] : [],
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

function withProviders(children: ReactNode) {
  return <TooltipProvider>{children}</TooltipProvider>;
}

function renderBlock(
  props: { emphasizeMidSource?: boolean; notional?: string } = {},
) {
  return render(
    withProviders(
      <AssetSpreadBlock
        section={stocksBoard}
        asset="QQQ"
        notional={props.notional ?? "1000"}
        venues={["binance", "pancakeswap_bsc", "tessera_bsc"]}
        venueLabels={{
          binance: "Binance · bStocks · QQQBUSDT",
          pancakeswap_bsc: "PancakeSwap (BSC) · bStocks · QQQB · USDT",
          tessera_bsc: "Tessera (BSC) · bStocks · QQQB · USDT",
        }}
        orderbookVenues={["binance"]}
        midSourceHint={STOCKS_MID_SOURCE_HINT}
        emphasizeMidSource={props.emphasizeMidSource}
      />,
    ),
  );
}

beforeEach(() => {
  useQuotesMatrixMock.mockReset();
  useQuotesMatrixMock.mockReturnValue(fakeQuery(MID));
});

afterEach(cleanup);

describe("AssetSpreadBlock mid-source rendering (WHI-810)", () => {
  it("renders the emphasized badge with the section's hint when opted in", () => {
    renderBlock({ emphasizeMidSource: true });

    const badge = screen.getByTestId("mid-source-badge-QQQ");
    expect(badge.textContent).toContain("cex_tradfi_index");
    expect(badge.getAttribute("title")).toBe(STOCKS_MID_SOURCE_HINT);
  });

  it("falls back to the plain mid-source line when not emphasized", () => {
    renderBlock();

    expect(screen.queryByTestId("mid-source-badge-QQQ")).toBeNull();
    const meta = screen.getByTestId("snapshot-meta-QQQ");
    expect(meta.textContent).toContain("Mid source");
    expect(meta.textContent).toContain("cex_tradfi_index");
  });

  it("renders no mid-source chrome at all when the payload has no mid", () => {
    useQuotesMatrixMock.mockReturnValue(fakeQuery());
    renderBlock({ emphasizeMidSource: true });

    expect(screen.queryByTestId("mid-source-badge-QQQ")).toBeNull();
    expect(screen.getByTestId("snapshot-meta-QQQ").textContent).not.toContain(
      "Mid source",
    );
  });

  it("forwards the section instrument type to the quotes request", () => {
    renderBlock({ emphasizeMidSource: true });

    expect(useQuotesMatrixMock).toHaveBeenCalledWith(
      expect.objectContaining({
        asset: "QQQ",
        instrument_type: stocksBoard.instrumentType,
      }),
    );
  });
});

describe("AssetSpreadBlock single-tier fetch (WHI-864)", () => {
  it("requests only the displayed notional (not the full section list)", () => {
    renderBlock({ notional: "10000" });

    expect(useQuotesMatrixMock).toHaveBeenCalledWith(
      expect.objectContaining({
        asset: "QQQ",
        notionals: ["10000"],
      }),
    );
    const call = useQuotesMatrixMock.mock.calls[0]?.[0] as {
      notionals: string[];
    };
    expect(call.notionals).toEqual(["10000"]);
  });

  it("tags the block with the active notional for network/debug inspection", () => {
    renderBlock({ notional: "100000" });
    expect(
      screen.getByTestId("asset-block-QQQ").getAttribute("data-notional"),
    ).toBe("100000");
  });
});
