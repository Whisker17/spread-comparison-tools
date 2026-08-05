// @vitest-environment jsdom

/**
 * Blue-chips page wiring for WHI-841 / WHI-864 size selector.
 * WHI-848: production uses one WebSocket; unit tests mock the stream so
 * AssetSpreadBlock falls back to the HTTP hook (one single-tier call per
 * asset when stream is absent — WHI-864).
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BlueChipsSection } from "@/components/BlueChipsSection";
import { TooltipProvider } from "@/components/ui/tooltip";
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

describe("BlueChipsSection (WHI-864)", () => {
  it("renders one shared size selector without All (not per-asset)", () => {
    render(<BlueChipsSection />, { wrapper: Wrapper });
    expect(screen.getAllByTestId("size-selector")).toHaveLength(1);
    expect(screen.queryByTestId("size-option-all")).toBeNull();
    expect(screen.getByTestId("size-option-1000")).toBeTruthy();
  });

  it("issues one single-tier /quotes request per asset (default $1k)", () => {
    render(<BlueChipsSection />, { wrapper: Wrapper });

    expect(blueChipsSection.assets).toEqual(["BTC", "ETH", "SOL"]);
    // One call per asset with only the selected tier (not all five).
    expect(useQuotesMatrixMock.mock.calls).toHaveLength(3);

    for (const asset of blueChipsSection.assets) {
      const call = useQuotesMatrixMock.mock.calls.find(
        ([params]) => (params as { asset: string }).asset === asset,
      );
      expect(call, `no /quotes request for ${asset}`).toBeDefined();
      const params = call?.[0] as { notionals: string[] };
      expect(params.notionals).toEqual([blueChipsSection.defaultNotional]);
      expect(params.notionals).toHaveLength(1);
    }
  });
});
