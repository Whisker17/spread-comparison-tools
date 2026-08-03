"use client";

/**
 * One logical asset: live multi-notional matrix + TOB + snapshot summary.
 * Used by section pages (WHI-809+). Does not edit SpreadMatrix internals.
 */

import { RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";

import { SnapshotSummary } from "@/components/SnapshotSummary";
import { SpreadMatrix } from "@/components/SpreadMatrix";
import { SummaryStrip } from "@/components/SummaryStrip";
import { TopOfBookRow } from "@/components/TopOfBookRow";
import { Button } from "@/components/ui/button";
import {
  buildVenueLabels,
  isOrderbookVenue,
  venueSummaryLabel,
} from "@/config/sections/blue-chips";
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
  /** Venues hidden for this asset (SOL EVM AMMs, etc.). */
  hiddenVenues?: readonly string[];
};

export function AssetSpreadBlock({
  section,
  asset,
  venues,
  hiddenVenues = [],
}: AssetSpreadBlockProps) {
  const [sideView, setSideView] = useState<SideView>(section.defaultSideView);

  const pollMs =
    section.pollIntervalMs === undefined ? undefined : section.pollIntervalMs;

  const query = useQuotesMatrix({
    asset,
    notionals: section.notionals,
    // Pin to the section venue set so we don't surface mock/other adapters.
    venues: venues.length > 0 ? venues : undefined,
    refetchInterval: pollMs === undefined ? undefined : pollMs,
  });

  const pairs = useMemo(() => query.data?.pairs ?? [], [query.data?.pairs]);

  const instrumentByVenue = useMemo(() => {
    const map: Record<string, string> = {};
    for (const p of pairs) {
      if (p.instrument_type && map[p.venue] === undefined) {
        map[p.venue] = p.instrument_type;
      }
    }
    return map;
  }, [pairs]);

  const venueLabels = useMemo(
    () => buildVenueLabels(asset, venues, instrumentByVenue),
    [asset, venues, instrumentByVenue],
  );

  /** Labels for summary prose — shorter, with instrument annotation. */
  const summaryVenueLabels = useMemo(() => {
    const out: Record<string, string> = {};
    for (const slug of venues) {
      out[slug] = venueSummaryLabel(slug, instrumentByVenue[slug]);
    }
    return out;
  }, [venues, instrumentByVenue]);

  const orderbookVenues = useMemo(
    () => venues.filter((v) => isOrderbookVenue(v)),
    [venues],
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

  return (
    <section
      className="space-y-4 rounded-xl border border-zinc-200 p-4 dark:border-zinc-800"
      data-testid={`asset-block-${asset}`}
      data-asset={asset}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">{asset}</h2>
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
            <time dateTime={snapshotTs} className="tabular-nums text-zinc-700 dark:text-zinc-300">
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
          <span>
            Mid source:{" "}
            <code className="rounded bg-zinc-100 px-1 py-0.5 text-[11px] text-zinc-700 dark:bg-zinc-900 dark:text-zinc-300">
              {mid.mid_source}
            </code>
          </span>
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
          <span className="truncate max-w-[12rem]" title={snapshotId}>
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
            hiddenVenues={hiddenVenues}
            venueLabels={summaryVenueLabels}
          />
          <SummaryStrip
            pairs={pairs}
            side={sideView}
            metric={section.cellMetric}
            venues={venues}
            hiddenVenues={hiddenVenues}
            venueLabels={summaryVenueLabels}
          />
          <SpreadMatrix
            pairs={pairs}
            notionals={section.notionals}
            venues={venues}
            hiddenVenues={hiddenVenues}
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
