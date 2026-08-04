"use client";

/**
 * Parameter-complete venues × notional-tiers matrix.
 *
 * Section agents drive venue sets, hidden columns, side view, and metric via
 * props/config — they must not edit this file (WHI-808 parallel-safety).
 */

import { useMemo } from "react";

import { StatusCell } from "@/components/StatusCell";
import type { Quote, SizeQuotePair } from "@/lib/api";
import {
  formatBps,
  formatNotional,
  parseDecimal,
  sortNotionals,
} from "@/lib/format";
import { heatClass, heatRange, type HeatRange } from "@/lib/heat";
import { isEligibleForBest, type MetricKey } from "@/lib/status";
import {
  bestVenueMap,
  bothLegsEligible,
  type SideView,
} from "@/lib/summary";
import { cn } from "@/lib/utils";

export type SpreadMatrixProps = {
  pairs: readonly SizeQuotePair[];
  /** Column order for notional tiers. Defaults to sorted unique from pairs. */
  notionals?: readonly string[];
  /**
   * Row order for venues. Empty/undefined = union of pair venues (sorted).
   * Section configs pass an explicit list to pin column sets.
   */
  venues?: readonly string[];
  /** Venues to omit from rows entirely. */
  hiddenVenues?: readonly string[];
  /** Disabled venues still render but are dimmed and never "best". */
  disabledVenues?: readonly string[];
  sideView?: SideView;
  /** Cell metric. Default total_cost_bps. */
  metric?: MetricKey;
  venueLabels?: Readonly<Record<string, string>>;
  /** Highlight best-eligible cells per tier (WHI-799 §5.2). Default true. */
  highlightBest?: boolean;
  /** Heat-color numeric cells. Default true. */
  heat?: boolean;
  className?: string;
  emptyMessage?: string;
  /** Retry handler for error-status cells. */
  onRetry?: () => void;
};

export function SpreadMatrix({
  pairs,
  notionals: notionalsProp,
  venues: venuesProp,
  hiddenVenues = [],
  disabledVenues = [],
  sideView = "buy",
  metric = "total_cost_bps",
  venueLabels,
  highlightBest = true,
  heat = true,
  className,
  emptyMessage = "No quote data",
  onRetry,
}: SpreadMatrixProps) {
  const hidden = useMemo(() => new Set(hiddenVenues), [hiddenVenues]);
  const disabled = useMemo(() => new Set(disabledVenues), [disabledVenues]);

  const notionals = useMemo(() => {
    if (notionalsProp && notionalsProp.length > 0) {
      return [...notionalsProp];
    }
    return sortNotionals([
      ...new Set(pairs.map((p) => String(p.notional_usd))),
    ]);
  }, [notionalsProp, pairs]);

  const venues = useMemo(() => {
    if (venuesProp && venuesProp.length > 0) {
      return venuesProp.filter((v) => !hidden.has(v));
    }
    const set = new Set(
      pairs.map((p) => p.venue).filter((v) => !hidden.has(v)),
    );
    return [...set].sort();
  }, [venuesProp, pairs, hidden]);

  const index = useMemo(() => {
    const map = new Map<string, SizeQuotePair>();
    for (const p of pairs) {
      map.set(`${p.venue}::${String(p.notional_usd)}`, p);
    }
    return map;
  }, [pairs]);

  const best = useMemo(() => {
    if (!highlightBest) return {};
    return bestVenueMap(pairs, {
      side: sideView,
      metric,
      venues: venuesProp && venuesProp.length > 0 ? venuesProp : undefined,
      hiddenVenues: [...hiddenVenues, ...disabledVenues],
    });
  }, [
    pairs,
    highlightBest,
    sideView,
    metric,
    venuesProp,
    hiddenVenues,
    disabledVenues,
  ]);

  /**
   * Per-column heat ranges (WHI-838 / WHI-799 §4.1). A gas-dominated $100 AMM
   * cell can be 100–1000× larger than CEX spreads; matrix-wide min/max would
   * collapse colour resolution on every larger tier. Extreme values remain
   * fully legible as numbers — only the colour mapping is column-local.
   */
  const rangesByNotional = useMemo(() => {
    const map = new Map<string, HeatRange | null>();
    if (!heat) return map;
    for (const n of notionals) {
      const values: (number | null)[] = [];
      for (const v of venues) {
        if (disabled.has(v)) continue;
        const pair = index.get(`${v}::${n}`);
        const value = metricValue(pair, sideView, metric);
        if (value === null) continue;
        if (!includeInHeat(pair, sideView, metric)) continue;
        values.push(value);
      }
      map.set(n, heatRange(values));
    }
    return map;
  }, [heat, venues, notionals, index, sideView, metric, disabled]);

  if (venues.length === 0 || notionals.length === 0) {
    return (
      <div
        className={cn(
          "rounded-lg border border-dashed border-zinc-300 p-6 text-center text-sm text-zinc-500 dark:border-zinc-700",
          className,
        )}
      >
        {emptyMessage}
      </div>
    );
  }

  return (
    <div className={cn("overflow-x-auto", className)} data-testid="spread-matrix">
      <table className="w-full min-w-[36rem] border-collapse text-sm">
        <thead>
          <tr className="border-b border-zinc-200 dark:border-zinc-800">
            <th className="sticky left-0 bg-white py-2 pr-3 text-left text-xs font-medium uppercase tracking-wide text-zinc-500 dark:bg-zinc-950">
              Venue
            </th>
            {notionals.map((n) => (
              <th
                key={n}
                className="px-1 py-2 text-center text-xs font-medium uppercase tracking-wide text-zinc-500"
              >
                {formatNotional(n)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {venues.map((venue) => {
            const isDisabled = disabled.has(venue);
            return (
              <tr
                key={venue}
                className={cn(
                  "border-b border-zinc-100 dark:border-zinc-900",
                  isDisabled && "opacity-40",
                )}
                data-venue={venue}
                data-disabled={isDisabled ? "true" : "false"}
              >
                <td className="sticky left-0 bg-white py-1 pr-3 font-medium text-zinc-800 dark:bg-zinc-950 dark:text-zinc-100">
                  {venueLabels?.[venue] ?? venue}
                </td>
                {notionals.map((n) => {
                  const pair = index.get(`${venue}::${n}`);
                  const cell = cellFromPair(pair, sideView, metric);
                  const isBest =
                    !isDisabled &&
                    highlightBest &&
                    best[n] === venue &&
                    cell.eligibleBest;
                  const heatOk =
                    heat &&
                    !isDisabled &&
                    cell.value !== null &&
                    includeInHeat(pair, sideView, metric);
                  const colRange = rangesByNotional.get(n) ?? null;

                  return (
                    <td key={n} className="px-0.5 py-0.5">
                      <StatusCell
                        quote={cell.displayQuote}
                        formattedMetric={cell.formatted}
                        metricKey={metric}
                        isBest={isBest}
                        heatClassName={
                          heatOk ? heatClass(cell.value, colRange) : undefined
                        }
                        onRetry={onRetry}
                      />
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-2 text-[11px] text-zinc-500">
        Cells: {metric.replace(/_/g, " ")} · view: {sideView.replace("_", " ")} ·
        best highlight excludes gas_unknown / non-ok (WHI-799 §5.2)
      </p>
    </div>
  );
}

type CellModel = {
  displayQuote: Quote | null;
  value: number | null;
  formatted: string | null;
  eligibleBest: boolean;
};

function cellFromPair(
  pair: SizeQuotePair | undefined,
  sideView: SideView,
  metric: MetricKey,
): CellModel {
  if (!pair) {
    return {
      displayQuote: null,
      value: null,
      formatted: null,
      eligibleBest: false,
    };
  }

  if (sideView === "round_trip") {
    const value = metricValue(pair, sideView, metric);
    const buy = pair.buy ?? null;
    const sell = pair.sell ?? null;
    // RT metric only defined when both legs ok (WHI-799 §4.6). If partial,
    // surface the non-ok leg for status chrome instead of buy-ok + "—".
    if (value === null) {
      const bad =
        buy && buy.status !== "ok"
          ? buy
          : sell && sell.status !== "ok"
            ? sell
            : (buy ?? sell);
      return {
        displayQuote: bad,
        value: null,
        formatted: null,
        eligibleBest: false,
      };
    }
    return {
      displayQuote: buy,
      value,
      formatted: formatBps(value),
      eligibleBest:
        metric === "total_cost_bps"
          ? bothLegsEligible(pair)
          : buy?.status === "ok" && sell?.status === "ok",
    };
  }

  const quote = sideView === "buy" ? (pair.buy ?? null) : (pair.sell ?? null);
  const value = metricValue(pair, sideView, metric);
  const eligibleBest =
    metric === "total_cost_bps"
      ? isEligibleForBest(quote)
      : Boolean(quote && quote.status === "ok" && value !== null);
  return {
    displayQuote: quote,
    value,
    formatted: value === null ? null : formatBps(value),
    eligibleBest,
  };
}

function metricValue(
  pair: SizeQuotePair | undefined,
  sideView: SideView,
  metric: MetricKey,
): number | null {
  if (!pair) return null;
  if (sideView === "round_trip") {
    if (metric === "total_cost_bps") {
      return parseDecimal(pair.round_trip_total_cost_bps);
    }
    return parseDecimal(pair.round_trip_spread_bps);
  }
  const quote = sideView === "buy" ? pair.buy : pair.sell;
  if (!quote) return null;
  if (metric === "total_cost_bps") {
    return parseDecimal(quote.total_cost_bps);
  }
  return parseDecimal(quote.spread_bps);
}

function includeInHeat(
  pair: SizeQuotePair | undefined,
  sideView: SideView,
  metric: MetricKey,
): boolean {
  if (!pair) return false;
  if (sideView === "round_trip") {
    if (metric === "total_cost_bps") return bothLegsEligible(pair);
    return pair.buy?.status === "ok" && pair.sell?.status === "ok";
  }
  const quote = sideView === "buy" ? pair.buy : pair.sell;
  if (!quote || quote.status !== "ok") return false;
  if (metric === "total_cost_bps") return isEligibleForBest(quote);
  return true;
}
