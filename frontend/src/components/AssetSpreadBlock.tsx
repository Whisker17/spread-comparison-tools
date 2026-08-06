"use client";

/**
 * One logical asset: live single-notional matrix + TOB + snapshot summary.
 * Section-agnostic — callers pass venue order, labels, size view, and
 * orderbook rows so WHI-809/810/811 do not share section-config imports.
 *
 * WHI-864: fetch/subscribe only the displayed tier (one notional). Switching
 * size re-requests that tier (store + local books — no upstream fan-out).
 * Multi-notional ``GET /quotes?notionals=`` remains for API callers.
 */

import { Info, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";

import { SnapshotSummary } from "@/components/SnapshotSummary";
import { SpreadMatrix } from "@/components/SpreadMatrix";
import { TopOfBookRow } from "@/components/TopOfBookRow";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import type { SectionConfig } from "@/config/sections/types";
import { useQuotesMatrix } from "@/hooks/useQuotes";
import { useQuotesStreamOptional } from "@/hooks/useQuotesStream";
import type { InstrumentType, TopOfBook } from "@/lib/api";
import { formatNotional, formatTimestamp } from "@/lib/format";
import { notionalsForSizeView } from "@/lib/notionalSize";
import { pairRowKey, parseRowKey } from "@/lib/pairIdentity";
import type { SideView } from "@/lib/summary";
import { cn } from "@/lib/utils";
import {
  formatVenueSymbolNote,
  venueSymbolsFromPairs,
} from "@/lib/venue-symbols";

const SIDE_OPTIONS: { id: SideView; label: string }[] = [
  { id: "buy", label: "Buy" },
  { id: "sell", label: "Sell" },
  { id: "round_trip", label: "Round trip" },
];

export type AssetSpreadBlockProps = {
  section: SectionConfig;
  asset: string;
  /**
   * Selected tier USD string (WHI-864: one tier at a time). Parent owns
   * selection via SizeSelector + `?size=` URL. Fetch/subscribe covers only
   * this tier.
   */
  notional: string;
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
  /** Optional secondary line under the title (e.g. issuer / board note). */
  assetSubtitle?: string;
  /**
   * Short meta line under the title (e.g. "CEX + perp DEX").
   * Defaults to a generic multi-venue + selected size + side line.
   */
  subtitle?: string;
  /**
   * When true, mid-source is rendered as a prominent warning-style badge.
   * Pair with `midSourceHint` for section-specific tooltip copy — the shared
   * component must not hardcode product domain text (WHI-810 concurrent-PR rule).
   */
  emphasizeMidSource?: boolean;
  /** Tooltip / title text for the emphasized mid-source badge. */
  midSourceHint?: string;
  /**
   * When true, after quotes load, surface a venue_symbol contract note
   * (scaled memes). Uses Quote.venue_symbol only — no multiplier parsing.
   * Default false so other sections are unchanged.
   */
  showVenueSymbolNote?: boolean;
  /**
   * Display names for venue_symbol note prose (slug → short name).
   * Falls back to slug when omitted.
   */
  venueDisplayNames?: Readonly<Record<string, string>>;
  /**
   * Optional instrument_type override for `/quotes` (e.g. perp for equity
   * perps / scaled memes). Falls back to `section.instrumentType`, then
   * adapter default.
   */
  instrumentType?: InstrumentType;
  /**
   * Optional stock form filter for `/quotes` (WHI-881). Default = all live
   * forms on the backend for stock underlyings.
   */
  forms?: readonly string[];
  /**
   * Row keys dimmed and excluded from §5.2 best (WHI-892 non-live coverage).
   * Passed through to SpreadMatrix as disabledVenues.
   */
  disabledVenues?: readonly string[];
  /** Matrix first-column header (section product copy). */
  matrixRowHeaderLabel?: string;
  /** Extra best-highlight footnote (section product copy). */
  matrixBestNoteExtra?: string;
};

export function AssetSpreadBlock({
  section,
  asset,
  notional,
  venues,
  venueLabels,
  summaryVenueLabels,
  orderbookVenues: orderbookVenuesProp,
  assetTitle,
  assetSubtitle,
  subtitle,
  emphasizeMidSource = false,
  midSourceHint,
  showVenueSymbolNote = false,
  venueDisplayNames,
  instrumentType,
  forms,
  disabledVenues,
  matrixRowHeaderLabel,
  matrixBestNoteExtra,
}: AssetSpreadBlockProps) {
  const [sideView, setSideView] = useState<SideView>(section.defaultSideView);

  // WHI-864: fetch only the displayed tier (one notional).
  const displayNotionals = useMemo(
    () => notionalsForSizeView(notional, section.notionals),
    [notional, section.notionals],
  );

  // Row keys may be `venue|form` (stocks) — strip form for the venue filter.
  // Drop synthetic catalog summary venue (WHI-892); it is label-only.
  const venueSlugsForRequest = useMemo(() => {
    if (venues.length === 0) return undefined;
    const slugs = new Set(
      venues
        .map((k) => parseRowKey(k).venue)
        .filter((v) => v.length > 0 && v !== "catalog"),
    );
    return slugs.size > 0 ? [...slugs] : undefined;
  }, [venues]);

  // WHI-848: when a page-level QuotesStreamProvider is present, read pushed
  // state (zero GET /quotes polling). Otherwise fall back to HTTP poll for
  // isolated / fixture use.
  const stream = useQuotesStreamOptional();
  const useStream = stream !== null;
  const httpQuery = useQuotesMatrix({
    asset,
    notionals: displayNotionals,
    // Pin to the section venue set so we don't surface mock/other adapters.
    venues: venueSlugsForRequest,
    instrument_type: instrumentType ?? section.instrumentType,
    forms,
    // Disable HTTP poll when the page stream owns transport.
    refetchInterval: useStream ? false : section.pollIntervalMs,
    enabled: !useStream,
  });

  const streamData = useStream ? stream.matrixFor(asset) : undefined;
  const data = useStream ? streamData : httpQuery.data;
  const isLoading = useStream
    ? (stream.status === "connecting" || stream.status === "reconnecting") &&
      !streamData
    : httpQuery.isLoading;
  const isFetching = useStream
    ? stream.status === "connecting"
    : httpQuery.isFetching;
  const isError = useStream
    ? stream.status === "reconnecting" && !streamData && Boolean(stream.lastError)
    : httpQuery.isError;
  const errorMessage = useStream
    ? stream.lastError
    : httpQuery.error?.message ?? null;
  const refetch = () => {
    if (useStream) {
      stream.resnapshot([asset]);
      return;
    }
    void httpQuery.refetch();
  };
  const dataUpdatedAt = useStream
    ? streamData
      ? 1
      : 0
    : httpQuery.dataUpdatedAt;

  const pairs = useMemo(() => {
    const all = data?.pairs ?? [];
    const focus = displayNotionals[0];
    if (!focus) return all;
    return all.filter((p) => String(p.notional_usd) === focus);
  }, [data?.pairs, displayNotionals]);

  const orderbookVenues = useMemo(
    () => orderbookVenuesProp ?? venues,
    [orderbookVenuesProp, venues],
  );

  const tobByVenue = useMemo(() => {
    const map: Record<string, TopOfBook | null> = {};
    for (const v of orderbookVenues) map[v] = null;
    // Prefer TOB from the smallest notional row (same book snapshot per row).
    const ordered = [...(data?.pairs ?? [])].sort(
      (a, b) => Number(a.notional_usd) - Number(b.notional_usd),
    );
    for (const pair of ordered) {
      if (!pair.top_of_book) continue;
      const key = pairRowKey(pair);
      // Accept either form-aware row key or bare venue (crypto boards).
      if (
        Object.prototype.hasOwnProperty.call(map, key) &&
        map[key] === null
      ) {
        map[key] = pair.top_of_book;
      } else if (
        Object.prototype.hasOwnProperty.call(map, pair.venue) &&
        map[pair.venue] === null
      ) {
        map[pair.venue] = pair.top_of_book;
      }
    }
    return map;
  }, [data?.pairs, orderbookVenues]);

  const mid = data?.mids?.[0];
  // Mixed-age contract (WHI-846/848): do not assume one snapshot_id per asset.
  const snapshotIds = data?.snapshotIds ?? [];
  const snapshotIdLabel =
    snapshotIds.length === 0
      ? null
      : snapshotIds.length === 1
        ? snapshotIds[0]!
        : `${snapshotIds.length} ids`;

  // Prefer quote/mid timestamps from the payload over client clock.
  const snapshotTs = useMemo(() => {
    if (mid?.timestamp) return mid.timestamp;
    for (const p of pairs) {
      const q = p.buy ?? p.sell;
      if (q?.timestamp) return q.timestamp;
    }
    return null;
  }, [mid, pairs]);

  const contractNote = useMemo(() => {
    if (!showVenueSymbolNote) return null;
    const venueSlugs = venues.map((k) => parseRowKey(k).venue);
    const symbols = venueSymbolsFromPairs(pairs, venueSlugs);
    const names: Record<string, string> = {};
    for (const slug of venueSlugs) {
      names[slug] = venueDisplayNames?.[slug] ?? slug;
    }
    return formatVenueSymbolNote(asset, symbols, names);
  }, [showVenueSymbolNote, pairs, venues, venueDisplayNames, asset]);

  const proseLabels = summaryVenueLabels ?? venueLabels;
  const sizeLabel = formatNotional(notional);
  const subtitleText =
    subtitle ??
    `All venue classes · ${sizeLabel} · ${sideView.replace("_", " ")}`;

  // Cold load: isLoading. Warm size-focus still has data immediately.
  const showSkeleton = isLoading;

  return (
    <section
      className="space-y-4 rounded-xl border border-zinc-200 p-4 dark:border-zinc-800"
      data-testid={`asset-block-${asset}`}
      data-asset={asset}
      data-notional={notional}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-lg font-semibold tracking-tight">
              {assetTitle ?? asset}
            </h2>
            {contractNote ? (
              <Tooltip content={contractNote}>
                <button
                  type="button"
                  className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200"
                  data-testid={`venue-symbol-note-${asset}`}
                  aria-label={`Contract symbols for ${asset}`}
                >
                  <Info className="h-3 w-3" aria-hidden />
                  1× normalized
                </button>
              </Tooltip>
            ) : null}
          </div>
          {assetSubtitle ? (
            <p className="mt-0.5 text-xs text-zinc-600 dark:text-zinc-400">
              {assetSubtitle}
            </p>
          ) : null}
          <p className="mt-0.5 text-xs text-zinc-500">{subtitleText}</p>
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
            onClick={() => refetch()}
            disabled={isFetching}
            aria-label={
              useStream
                ? `Resnapshot ${asset} quotes`
                : `Refresh ${asset} quotes`
            }
          >
            <RefreshCw
              className={cn("h-3.5 w-3.5", isFetching && "animate-spin")}
            />
            {useStream ? "Resnapshot" : "Refresh"}
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
        ) : dataUpdatedAt > 0 ? (
          <span>
            Updated:{" "}
            <span className="tabular-nums text-zinc-700 dark:text-zinc-300">
              {new Date(dataUpdatedAt).toLocaleTimeString()}
            </span>
          </span>
        ) : null}
        {mid?.mid_source ? (
          emphasizeMidSource ? (
            <span
              className="inline-flex items-center gap-1.5 rounded-md border border-amber-300 bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-900 dark:border-amber-800 dark:bg-amber-950/50 dark:text-amber-100"
              data-testid={`mid-source-badge-${asset}`}
              title={midSourceHint}
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
        {snapshotIdLabel ? (
          <span
            className="max-w-[14rem] truncate"
            title={snapshotIds.join(", ")}
            data-testid={`snapshot-ids-${asset}`}
          >
            id
            {snapshotIds.length > 1 ? "s" : ""}:{" "}
            <code className="text-[10px]">
              {snapshotIds.length === 1
                ? `${snapshotIds[0]!.slice(0, 12)}…`
                : snapshotIdLabel}
            </code>
          </span>
        ) : null}
        {useStream ? (
          <span>Push stream</span>
        ) : section.pollIntervalMs ? (
          <span>
            Auto-refresh {Math.round(section.pollIntervalMs / 1000)}s
          </span>
        ) : null}
      </div>

      {showSkeleton && (
        <p className="text-sm text-zinc-500">
          Loading {asset} quotes ({sizeLabel})…
        </p>
      )}
      {isError && (
        <div className="rounded-md border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-200">
          <p className="font-medium">Failed to load {asset} quotes</p>
          <p className="mt-0.5 text-xs opacity-90">
            {errorMessage ?? "Unknown error"}. Is the backend running at{" "}
            <code>NEXT_PUBLIC_API_URL</code> (dev default http://localhost:8000)?
          </p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="mt-2"
            onClick={() => refetch()}
          >
            Retry
          </Button>
        </div>
      )}

      {!showSkeleton && !isError && (
        <>
          <SnapshotSummary
            pairs={pairs}
            asset={asset}
            side={sideView}
            metric={section.cellMetric}
            venues={venues}
            venueLabels={proseLabels}
            hiddenVenues={disabledVenues}
          />
          <SpreadMatrix
            pairs={pairs}
            notionals={displayNotionals}
            venues={venues}
            disabledVenues={disabledVenues}
            sideView={sideView}
            metric={section.cellMetric}
            venueLabels={venueLabels}
            showDetailColumns={true}
            onRetry={() => refetch()}
            rowHeaderLabel={matrixRowHeaderLabel}
            bestNoteExtra={matrixBestNoteExtra}
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
