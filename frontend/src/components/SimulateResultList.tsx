"use client";

import { AlertTriangle, ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import type { SimulateResponse, SimulateRowResponse } from "@/lib/api";
import {
  formatBps,
  formatDeltaVsBest,
  formatNotional,
  formatPrice,
  formatTimestamp,
} from "@/lib/format";
import {
  bestSimulateRow,
  deltaVsBest,
  feeBreakdownLines,
  partitionSimulateRows,
  referenceOutputRow,
  type VenueDisplayMeta,
} from "@/lib/simulateView";
import { cn } from "@/lib/utils";

export type SimulateResultListProps = {
  data: SimulateResponse | undefined;
  isLoading: boolean;
  /** Soft loading while a refresh is in flight but prior data is shown. */
  isRefreshing?: boolean;
  venueMeta: Readonly<Record<string, VenueDisplayMeta>>;
  /** Representation labels for the non-stable asset (slug → label). */
  representations?: Readonly<Record<string, string>>;
};

const SKELETON_COUNT = 6;

/** Ranked simulate rows + collapsed unavailable section (WHI-815). */
export function SimulateResultList({
  data,
  isLoading,
  isRefreshing = false,
  venueMeta,
  representations = {},
}: SimulateResultListProps) {
  if (isLoading && !data) {
    return <SkeletonList />;
  }

  if (!data) {
    // Error banner (if any) is rendered by the parent; avoid implying the form
    // is incomplete when the last request simply failed.
    return null;
  }

  const { ranked, notSupported } = partitionSimulateRows(data.rows);
  const best = bestSimulateRow(data.rows);
  const reference = referenceOutputRow(ranked, best);

  return (
    <div className="space-y-3" data-testid="simulate-results">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-zinc-500">
        <span>
          {data.side} {data.asset} · notional ≈ {formatNotional(data.notional_usd)}{" "}
          · mid {formatPrice(data.mid.mid)} ({data.mid.mid_source})
        </span>
        {isRefreshing && (
          <span className="text-amber-600 dark:text-amber-400">Refreshing…</span>
        )}
      </div>

      {ranked.length === 0 ? (
        <p className="text-sm text-zinc-500">No venue quotes returned.</p>
      ) : (
        <ul className="divide-y divide-zinc-200 overflow-hidden rounded-lg border border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800">
          {ranked.map((row) => (
            <SimulateResultRow
              key={`${row.venue}-${row.instrument_type}`}
              row={row}
              reference={reference}
              buyAsset={data.buy_asset}
              meta={venueMeta[row.venue]}
              representation={representations[row.venue]}
            />
          ))}
        </ul>
      )}

      {notSupported.length > 0 && (
        <UnavailableSection rows={notSupported} venueMeta={venueMeta} />
      )}
    </div>
  );
}

function SimulateResultRow({
  row,
  reference,
  buyAsset,
  meta,
  representation,
}: {
  row: SimulateRowResponse;
  reference: SimulateRowResponse | null;
  buyAsset: string;
  meta?: VenueDisplayMeta;
  representation?: string;
}) {
  const [open, setOpen] = useState(false);
  const delta = deltaVsBest(row, reference);
  const isBest = row.best === true;
  const isOk = row.status === "ok";
  const lines = feeBreakdownLines(row);
  const displayName = meta?.displayName ?? row.venue;

  return (
    <li
      className={cn(
        "bg-white dark:bg-zinc-950",
        isBest && "bg-emerald-50/80 dark:bg-emerald-950/30",
      )}
      data-testid={`simulate-row-${row.venue}`}
      data-best={isBest ? "true" : "false"}
      data-status={row.status}
    >
      <button
        type="button"
        className="flex w-full flex-col gap-2 px-3 py-3 text-left sm:flex-row sm:items-center sm:gap-4"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
          {open ? (
            <ChevronDown className="h-4 w-4 shrink-0 text-zinc-400" />
          ) : (
            <ChevronRight className="h-4 w-4 shrink-0 text-zinc-400" />
          )}
          <span className="font-medium text-zinc-900 dark:text-zinc-50">
            {displayName}
          </span>
          {isBest && (
            <Badge
              variant="default"
              className="bg-emerald-600 text-white"
              data-testid="best-badge"
            >
              Best
            </Badge>
          )}
          {meta?.classLabel && (
            <Badge variant="secondary">{meta.classLabel}</Badge>
          )}
          {meta?.chain && <Badge variant="outline">{meta.chain}</Badge>}
          {meta?.showRepresentation && representation && (
            <Badge variant="muted" title="Representation label">
              {representation}
            </Badge>
          )}
          {row.mid_stale && (
            <span
              className="inline-flex items-center gap-0.5 text-amber-600"
              title="mid stale"
              aria-label="mid stale"
            >
              <AlertTriangle className="h-3.5 w-3.5" />
            </span>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 pl-6 text-sm tabular-nums sm:pl-0">
          {isOk ? (
            <>
              <span className="min-w-[8rem] font-semibold">
                {formatPrice(row.expected_output)}{" "}
                <span className="text-xs font-normal text-zinc-500">
                  {buyAsset}
                </span>
              </span>
              <span
                className="min-w-[7rem] text-xs text-zinc-500"
                data-testid={`delta-${row.venue}`}
              >
                {formatDeltaVsBest(delta.absolute, delta.bps, buyAsset)}
              </span>
              <span className="text-xs text-zinc-500">
                px {formatPrice(row.effective_price)}
              </span>
              <span className="text-xs text-zinc-500">
                cost {formatBps(row.total_cost_bps)} bps
              </span>
            </>
          ) : (
            <StatusInline row={row} />
          )}
          {row.venue_symbol && (
            <span
              className="font-mono text-[11px] text-zinc-400"
              title="Venue symbol / contract"
            >
              {row.venue_symbol}
            </span>
          )}
          <span className="text-[11px] text-zinc-400">
            {formatTimestamp(row.timestamp)}
          </span>
        </div>
      </button>

      {open && (
        <div
          className="border-t border-zinc-100 bg-zinc-50/80 px-4 py-3 text-xs dark:border-zinc-800 dark:bg-zinc-900/40"
          data-testid={`breakdown-${row.venue}`}
        >
          <p className="mb-2 font-medium text-zinc-700 dark:text-zinc-200">
            Cost breakdown
          </p>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
            {lines.map((line) => (
              <div key={line.id} className="flex justify-between gap-2">
                <dt className="text-zinc-500">{line.label}</dt>
                <dd className="tabular-nums text-zinc-800 dark:text-zinc-100">
                  {line.unknown
                    ? "unknown"
                    : line.bps == null || line.bps === ""
                      ? "—"
                      : `${formatBps(line.bps)} bps`}
                  {line.note && (
                    <span className="ml-1 text-zinc-400">({line.note})</span>
                  )}
                </dd>
              </div>
            ))}
          </dl>
          {row.error_message && (
            <p className="mt-2 text-rose-600 dark:text-rose-400">
              {row.error_message}
              {row.error_code ? ` · ${row.error_code}` : ""}
            </p>
          )}
        </div>
      )}
    </li>
  );
}

function StatusInline({ row }: { row: SimulateRowResponse }) {
  if (row.status === "error") {
    return (
      <Badge variant="danger" data-testid={`status-${row.venue}`}>
        {row.error_code ?? "error"}
      </Badge>
    );
  }
  if (row.status === "insufficient_liquidity") {
    return <Badge variant="warning">insufficient liquidity</Badge>;
  }
  if (row.status === "no_quote" || row.status === "unsupported_asset") {
    return <span className="text-zinc-400">—</span>;
  }
  return <Badge variant="muted">{row.status}</Badge>;
}

function UnavailableSection({
  rows,
  venueMeta,
}: {
  rows: readonly SimulateRowResponse[];
  venueMeta: Readonly<Record<string, VenueDisplayMeta>>;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div
      className="rounded-lg border border-dashed border-zinc-300 dark:border-zinc-700"
      data-testid="unavailable-section"
    >
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-zinc-600 dark:text-zinc-300"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {open ? (
          <ChevronDown className="h-4 w-4" />
        ) : (
          <ChevronRight className="h-4 w-4" />
        )}
        Unavailable for this pair ({rows.length})
      </button>
      {open && (
        <ul className="space-y-1 border-t border-zinc-200 px-3 py-2 text-sm dark:border-zinc-800">
          {rows.map((r) => (
            <li
              key={r.venue}
              className="flex items-center gap-2 text-zinc-500"
              data-testid={`unavailable-${r.venue}`}
            >
              <span>{venueMeta[r.venue]?.displayName ?? r.venue}</span>
              <Badge variant="muted">not supported</Badge>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function SkeletonList() {
  return (
    <ul
      className="space-y-2"
      data-testid="simulate-skeleton"
      aria-busy="true"
      aria-label="Loading simulation results"
    >
      {Array.from({ length: SKELETON_COUNT }, (_, i) => (
        <li
          key={i}
          className="h-14 animate-pulse rounded-lg bg-zinc-100 dark:bg-zinc-900"
        />
      ))}
    </ul>
  );
}


