"use client";

/**
 * Client-side quotes polling (TanStack Query).
 *
 * Choice note (PR): TanStack Query over SWR for explicit query-key control,
 * multi-notional fan-out, and first-class manual refetch.
 */

import {
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";

import {
  fetchQuotes,
  fetchQuotesMultiNotional,
  type InstrumentType,
  type QuotesResponse,
  type ReferenceMid,
  type SizeQuotePair,
} from "@/lib/api";

/**
 * Hook default poll interval. Section pages that need a product default
 * (e.g. blue-chips 30s) set `section.pollIntervalMs` instead of changing this.
 */
export const DEFAULT_POLL_MS = 15_000;

export type UseQuotesParams = {
  asset: string;
  notional: string | number;
  venues?: readonly string[];
  side?: "buy" | "sell";
  instrument_type?: InstrumentType;
  /** Polling interval ms; 0 / false disables. Default DEFAULT_POLL_MS (15s). */
  refetchInterval?: number | false;
  enabled?: boolean;
};

export function quotesQueryKey(params: UseQuotesParams) {
  return [
    "quotes",
    params.asset,
    String(params.notional),
    params.venues?.join(",") ?? "",
    params.side ?? "",
    params.instrument_type ?? "",
  ] as const;
}

/** Single notional `/quotes` poll + manual refresh via `refetch`. */
export function useQuotes(
  params: UseQuotesParams,
): UseQueryResult<QuotesResponse, Error> {
  const interval =
    params.refetchInterval === undefined
      ? DEFAULT_POLL_MS
      : params.refetchInterval;

  return useQuery({
    queryKey: quotesQueryKey(params),
    queryFn: ({ signal }) =>
      fetchQuotes(
        {
          asset: params.asset,
          notional: params.notional,
          venues: params.venues,
          side: params.side,
          instrument_type: params.instrument_type,
        },
        { signal },
      ),
    enabled: params.enabled ?? Boolean(params.asset),
    refetchInterval: interval === false ? false : interval,
    staleTime: 5_000,
  });
}

export type UseQuotesMatrixParams = {
  asset: string;
  notionals: readonly (string | number)[];
  venues?: readonly string[];
  side?: "buy" | "sell";
  instrument_type?: InstrumentType;
  refetchInterval?: number | false;
  enabled?: boolean;
};

export type QuotesMatrixData = {
  asset: string;
  pairs: SizeQuotePair[];
  mids: ReferenceMid[];
  snapshotIds: string[];
};

export function quotesMatrixQueryKey(params: UseQuotesMatrixParams) {
  return [
    "quotes-matrix",
    params.asset,
    params.notionals.map(String).join(","),
    params.venues?.join(",") ?? "",
    params.side ?? "",
    params.instrument_type ?? "",
  ] as const;
}

/** Multi-notional fan-out for SpreadMatrix. */
export function useQuotesMatrix(
  params: UseQuotesMatrixParams,
): UseQueryResult<QuotesMatrixData, Error> {
  const interval =
    params.refetchInterval === undefined
      ? DEFAULT_POLL_MS
      : params.refetchInterval;

  return useQuery({
    queryKey: quotesMatrixQueryKey(params),
    queryFn: ({ signal }) =>
      fetchQuotesMultiNotional(
        {
          asset: params.asset,
          notionals: params.notionals,
          venues: params.venues,
          side: params.side,
          instrument_type: params.instrument_type,
        },
        { signal },
      ),
    enabled: (params.enabled ?? true) && Boolean(params.asset),
    refetchInterval: interval === false ? false : interval,
    staleTime: 5_000,
  });
}

/** Invalidate all quotes queries (manual global refresh). */
export function useRefreshQuotes() {
  const qc = useQueryClient();
  return () =>
    qc.invalidateQueries({
      predicate: (q) =>
        Array.isArray(q.queryKey) &&
        (q.queryKey[0] === "quotes" || q.queryKey[0] === "quotes-matrix"),
    });
}
