"use client";

/**
 * Full `/simulate` page: pair pickers from GET /simulate/pairs, free-form
 * amount, single-shot ranked venue list (WHI-815).
 */

import { useQuery } from "@tanstack/react-query";
import { ArrowDownUp, RefreshCw } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

import { SimulateResultList } from "@/components/SimulateResultList";
import { Button } from "@/components/ui/button";
import {
  SIMULATE_DEBOUNCE_MS,
  useSimulate,
} from "@/hooks/useSimulate";
import {
  fetchAssets,
  fetchSimulatePairs,
  fetchVenues,
} from "@/lib/api";
import { formatNotional, formatPrice, parseDecimal } from "@/lib/format";
import {
  constrainSimulateSelection,
  defaultSimulatePair,
  isValidSimulateAmount,
  isValidSimulatePair,
  selectorOptionsFor,
  swapSimulatePair,
  type SimulatePair,
} from "@/lib/simulatePairs";
import {
  buildVenueMetaMap,
  parseSimulateError,
} from "@/lib/simulateView";
import { cn } from "@/lib/utils";

const DEFAULT_AMOUNT = "1";

export function SimulateSection() {
  const pairsQuery = useQuery({
    queryKey: ["simulate-pairs"],
    queryFn: ({ signal }) => fetchSimulatePairs({ signal }),
    staleTime: 60_000,
  });

  const venuesQuery = useQuery({
    queryKey: ["venues"],
    queryFn: ({ signal }) => fetchVenues({ signal }),
    staleTime: 60_000,
  });

  const assetsQuery = useQuery({
    queryKey: ["assets"],
    queryFn: ({ signal }) => fetchAssets({ signal }),
    staleTime: 60_000,
  });

  const pairMeta = useMemo(
    () =>
      pairsQuery.data
        ? {
            stables: pairsQuery.data.stables,
            assets: pairsQuery.data.assets,
          }
        : null,
    [pairsQuery.data],
  );

  // User override; when null, fall through to API-derived defaults (no effect seed).
  const [pairOverride, setPairOverride] = useState<SimulatePair | null>(null);
  const [amount, setAmount] = useState(DEFAULT_AMOUNT);

  const defaults = useMemo(
    () =>
      pairMeta
        ? defaultSimulatePair(pairMeta)
        : { sell: "", buy: "" },
    [pairMeta],
  );
  const sell = pairOverride?.sell || defaults.sell;
  const buy = pairOverride?.buy || defaults.buy;

  const simulate = useSimulate({
    sellAsset: sell,
    buyAsset: buy,
    amount,
    pairMeta,
  });

  const venueMeta = useMemo(
    () => buildVenueMetaMap(venuesQuery.data ?? []),
    [venuesQuery.data],
  );

  const representations = useMemo(() => {
    const nonStable = simulate.data?.asset;
    if (!nonStable) return {};
    const row = (assetsQuery.data ?? []).find(
      (a) => a.id.toUpperCase() === nonStable.toUpperCase(),
    );
    return row?.representations ?? {};
  }, [assetsQuery.data, simulate.data?.asset]);

  const sellOptions = useMemo(
    () => (pairMeta ? selectorOptionsFor(buy, pairMeta) : []),
    [pairMeta, buy],
  );
  const buyOptions = useMemo(
    () => (pairMeta ? selectorOptionsFor(sell, pairMeta) : []),
    [pairMeta, sell],
  );

  const pairValid =
    pairMeta !== null && isValidSimulatePair(sell, buy, pairMeta);
  const amountValid = isValidSimulateAmount(amount);

  const inlineError =
    simulate.isError && simulate.error
      ? parseSimulateError(simulate.error)
      : null;

  const approxUsd = approxUsdSubtitle(amount, sell, simulate.data);

  function onSellChange(value: string) {
    if (!pairMeta) return;
    setPairOverride(
      constrainSimulateSelection({ sell, buy }, "sell", value, pairMeta),
    );
  }

  function onBuyChange(value: string) {
    if (!pairMeta) return;
    setPairOverride(
      constrainSimulateSelection({ sell, buy }, "buy", value, pairMeta),
    );
  }

  function onSwap() {
    setPairOverride(swapSimulatePair({ sell, buy }));
  }

  const pairsLoading = pairsQuery.isLoading;
  const pairsFailed = pairsQuery.isError;

  return (
    <div className="space-y-6" data-testid="simulate-section">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Simulate</h1>
        <p className="mt-1 max-w-3xl text-sm text-zinc-600 dark:text-zinc-400">
          Aggregator-style trade comparison across venues. Pick a sell/buy pair
          (exactly one USD stable leg) and amount — results rank by expected
          output with full cost breakdowns. Read-only: no execution.
        </p>
      </header>

      <section
        className="rounded-xl border border-zinc-200 bg-zinc-50/50 p-4 dark:border-zinc-800 dark:bg-zinc-900/30"
        data-testid="simulate-form"
      >
        {pairsFailed && (
          <p className="mb-3 text-sm text-rose-600" role="alert">
            Could not load tradeable pairs. Check the API and retry.
          </p>
        )}

        <div className="flex flex-col gap-3 lg:flex-row lg:items-end">
          <Field label="Sell" htmlFor="simulate-sell">
            <select
              id="simulate-sell"
              data-testid="sell-select"
              className={selectClass}
              value={sell}
              disabled={pairsLoading || !pairMeta}
              onChange={(e) => onSellChange(e.target.value)}
            >
              {sell && !sellOptions.includes(sell) && (
                <option value={sell}>{sell}</option>
              )}
              {sellOptions.map((id) => (
                <option key={id} value={id}>
                  {id}
                </option>
              ))}
            </select>
          </Field>

          <div className="flex justify-center lg:pb-0.5">
            <Button
              type="button"
              variant="outline"
              size="icon"
              onClick={onSwap}
              disabled={!pairMeta || !sell || !buy}
              aria-label="Swap sell and buy"
              data-testid="swap-button"
            >
              <ArrowDownUp className="h-4 w-4" />
            </Button>
          </div>

          <Field label="Buy" htmlFor="simulate-buy">
            <select
              id="simulate-buy"
              data-testid="buy-select"
              className={selectClass}
              value={buy}
              disabled={pairsLoading || !pairMeta}
              onChange={(e) => onBuyChange(e.target.value)}
            >
              {buy && !buyOptions.includes(buy) && (
                <option value={buy}>{buy}</option>
              )}
              {buyOptions.map((id) => (
                <option key={id} value={id}>
                  {id}
                </option>
              ))}
            </select>
          </Field>

          <Field label={`Amount (${sell || "sell asset"})`} htmlFor="simulate-amount">
            <input
              id="simulate-amount"
              data-testid="amount-input"
              type="text"
              inputMode="decimal"
              autoComplete="off"
              className={selectClass}
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="e.g. 1"
            />
          </Field>

          <Button
            type="button"
            variant="outline"
            onClick={() => void simulate.refetch()}
            disabled={!simulate.canSimulate || simulate.isFetching}
            data-testid="refresh-button"
            className="shrink-0"
          >
            <RefreshCw
              className={cn(
                "h-4 w-4",
                simulate.isFetching && "animate-spin",
              )}
            />
            Refresh
          </Button>
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-zinc-500">
          {approxUsd && <span data-testid="approx-usd">{approxUsd}</span>}
          {!pairValid && pairMeta && sell && buy && (
            <span className="text-amber-700 dark:text-amber-300" role="status">
              Pair must be exactly one tradeable stable + one catalog asset.
            </span>
          )}
          {!amountValid && amount.trim() !== "" && (
            <span className="text-amber-700 dark:text-amber-300" role="status">
              Amount must be a positive number (sell-asset units).
            </span>
          )}
          <span className="text-zinc-400">
            Auto-runs after {SIMULATE_DEBOUNCE_MS}ms idle (debounced).
          </span>
        </div>
      </section>

      {inlineError && (
        <div
          className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-200"
          role="alert"
          data-testid="simulate-error"
          data-error-kind={inlineError.kind}
        >
          {inlineError.message}
        </div>
      )}

      <SimulateResultList
        data={simulate.data}
        isLoading={
          Boolean(pairMeta) &&
          simulate.canSimulate &&
          (simulate.isLoading || simulate.isPending) &&
          !simulate.data
        }
        isRefreshing={simulate.isFetching && Boolean(simulate.data)}
        venueMeta={venueMeta}
        representations={representations}
      />

      <footer className="space-y-1 border-t border-zinc-200 pt-4 text-xs text-zinc-500 dark:border-zinc-800">
        <p>
          <strong className="font-medium text-zinc-700 dark:text-zinc-300">
            Best row.
          </strong>{" "}
          Highlighted from the API <code className="text-[11px]">best</code>{" "}
          flag only (WHI-799 §5.2 — status=ok and complete total_cost_bps;
          gas_unknown never wins). The UI does not re-rank.
        </p>
        <p>
          <strong className="font-medium text-zinc-700 dark:text-zinc-300">
            Pair scope.
          </strong>{" "}
          Phase 1 accepts only USD-stable-paired trades. Selectors are fed by{" "}
          <code className="text-[11px]">GET /simulate/pairs</code> so stables
          are never hardcoded in the frontend.
        </p>
      </footer>
    </div>
  );
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor: string;
  children: ReactNode;
}) {
  return (
    <label
      htmlFor={htmlFor}
      className="flex min-w-[8rem] flex-1 flex-col gap-1 text-xs font-medium text-zinc-600 dark:text-zinc-300"
    >
      <span>{label}</span>
      {children}
    </label>
  );
}

const selectClass =
  "h-9 w-full rounded-md border border-zinc-300 bg-white px-2 text-sm text-zinc-900 shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-400 disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50";

/**
 * ≈USD line from the last successful response when amount/pair still match;
 * omit before first simulation (no mid yet).
 */
function approxUsdSubtitle(
  amount: string,
  sell: string,
  data: ReturnType<typeof useSimulate>["data"],
): string | null {
  if (!data) return null;
  if (data.sell_asset.toUpperCase() !== sell.toUpperCase()) return null;
  const amt = parseDecimal(amount);
  const dataAmt = parseDecimal(data.amount);
  if (amt === null || dataAmt === null) return null;
  // Allow tiny float noise.
  if (Math.abs(amt - dataAmt) > 1e-9 * Math.max(1, Math.abs(dataAmt))) {
    return null;
  }
  const notional = parseDecimal(data.notional_usd);
  if (notional === null) return null;
  return `≈ ${formatNotional(notional)} · mid ${formatPrice(data.mid.mid)}`;
}
