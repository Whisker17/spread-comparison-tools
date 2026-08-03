"use client";

/**
 * One logical asset: live multi-notional matrix + TOB + snapshot summary.
 * Section-agnostic — callers pass venue order, labels, and orderbook rows
 * so WHI-809/810/811 do not share section-config imports (parallel-safety).
 */

import { RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";

import { SnapshotSummary } from "@/components/SnapshotSummary";
import { SpreadMatrix } from "@/components/SpreadMatrix";
import { TopOfBookRow } from "@/components/TopOfBookRow";
import { Button } from "@/components/ui/button";
import type { SectionConfig } from "@/config/sections/types";
import { useQuotesMatrix } from "@/hooks/useQuotes";
import type { TopOfBook } from "@/lib/api";
import { formatTimestamp } from "@/lib/format";
import type { SideView } from "@/lib/summary";
import { cn } from "@/lib/utils";

const SIDE_OPTIONS: { id: SideView; label: string }[] = [
  { id: "buy", label: "Buy" },
  { id: "sell", label: "Sell" },
  { id: "round_trip", label: "Round trip" },
];

export type AssetSpreadBlockProps = {
  section: SectionConfig;
  asset: string;
  /** Visible venue row order (already filtered for this asset). */
  venues: readonly string[];
  /** Matrix / TOB row labels keyed by venue slug. */
  venueLabels: Readonly<Record<string, string>>;
  /** Shorter labels for snapshot summary prose. */
  summaryVenueLabels?: Readonly<Record<string, string>>;
  /** Subset of `venues` that can produce TopOfBook (orderbook classes). */
  orderbookVenues?: readonly string[];
  /**
   * Optional display title (defaults to `asset`). Sections use this for
   * annotations like "NVDAON · Ondo" without branching on section id.
   */
  assetTitle?: string;
  /** Optional secondary line under the title. */
  assetSubtitle?: string;
  /**
   * When true, mid-source is rendered as a prominent warning-style badge
   * (stocks mid chain is weaker than crypto P0 — WHI-799 §3.3 / WHI-810).
   */
  emphasizeMidSource?: boolean;
};

export function AssetSpreadBlock({
  section,
  asset,
  venues,
  venueLabels,
  summaryVenueLabels,
  orderbookVenues: orderbookVenuesProp,
  assetTitle,
  assetSubtitle,
  emphasizeMidSource = false,
}: AssetSpreadBlockProps) {
  const [sideView, setSideView] = useState<SideView>(section.defaultSideView);

  const query = useQuotesMatrix({
    asset,
    notionals: section.notionals,
    // Pin to the section venue set so we don't surface mock/other adapters.
    venues: venues.length > 0 ? venues : undefined,
    refetchInterval: section.pollIntervalMs,
  });

  const pairs = useMemo(() => query.data?.pairs ?? [], [query.data?.pairs]);

  const orderbookVenues = useMemo(
    () => orderbookVenuesProp ?? venues,
    [orderbookVenuesProp, venues],
  );

  const tobByVenue = useMemo(() => {
    const map: Record<string, TopOfBook | null> = {};
    for (const v of orderbookVenues) map[v] = null;
    // Prefer TOB from the smallest notional row (same book snapshot per venue).
    const ordered = [...pairs].sort(
      (a, b) => Number(a.notional_usd) - Number(b.notional_usd),
    );
    for (const pair of ordered) {
      if (
        pair.top_of_book &&
        Object.prototype.hasOwnProperty.call(map, pair.venue) &&
        map[pair.venue] === null
      ) {
        map[pair.venue] = pair.top_of_book;
      }
    }
    return map;
  }, [pairs, orderbookVenues]);

  const mid = query.data?.mids?.[0];
  const snapshotId = query.data?.snapshotIds?.[0];

  // Prefer quote/mid timestamps from the payload over client clock.
  const snapshotTs = useMemo(() => {
    if (mid?.timestamp) return mid.timestamp;
    for (const p of pairs) {
      const q = p.buy ?? p.sell;
      if (q?.timestamp) return q.timestamp;
    }
    return null;
  }, [mid, pairs]);

  const proseLabels = summaryVenueLabels ?? venueLabels;
  const pollMs = section.pollIntervalMs;

  return (
    <section
      className="space-y-4 rounded-xl border border-zinc-200 p-4 dark:border-zinc-800"
      data-testid={`asset-block-${asset}`}
      data-asset={asset}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">
            {assetTitle ?? asset}
          </h2>
          {assetSubtitle ? (
            <p className="mt-0.5 text-xs text-zinc-600 dark:text-zinc-400">
              {assetSubtitle}
            </p>
          ) : null}
          <p className="mt-0.5 text-xs text-zinc-500">
            All venue classes · {section.notionals.length} notional tiers ·{" "}
            {sideView.replace("_", " ")}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1 rounded-md border border-zinc-200 p-0.5 dark:border-zinc-700">
            {SIDE_OPTIONS.map((opt) => (
              <button
                key={opt.id}
                type="button"
                onClick={() => setSideView(opt.id)}
                className={cn(
                  "rounded px-2 py-1 text-xs",
                  sideView === opt.id
                    ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                    : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800",
                )}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void query.refetch()}
            disabled={query.isFetching}
            aria-label={`Refresh ${asset} quotes`}
          >
            <RefreshCw
              className={cn("h-3.5 w-3.5", query.isFetching && "animate-spin")}
            />
            Refresh
          </Button>
        </div>
      </div>

      {/* Snapshot meta: mid source + timestamp */}
      <div
        className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-500"
        data-testid={`snapshot-meta-${asset}`}
      >
        {snapshotTs ? (
          <span>
            Snapshot:{" "}
            <time
              dateTime={snapshotTs}
              className="tabular-nums text-zinc-700 dark:text-zinc-300"
            >
              {formatTimestamp(snapshotTs)}
            </time>
          </span>
        ) : query.dataUpdatedAt > 0 ? (
          <span>
            Updated:{" "}
            <span className="tabular-nums text-zinc-700 dark:text-zinc-300">
              {new Date(query.dataUpdatedAt).toLocaleTimeString()}
            </span>
          </span>
        ) : null}
        {mid?.mid_source ? (
          emphasizeMidSource ? (
            <span
              className="inline-flex items-center gap-1.5 rounded-md border border-amber-300 bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-900 dark:border-amber-800 dark:bg-amber-950/50 dark:text-amber-100"
              data-testid={`mid-source-badge-${asset}`}
              title="Stock mid sources (cex_tradfi_index / proxy_perp_mark_median / CEX spot TOB) are weaker than crypto P0 index mids (WHI-799 §3.3)."
            >
              <span className="uppercase tracking-wide opacity-80">
                Mid source
              </span>
              <code className="rounded bg-amber-100/80 px-1 py-px text-[11px] dark:bg-amber-900/60">
                {mid.mid_source}
              </code>
            </span>
          ) : (
            <span>
              Mid source:{" "}
              <code className="rounded bg-zinc-100 px-1 py-0.5 text-[11px] text-zinc-700 dark:bg-zinc-900 dark:text-zinc-300">
                {mid.mid_source}
              </code>
            </span>
          )
        ) : null}
        {mid?.mid !== undefined && mid?.mid !== null ? (
          <span>
            Mid:{" "}
            <span className="tabular-nums text-zinc-700 dark:text-zinc-300">
              {String(mid.mid)}
            </span>
          </span>
        ) : null}
        {snapshotId ? (
          <span className="max-w-[12rem] truncate" title={snapshotId}>
            id: <code className="text-[10px]">{snapshotId.slice(0, 12)}…</code>
          </span>
        ) : null}
        {pollMs ? (
          <span>Auto-refresh {Math.round(pollMs / 1000)}s</span>
        ) : null}
      </div>

      {query.isLoading && (
        <p className="text-sm text-zinc-500">Loading {asset} quotes…</p>
      )}
      {query.isError && (
        <div className="rounded-md border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-200">
          <p className="font-medium">Failed to load {asset} quotes</p>
          <p className="mt-0.5 text-xs opacity-90">
            {query.error.message}. Is the backend running on{" "}
            <code>NEXT_PUBLIC_API_URL</code> (default http://localhost:8000)?
          </p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="mt-2"
            onClick={() => void query.refetch()}
          >
            Retry
          </Button>
        </div>
      )}

      {!query.isLoading && !query.isError && (
        <>
          <SnapshotSummary
            pairs={pairs}
            asset={asset}
            side={sideView}
            metric={section.cellMetric}
            venues={venues}
            venueLabels={proseLabels}
          />
          <SpreadMatrix
            pairs={pairs}
            notionals={section.notionals}
            venues={venues}
            sideView={sideView}
            metric={section.cellMetric}
            venueLabels={venueLabels}
            onRetry={() => void query.refetch()}
          />
          {section.showTopOfBook && orderbookVenues.length > 0 && (
            <TopOfBookRow
              byVenue={tobByVenue}
              venues={orderbookVenues}
              venueLabels={venueLabels}
            />
          )}
        </>
      )}
    </section>
  );
}
