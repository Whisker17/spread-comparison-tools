"use client";

import type { SizeQuotePair } from "@/lib/api";
import {
  formatSnapshotSummary,
  type RankMetric,
  type SideView,
} from "@/lib/summary";
import { cn } from "@/lib/utils";

export type SnapshotSummaryProps = {
  pairs: readonly SizeQuotePair[];
  asset: string;
  side?: SideView;
  metric?: RankMetric;
  venues?: readonly string[];
  hiddenVenues?: readonly string[];
  /** Display labels for venue slugs in the prose. */
  venueLabels?: Readonly<Record<string, string>>;
  className?: string;
};

/**
 * Point-in-time narrative best-venue summary (WHI-809 Phase 1).
 * Ranking rule is shared with SummaryStrip / SpreadMatrix via lib/summary.ts.
 */
export function SnapshotSummary({
  pairs,
  asset,
  side = "buy",
  metric = "total_cost_bps",
  venues,
  hiddenVenues,
  venueLabels,
  className,
}: SnapshotSummaryProps) {
  const text = formatSnapshotSummary(pairs, {
    asset,
    side,
    metric,
    venues,
    hiddenVenues,
    venueLabels,
  });

  if (!text) {
    return null;
  }

  return (
    <div
      className={cn(
        "rounded-lg border border-emerald-200 bg-emerald-50/60 px-3 py-2.5 dark:border-emerald-900 dark:bg-emerald-950/30",
        className,
      )}
      data-testid="snapshot-summary"
    >
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <span className="text-[10px] font-medium uppercase tracking-wide text-emerald-800 dark:text-emerald-300">
          Snapshot summary
        </span>
        <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-emerald-700 dark:bg-emerald-900/60 dark:text-emerald-200">
          Point-in-time
        </span>
      </div>
      <p className="text-sm leading-relaxed text-zinc-800 dark:text-zinc-100">
        {text}
      </p>
    </div>
  );
}
