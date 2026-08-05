// @vitest-environment jsdom

/**
 * Blue-chips page wiring for WHI-841 / WHI-843 size selector.
 * WHI-848: production uses one WebSocket; unit tests mock the stream so
 * AssetSpreadBlock falls back to the HTTP hook (still one multi-tier call
 * per asset when stream is absent).
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BlueChipsSection } from "@/components/BlueChipsSection";
import { TooltipProvider } from "@/components/ui/tooltip";
import { NOTIONAL_TIERS_USD } from "@/config/notionals";
import { blueChipsSection } from "@/config/sections/blue-chips";

const { useQuotesMatrixMock, fetchAssetsMock, replaceMock } = vi.hoisted(() => ({
  useQuotesMatrixMock: vi.fn(),
  fetchAssetsMock: vi.fn(),
  replaceMock: vi.fn(),
}));

vi.mock("@/hooks/useQuotes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useQuotes")>()),
  useQuotesMatrix: useQuotesMatrixMock,
}));

// Passthrough provider + optional null so AssetSpreadBlock uses the HTTP mock.
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
  usePathname: () => "/blue-chips",
}));

function fakeQuery(params: { asset: string }) {
  return {
    data: {
      asset: params.asset,
      pairs: [],
      mids: [],
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

beforeEach(() => {
  useQuotesMatrixMock.mockReset();
  useQuotesMatrixMock.mockImplementation(fakeQuery);
  fetchAssetsMock.mockReset();
  fetchAssetsMock.mockResolvedValue([]);
  replaceMock.mockReset();
});

afterEach(cleanup);

describe("BlueChipsSection (WHI-843)", () => {
  it("renders one shared size selector (not per-asset)", () => {
    render(<BlueChipsSection />, { wrapper: Wrapper });
    expect(screen.getAllByTestId("size-selector")).toHaveLength(1);
    expect(screen.getByTestId("size-option-all")).toBeTruthy();
  });

  it("issues one multi-tier /quotes request per asset (3 total, all tiers)", () => {
    render(<BlueChipsSection />, { wrapper: Wrapper });

    expect(blueChipsSection.assets).toEqual(["BTC", "ETH", "SOL"]);
    // One call per asset with every section notional (not 15 single-tier calls).
    expect(useQuotesMatrixMock.mock.calls).toHaveLength(3);

    for (const asset of blueChipsSection.assets) {
      const call = useQuotesMatrixMock.mock.calls.find(
        ([params]) => (params as { asset: string }).asset === asset,
      );
      expect(call, `no /quotes request for ${asset}`).toBeDefined();
      const params = call?.[0] as { notionals: string[] };
      expect(params.notionals).toEqual([...NOTIONAL_TIERS_USD]);
      expect(params.notionals).toHaveLength(5);
    }
  });
});
