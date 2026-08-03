"use client";

import { RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";

import { SpreadMatrix } from "@/components/SpreadMatrix";
import { SummaryStrip } from "@/components/SummaryStrip";
import { TopOfBookRow } from "@/components/TopOfBookRow";
import { Button } from "@/components/ui/button";
import type { SectionConfig } from "@/config/sections/types";
import { useQuotesMatrix } from "@/hooks/useQuotes";
import type { TopOfBook } from "@/lib/api";
import type { SideView } from "@/lib/summary";
import { cn } from "@/lib/utils";

const SIDE_OPTIONS: { id: SideView; label: string }[] = [
  { id: "buy", label: "Buy" },
  { id: "sell", label: "Sell" },
  { id: "round_trip", label: "Round trip" },
];

/**
 * Live demo widget: polls GET /quotes for one asset across configured notionals
 * and renders SpreadMatrix + optional TOB / summary. Used by /blue-chips scaffold.
 */
export function LiveSpreadDemo({
  section,
  asset,
}: {
  section: SectionConfig;
  asset: string;
}) {
  const [sideView, setSideView] = useState<SideView>(section.defaultSideView);

  const query = useQuotesMatrix({
    asset,
    notionals: section.notionals,
    venues: section.venues.length > 0 ? section.venues : undefined,
  });

  const pairs = useMemo(
    () => query.data?.pairs ?? [],
    [query.data?.pairs],
  );

  const venues = useMemo(() => {
    if (section.venues.length > 0) return [...section.venues];
    return [...new Set(pairs.map((p) => p.venue))].sort();
  }, [section.venues, pairs]);

  const tobByVenue = useMemo(() => {
    const map: Record<string, TopOfBook | null> = {};
    for (const v of venues) map[v] = null;
    // Prefer TOB from the smallest notional row (same book snapshot per venue).
    for (const pair of pairs) {
      if (pair.top_of_book && map[pair.venue] === null) {
        map[pair.venue] = pair.top_of_book;
      }
    }
    return map;
  }, [pairs, venues]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="text-sm">
          <span className="font-medium">{asset}</span>
          <span className="ml-2 text-zinc-500">
            live from <code className="text-xs">GET /quotes</code>
          </span>
        </div>
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
        >
          <RefreshCw
            className={cn("h-3.5 w-3.5", query.isFetching && "animate-spin")}
          />
          Refresh
        </Button>
        {query.dataUpdatedAt > 0 && (
          <span className="text-xs text-zinc-500">
            updated {new Date(query.dataUpdatedAt).toLocaleTimeString()}
          </span>
        )}
      </div>

      {query.isLoading && (
        <p className="text-sm text-zinc-500">Loading quotes…</p>
      )}
      {query.isError && (
        <div className="rounded-md border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-200">
          <p className="font-medium">Failed to load quotes</p>
          <p className="mt-0.5 text-xs opacity-90">
            {query.error.message}. Is the backend running on{" "}
            <code>NEXT_PUBLIC_API_URL</code> (default http://localhost:8000)?
          </p>
        </div>
      )}

      {!query.isLoading && !query.isError && (
        <>
          <SummaryStrip
            pairs={pairs}
            side={sideView}
            venues={section.venues.length > 0 ? section.venues : undefined}
            hiddenVenues={section.hiddenVenues}
          />
          <SpreadMatrix
            pairs={pairs}
            notionals={section.notionals}
            venues={section.venues.length > 0 ? section.venues : undefined}
            hiddenVenues={section.hiddenVenues}
            sideView={sideView}
            metric={section.cellMetric}
            onRetry={() => void query.refetch()}
          />
          {section.showTopOfBook && venues.length > 0 && (
            <TopOfBookRow byVenue={tobByVenue} venues={venues} />
          )}
        </>
      )}
    </div>
  );
}
