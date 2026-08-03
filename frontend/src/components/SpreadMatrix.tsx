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
import { formatBps, formatNotional } from "@/lib/format";
import { heatClass, heatRange } from "@/lib/heat";
import {
  bestVenueMap,
  type SideView,
} from "@/lib/summary";
import type { MetricKey } from "@/lib/status";
import { parseDecimal } from "@/lib/format";
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
}: SpreadMatrixProps) {
  const hidden = useMemo(() => new Set(hiddenVenues), [hiddenVenues]);
  const disabled = useMemo(() => new Set(disabledVenues), [disabledVenues]);

  const notionals = useMemo(() => {
    if (notionalsProp && notionalsProp.length > 0) {
      return [...notionalsProp];
    }
    const set = new Set(pairs.map((p) => String(p.notional_usd)));
    return [...set].sort(
      (a, b) => (parseDecimal(a) ?? 0) - (parseDecimal(b) ?? 0),
    );
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
      venues: venuesProp && venuesProp.length > 0 ? venuesProp : undefined,
      hiddenVenues: [...hiddenVenues, ...disabledVenues],
    });
  }, [
    pairs,
    highlightBest,
    sideView,
    venuesProp,
    hiddenVenues,
    disabledVenues,
  ]);

  const range = useMemo(() => {
    if (!heat) return null;
    const values: (number | null)[] = [];
    for (const v of venues) {
      if (disabled.has(v)) continue;
      for (const n of notionals) {
        const pair = index.get(`${v}::${n}`);
        const q = quoteFromPair(pair, sideView);
        if (!q || q.status !== "ok") continue;
        if (metric === "total_cost_bps" && q.fee_breakdown.gas_unknown) continue;
        values.push(metricValue(q, pair, sideView, metric));
      }
    }
    return heatRange(values);
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
                  const quote = quoteFromPair(pair, sideView);
                  const value = metricValue(quote, pair, sideView, metric);
                  const formatted =
                    value === null ? null : formatBps(value);
                  const isBest =
                    !isDisabled &&
                    highlightBest &&
                    best[n] === venue &&
                    quote?.status === "ok";

                  return (
                    <td key={n} className="px-0.5 py-0.5">
                      <StatusCell
                        quote={quote}
                        formattedMetric={
                          formatted === null ? null : `${formatted}`
                        }
                        metricKey={metric}
                        isBest={isBest}
                        heatClassName={
                          heat && !isDisabled && value !== null
                            ? heatClass(value, range)
                            : undefined
                        }
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

function quoteFromPair(
  pair: SizeQuotePair | undefined,
  sideView: SideView,
): Quote | null {
  if (!pair) return null;
  if (sideView === "buy") return pair.buy ?? null;
  if (sideView === "sell") return pair.sell ?? null;
  // round_trip: synthesize a pseudo-quote for status rendering from buy leg
  // status; metric comes from pair-level fields.
  const buy = pair.buy;
  const sell = pair.sell;
  if (!buy && !sell) return null;
  // Prefer buy for status chrome; metricValue handles RT numbers.
  return buy ?? sell ?? null;
}

function metricValue(
  quote: Quote | null,
  pair: SizeQuotePair | undefined,
  sideView: SideView,
  metric: MetricKey,
): number | null {
  if (sideView === "round_trip" && pair) {
    if (metric === "total_cost_bps") {
      return parseDecimal(pair.round_trip_total_cost_bps);
    }
    return parseDecimal(pair.round_trip_spread_bps);
  }
  if (!quote) return null;
  if (metric === "total_cost_bps") {
    return parseDecimal(quote.total_cost_bps);
  }
  return parseDecimal(quote.spread_bps);
}
