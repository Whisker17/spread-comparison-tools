"use client";

import { useQuery } from "@tanstack/react-query";
import { Suspense, useMemo } from "react";

import { AssetSpreadBlock } from "@/components/AssetSpreadBlock";
import { SectionShellLoading } from "@/components/SectionShellLoading";
import { SizeSelector } from "@/components/SizeSelector";
import { StreamStatusBadge } from "@/components/StreamStatusBadge";
import { UsMarketHoursIndicator } from "@/components/UsMarketHoursIndicator";
import {
  BSTOCKS_REBASE_FOOTNOTE,
  buildStockMatrixRows,
  buildStocksVenueLabels,
  hasBstockForm,
  orderbookRows,
  resolveStockForms,
  STOCK_ASSET_SUBTITLES,
  STOCK_UNDERLYINGS,
  STOCKS_BEST_NOTE,
  STOCKS_MATRIX_ROW_HEADER,
  STOCKS_MID_SOURCE_HINT,
  stocksBoard,
  stocksPageHeader,
  stocksVenueSummaryLabels,
  venuesFromForms,
  type StockFormDef,
} from "@/config/sections/stocks";
import { useNotionalSize } from "@/hooks/useNotionalSize";
import {
  QuotesStreamProvider,
  useQuotesStream,
} from "@/hooks/useQuotesStream";
import { fetchAssets } from "@/lib/api";
import { formatNotional } from "@/lib/format";
import type { StreamFilter } from "@/lib/streamQuotes";

/**
 * Full `/stocks` content (WHI-882): one matrix per underlying, rows =
 * venue × form sharing a single mid.
 *
 * WHI-841: page-level size selector.
 * WHI-848: one WebSocket with all underlyings (no instrument_type pin —
 * backend expands live forms via form_class).
 */
export function StocksSection() {
  return (
    <Suspense
      fallback={<SectionShellLoading title={stocksPageHeader.title} />}
    >
      <StocksSectionInner />
    </Suspense>
  );
}

function StocksSectionInner() {
  const { notional, setNotional } = useNotionalSize({
    allowed: stocksBoard.notionals,
    defaultNotional: stocksBoard.defaultNotional,
  });

  const assetsQuery = useQuery({
    queryKey: ["assets"],
    queryFn: ({ signal }) => fetchAssets({ signal }),
    staleTime: 60_000,
  });

  const formsByUnderlying = useMemo(() => {
    const map = new Map<string, StockFormDef[]>();
    for (const underlying of STOCK_UNDERLYINGS) {
      map.set(underlying, resolveStockForms(underlying, assetsQuery.data));
    }
    return map;
  }, [assetsQuery.data]);

  const streamFilters = useMemo<StreamFilter[]>(() => {
    // Single filter: all underlyings, all live-form venues, no instrument pin.
    const venueSet = new Set<string>();
    for (const forms of formsByUnderlying.values()) {
      for (const v of venuesFromForms(forms)) {
        venueSet.add(v);
      }
    }
    return [
      {
        assets: [...STOCK_UNDERLYINGS],
        // WHI-864: subscribe only the visible tier.
        notionals: [notional],
        venues: [...venueSet],
        // Default forms = all live (backend); omit instrument_type so form
        // expansion picks spot vs perp per form_class (WHI-881).
      },
    ];
  }, [notional, formsByUnderlying]);

  return (
    <QuotesStreamProvider filters={streamFilters}>
      <StocksStreamBody
        notional={notional}
        setNotional={setNotional}
        formsByUnderlying={formsByUnderlying}
      />
    </QuotesStreamProvider>
  );
}

function StocksStreamBody({
  notional,
  setNotional,
  formsByUnderlying,
}: {
  notional: string;
  setNotional: (v: string) => void;
  formsByUnderlying: Map<string, StockFormDef[]>;
}) {
  const stream = useQuotesStream();

  return (
    <div className="space-y-8">
      <header className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">
              {stocksPageHeader.title}
            </h1>
            <p className="mt-1 max-w-3xl text-sm text-zinc-600 dark:text-zinc-400">
              {stocksPageHeader.description}
            </p>
          </div>
          <div className="flex flex-wrap items-start gap-3">
            <StreamStatusBadge status={stream.status} />
            <SizeSelector
              tiers={stocksBoard.notionals}
              value={notional}
              onChange={setNotional}
            />
            <UsMarketHoursIndicator />
          </div>
        </div>
        <p className="max-w-3xl text-xs text-zinc-500">
          Reference mids for stocks use a weaker chain than crypto P0 (
          <code className="text-[11px]">cex_tradfi_index</code>,{" "}
          <code className="text-[11px]">proxy_perp_mark_median</code>, or CEX
          spot TOB — WHI-799 §3.3). All forms of an underlying share one mid so
          bps are comparable. Size{" "}
          <strong className="font-medium text-zinc-700 dark:text-zinc-300">
            {formatNotional(notional)}
          </strong>{" "}
          applies to every board over one live WebSocket (WHI-848).
        </p>
      </header>

      <div className="space-y-8" data-testid="stocks-boards">
        {STOCK_UNDERLYINGS.map((underlying) => {
          const forms = formsByUnderlying.get(underlying) ?? [];
          return (
            <UnderlyingBoard
              key={underlying}
              underlying={underlying}
              forms={forms}
              notional={notional}
            />
          );
        })}
      </div>

      <footer className="space-y-2 border-t border-zinc-200 pt-4 text-xs text-zinc-500 dark:border-zinc-800">
        <p>
          <strong className="font-medium text-zinc-700 dark:text-zinc-300">
            Forms.
          </strong>{" "}
          Each row is a (venue, form) pair — e.g. NVDA shows equity perps and
          bStocks / Ondo token rows in one table. Form badges (Perp / bStocks /
          Ondo / xStocks) distinguish issuers when the same venue lists two
          forms (tessera_bsc × NVDAB vs NVDAon).
        </p>
        <p>
          <strong className="font-medium text-zinc-700 dark:text-zinc-300">
            Best.
          </strong>{" "}
          Snapshot best is grouped by form_class (perp vs tokenized) per
          WHI-799 §5.2 — a cheap perp path does not silence a tokenized winner.
          Eligibility still requires status=ok and complete total_cost_bps
          (gas_unknown never wins).
        </p>
        <p>
          <strong className="font-medium text-zinc-700 dark:text-zinc-300">
            Missing pools.
          </strong>{" "}
          Tessera / Pancake coverage is a subset of listed forms; a vanished
          pool returns <code className="text-[11px]">no_quote</code> and
          renders as &quot;—&quot;, not a page error.
        </p>
      </footer>
    </div>
  );
}

function UnderlyingBoard({
  underlying,
  forms,
  notional,
}: {
  underlying: string;
  forms: readonly StockFormDef[];
  notional: string;
}) {
  const rows = useMemo(() => buildStockMatrixRows(forms), [forms]);
  const rowKeys = useMemo(() => rows.map((r) => r.rowKey), [rows]);
  const venueLabels = useMemo(() => buildStocksVenueLabels(rows), [rows]);
  const summaryLabels = useMemo(
    () => stocksVenueSummaryLabels(rows),
    [rows],
  );
  const orderbookRowKeys = useMemo(
    () => orderbookRows(rows).map((r) => r.rowKey),
    [rows],
  );
  const formIds = useMemo(() => forms.map((f) => f.id), [forms]);
  const showBstockNote = hasBstockForm(forms);

  return (
    <section
      className="space-y-3"
      data-testid={`stocks-board-${underlying}`}
      data-forms={formIds.join(",")}
      aria-labelledby={`stocks-board-${underlying}-title`}
    >
      {showBstockNote ? (
        <p
          className="max-w-3xl rounded-md border border-sky-200 bg-sky-50/70 px-3 py-2 text-xs text-sky-950 dark:border-sky-900 dark:bg-sky-950/40 dark:text-sky-100"
          data-testid="bstocks-rebase-footnote"
          role="note"
        >
          <strong className="font-medium">bStocks rebase.</strong>{" "}
          {BSTOCKS_REBASE_FOOTNOTE}
        </p>
      ) : null}
      <div className="sr-only" id={`stocks-board-${underlying}-title`}>
        {underlying}
      </div>
      {rowKeys.length === 0 ? (
        <div
          className="rounded-xl border border-dashed border-zinc-300 p-4 dark:border-zinc-700"
          data-testid={`asset-block-${underlying}`}
          data-asset={underlying}
        >
          <h2 className="text-lg font-semibold tracking-tight">{underlying}</h2>
          {STOCK_ASSET_SUBTITLES[underlying] ? (
            <p className="mt-0.5 text-xs text-zinc-600 dark:text-zinc-400">
              {STOCK_ASSET_SUBTITLES[underlying]}
            </p>
          ) : null}
          <p
            className="mt-2 text-sm text-zinc-500"
            data-testid={`no-live-forms-${underlying}`}
          >
            No live forms in the catalog for this underlying — nothing to quote.
          </p>
        </div>
      ) : (
        <AssetSpreadBlock
          section={stocksBoard}
          asset={underlying}
          notional={notional}
          assetTitle={underlying}
          assetSubtitle={STOCK_ASSET_SUBTITLES[underlying]}
          venues={rowKeys}
          venueLabels={venueLabels}
          summaryVenueLabels={summaryLabels}
          orderbookVenues={orderbookRowKeys}
          forms={formIds}
          emphasizeMidSource
          midSourceHint={STOCKS_MID_SOURCE_HINT}
          matrixRowHeaderLabel={STOCKS_MATRIX_ROW_HEADER}
          matrixBestNoteExtra={STOCKS_BEST_NOTE}
        />
      )}
    </section>
  );
}
