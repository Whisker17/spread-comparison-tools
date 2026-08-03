"use client";

import type { SizeQuotePair } from "@/lib/api";
import { formatBps, formatNotional } from "@/lib/format";
import {
  bestVenuePerTier,
  type BestVenueOptions,
  type RankMetric,
  type SideView,
} from "@/lib/summary";
import { cn } from "@/lib/utils";

export type SummaryStripProps = {
  pairs: readonly SizeQuotePair[];
  side?: SideView;
  metric?: RankMetric;
  venues?: readonly string[];
  hiddenVenues?: readonly string[];
  venueLabels?: Readonly<Record<string, string>>;
  className?: string;
};

/**
 * Best-venue-per-tier strip. Ranking rule lives in `lib/summary.ts` so
 * WHI-818 can swap the data source without forking the eligibility filter.
 */
export function SummaryStrip({
  pairs,
  side = "buy",
  metric = "total_cost_bps",
  venues,
  hiddenVenues,
  venueLabels,
  className,
}: SummaryStripProps) {
  const options: BestVenueOptions = { side, metric, venues, hiddenVenues };
  const picks = bestVenuePerTier(pairs, options);

  if (picks.length === 0) {
    return null;
  }

  return (
    <div
      className={cn(
        "flex flex-wrap gap-2 rounded-lg border border-zinc-200 bg-zinc-50 p-3 dark:border-zinc-800 dark:bg-zinc-900/40",
        className,
      )}
      data-testid="summary-strip"
    >
      <span className="w-full text-xs font-medium uppercase tracking-wide text-zinc-500">
        Best venue per tier ({side.replace("_", " ")} ·{" "}
        {metric.replace(/_/g, " ")})
      </span>
      {picks.map((pick) => (
        <div
          key={pick.notionalUsd}
          className="min-w-[7rem] rounded-md border border-zinc-200 bg-white px-2.5 py-1.5 dark:border-zinc-700 dark:bg-zinc-950"
          data-notional={pick.notionalUsd}
        >
          <div className="text-[10px] uppercase text-zinc-500">
            {formatNotional(pick.notionalUsd)}
          </div>
          {pick.empty ? (
            <div className="text-sm text-zinc-400">—</div>
          ) : (
            <>
              <div className="text-sm font-medium">
                {venueLabels?.[pick.venue] ?? pick.venue}
              </div>
              <div className="text-xs tabular-nums text-zinc-500">
                {formatBps(pick.valueBps)} bps
              </div>
            </>
          )}
        </div>
      ))}
    </div>
  );
}
