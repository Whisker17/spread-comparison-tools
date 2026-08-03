"use client";

/**
 * Debounced POST /simulate query (WHI-815).
 *
 * Simulation is single-shot and rate-guarded upstream — never fire per
 * keystroke. Pair/amount changes debounce; manual refresh calls refetch().
 */

import {
  useQuery,
  type UseQueryResult,
} from "@tanstack/react-query";

import {
  postSimulate,
  type SimulateRequest,
  type SimulateResponse,
} from "@/lib/api";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import {
  isValidSimulateAmount,
  isValidSimulatePair,
  type SimulatePairMeta,
} from "@/lib/simulatePairs";

/** Default debounce for amount / pair edits (ms). */
export const SIMULATE_DEBOUNCE_MS = 400;

export type UseSimulateParams = {
  sellAsset: string;
  buyAsset: string;
  /** Raw amount string (sell-asset units); debounced before request. */
  amount: string;
  pairMeta: SimulatePairMeta | null;
  /** Override debounce for tests. */
  debounceMs?: number;
  enabled?: boolean;
};

export function simulateQueryKey(params: {
  sellAsset: string;
  buyAsset: string;
  amount: string;
}) {
  return [
    "simulate",
    params.sellAsset,
    params.buyAsset,
    params.amount,
  ] as const;
}

export type UseSimulateResult = UseQueryResult<SimulateResponse, Error> & {
  /** Amount currently in flight / last requested (debounced). */
  debouncedAmount: string;
  /** True when form is valid enough to request. */
  canSimulate: boolean;
};

export function useSimulate(params: UseSimulateParams): UseSimulateResult {
  const debounceMs = params.debounceMs ?? SIMULATE_DEBOUNCE_MS;
  // Debounce free-form amount only — discrete select changes should fire
  // immediately (AC: debounce keystrokes, not every UI control).
  const debouncedAmount = useDebouncedValue(params.amount, debounceMs);
  const sell = params.sellAsset;
  const buy = params.buyAsset;

  const meta = params.pairMeta;
  const canSimulate =
    Boolean(meta) &&
    isValidSimulatePair(sell, buy, meta ?? { stables: [], assets: [] }) &&
    isValidSimulateAmount(debouncedAmount);

  const enabled = (params.enabled ?? true) && canSimulate;

  const query = useQuery({
    queryKey: simulateQueryKey({
      sellAsset: sell,
      buyAsset: buy,
      amount: debouncedAmount.trim(),
    }),
    queryFn: ({ signal }) => {
      const body: SimulateRequest = {
        sell_asset: sell,
        buy_asset: buy,
        amount: debouncedAmount.trim(),
      };
      return postSimulate(body, { signal });
    },
    enabled,
    staleTime: 0,
    gcTime: 30_000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  return {
    ...query,
    debouncedAmount,
    canSimulate,
  };
}
