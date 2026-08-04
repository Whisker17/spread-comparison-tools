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
  tokenizedStocksBoard,
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
      asset: "QQQB",
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
        section={tokenizedStocksBoard}
        asset="QQQB"
        notional={props.notional ?? "1000"}
        venues={["binance", "pancakeswap_bsc", "tessera_bsc"]}
        venueLabels={{
          binance: "Binance · spot · QQQBUSDT",
          pancakeswap_bsc: "PancakeSwap (BSC) · QQQB · USDT",
          tessera_bsc: "Tessera (BSC) · QQQB · USDT",
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

    const badge = screen.getByTestId("mid-source-badge-QQQB");
    expect(badge.textContent).toContain("cex_tradfi_index");
    expect(badge.getAttribute("title")).toBe(STOCKS_MID_SOURCE_HINT);
  });

  it("falls back to the plain mid-source line when not emphasized", () => {
    renderBlock();

    expect(screen.queryByTestId("mid-source-badge-QQQB")).toBeNull();
    const meta = screen.getByTestId("snapshot-meta-QQQB");
    expect(meta.textContent).toContain("Mid source");
    expect(meta.textContent).toContain("cex_tradfi_index");
  });

  it("renders no mid-source chrome at all when the payload has no mid", () => {
    useQuotesMatrixMock.mockReturnValue(fakeQuery());
    renderBlock({ emphasizeMidSource: true });

    expect(screen.queryByTestId("mid-source-badge-QQQB")).toBeNull();
    expect(screen.getByTestId("snapshot-meta-QQQB").textContent).not.toContain(
      "Mid source",
    );
  });

  it("forwards the section instrument type to the quotes request", () => {
    renderBlock({ emphasizeMidSource: true });

    expect(useQuotesMatrixMock).toHaveBeenCalledWith(
      expect.objectContaining({
        asset: "QQQB",
        instrument_type: tokenizedStocksBoard.instrumentType,
      }),
    );
  });
});

describe("AssetSpreadBlock multi-tier fetch (WHI-843)", () => {
  it("always requests the full section notional list (one multi-tier package)", () => {
    renderBlock({ notional: "10000" });

    expect(useQuotesMatrixMock).toHaveBeenCalledWith(
      expect.objectContaining({
        asset: "QQQB",
        notionals: [...tokenizedStocksBoard.notionals],
      }),
    );
    // One request carries every tier — size focus is a view preference only.
    const call = useQuotesMatrixMock.mock.calls[0]?.[0] as {
      notionals: string[];
    };
    expect(call.notionals.length).toBeGreaterThan(1);
  });

  it("tags the block with the active notional for network/debug inspection", () => {
    renderBlock({ notional: "100000" });
    expect(
      screen.getByTestId("asset-block-QQQB").getAttribute("data-notional"),
    ).toBe("100000");
  });
});
