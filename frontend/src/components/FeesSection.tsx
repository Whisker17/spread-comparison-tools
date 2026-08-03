"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { CostCompositionBars } from "@/components/CostCompositionBars";
import { FeeStructureTable } from "@/components/FeeStructureTable";
import {
  assetSwitcherOptions,
  FEES_DEFAULT_ASSET,
  FEES_DEFAULT_NOTIONAL,
  FEES_NOTIONALS,
  FEES_POLL_MS,
} from "@/config/sections/fees";
import { useQuotes } from "@/hooks/useQuotes";
import { fetchAssets, fetchFees, fetchVenues } from "@/lib/api";
import {
  formatFeesConclusion,
  rankCostComposition,
} from "@/lib/costComposition";
import { buildFeeTableGroups, buildVenueLabelMap } from "@/lib/feesTable";
import { formatNotional } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Full `/fees` page: static schedule table + live cost composition (WHI-813).
 *
 * Side buy/sell is a small extra control beyond the issue's asset/tier
 * switchers so the same notional can be compared for either leg.
 */
export function FeesSection() {
  const [asset, setAsset] = useState<string>(FEES_DEFAULT_ASSET);
  const [notional, setNotional] = useState<string>(FEES_DEFAULT_NOTIONAL);
  const [side, setSide] = useState<"buy" | "sell">("buy");

  const feesQuery = useQuery({
    queryKey: ["fees"],
    queryFn: ({ signal }) => fetchFees({ signal }),
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

  const assetOptions = useMemo(
    () => assetSwitcherOptions(assetsQuery.data),
    [assetsQuery.data],
  );

  // Single source of truth for quotes + labels (never fetch A and narrate B).
  const activeAsset = assetOptions.includes(asset)
    ? asset
    : (assetOptions[0] ?? FEES_DEFAULT_ASSET);

  const quotesQuery = useQuotes({
    asset: activeAsset,
    notional,
    side,
    refetchInterval: FEES_POLL_MS,
  });

  const venueLabels = useMemo(
    () => buildVenueLabelMap(venuesQuery.data ?? []),
    [venuesQuery.data],
  );

  const feeGroups = useMemo(
    () =>
      buildFeeTableGroups(feesQuery.data ?? [], venuesQuery.data ?? []),
    [feesQuery.data, venuesQuery.data],
  );

  const pairs = useMemo(
    () => quotesQuery.data?.pairs ?? [],
    [quotesQuery.data?.pairs],
  );
  const { ranked, incomplete, other } = useMemo(
    () =>
      rankCostComposition(pairs, {
        side,
        venueLabels,
      }),
    [pairs, side, venueLabels],
  );

  const conclusion = useMemo(
    () =>
      formatFeesConclusion(ranked, {
        asset: activeAsset,
        notionalUsd: notional,
        side,
      }),
    [ranked, activeAsset, notional, side],
  );

  const feesLoading = feesQuery.isLoading || venuesQuery.isLoading;
  const feesError = feesQuery.error ?? venuesQuery.error;

  return (
    <div className="space-y-8">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Fees</h1>
        <p className="max-w-3xl text-sm text-zinc-600 dark:text-zinc-400">
          Static fee schedules across venues, plus a live view of what a trade
          actually costs when spread and explicit fees are combined into{" "}
          <code className="text-[11px]">total_cost_bps</code>.
        </p>
      </header>

      <ExplainerStrip />

      <section className="space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold tracking-tight">
              Fee structure
            </h2>
            <p className="text-xs text-zinc-500">
              From <code className="text-[11px]">GET /fees</code> (WHI-812
              catalog). Citations link to venue docs;{" "}
              <code className="text-[11px]">updated_at</code> is the schedule
              stamp.
            </p>
          </div>
          {feesQuery.dataUpdatedAt ? (
            <p className="text-xs text-zinc-400">
              Loaded {new Date(feesQuery.dataUpdatedAt).toLocaleString()}
            </p>
          ) : null}
        </div>

        {feesLoading ? (
          <p className="text-sm text-zinc-500">Loading fee schedules…</p>
        ) : feesError ? (
          <p className="text-sm text-rose-600 dark:text-rose-400">
            Failed to load fees:{" "}
            {feesError instanceof Error ? feesError.message : String(feesError)}
          </p>
        ) : (
          <FeeStructureTable groups={feeGroups} />
        )}
      </section>

      <section className="space-y-4">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">
            Cost composition
          </h2>
          <p className="text-xs text-zinc-500">
            Live <code className="text-[11px]">GET /quotes</code> — stacked bar
            per venue: spread + trading fee + platform + gas. Compare the same
            notional across venues without leaving this page.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-4">
          <Switcher
            label="Asset"
            value={activeAsset}
            options={assetOptions.map((a) => ({ value: a, label: a }))}
            onChange={setAsset}
          />
          <Switcher
            label="Size"
            value={notional}
            options={FEES_NOTIONALS.map((n) => ({
              value: n,
              label: formatNotional(n),
            }))}
            onChange={setNotional}
          />
          <Switcher
            label="Side"
            value={side}
            options={[
              { value: "buy", label: "Buy" },
              { value: "sell", label: "Sell" },
            ]}
            onChange={(v) => setSide(v as "buy" | "sell")}
          />
          {quotesQuery.isFetching ? (
            <span className="text-xs text-zinc-400">Refreshing…</span>
          ) : null}
        </div>

        {quotesQuery.isLoading ? (
          <p className="text-sm text-zinc-500">Loading live quotes…</p>
        ) : quotesQuery.error ? (
          <p className="text-sm text-rose-600 dark:text-rose-400">
            Failed to load quotes:{" "}
            {quotesQuery.error instanceof Error
              ? quotesQuery.error.message
              : String(quotesQuery.error)}
          </p>
        ) : (
          <>
            <CostCompositionBars
              ranked={ranked}
              incomplete={incomplete}
              other={other}
            />
            {conclusion ? (
              <p
                className="rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm text-zinc-800 dark:border-zinc-800 dark:bg-zinc-900/50 dark:text-zinc-200"
                data-testid="fees-conclusion"
              >
                {conclusion}
              </p>
            ) : (
              <p className="text-sm text-zinc-500">
                No complete total-cost quotes yet for {activeAsset} at{" "}
                {formatNotional(notional)} — incomplete (gas_unknown) venues
                never win ranking.
              </p>
            )}
          </>
        )}
      </section>
    </div>
  );
}

function ExplainerStrip() {
  return (
    <aside className="space-y-2 rounded-lg border border-zinc-200 bg-zinc-50/80 px-4 py-3 text-sm text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900/40 dark:text-zinc-300">
      <p>
        <strong className="font-medium text-zinc-900 dark:text-zinc-100">
          Embedded vs explicit fees.
        </strong>{" "}
        Prop AMM and public AMM quotes usually show no trading-fee bar segment
        — the LP / market-maker fee is already inside the quoted price, so it
        shows up in the <em>spread</em> segment (marked{" "}
        <span className="whitespace-nowrap">“fee in price”</span>). CEX and
        perp venues add an explicit taker fee on top of spread.
      </p>
      <p>
        <strong className="font-medium text-zinc-900 dark:text-zinc-100">
          Funding is informational only.
        </strong>{" "}
        Perp funding models appear in the fee table but are{" "}
        <em>not</em> included in default{" "}
        <code className="text-[11px]">total_cost_bps</code> (WHI-799 §5.3).
        Holding-cost simulation is a later follow-up.
      </p>
    </aside>
  );
}

function Switcher({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: readonly { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11px] font-medium uppercase tracking-wide text-zinc-500">
        {label}
      </span>
      <div className="inline-flex rounded-md border border-zinc-200 p-0.5 dark:border-zinc-700">
        {options.map((opt) => {
          const active = opt.value === value;
          return (
            <button
              key={opt.value}
              type="button"
              onClick={() => onChange(opt.value)}
              className={cn(
                "rounded px-2.5 py-1 text-xs font-medium transition-colors",
                active
                  ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                  : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800",
              )}
            >
              {opt.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
