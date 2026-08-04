"use client";

import { useQuery } from "@tanstack/react-query";
import { Suspense, useMemo } from "react";

import { AssetSpreadBlock } from "@/components/AssetSpreadBlock";
import { SectionShellLoading } from "@/components/SectionShellLoading";
import { SizeSelector } from "@/components/SizeSelector";
import { UsMarketHoursIndicator } from "@/components/UsMarketHoursIndicator";
import {
  BSTOCKS_REBASE_FOOTNOTE,
  buildStocksVenueLabels,
  equityPerpsBoard,
  STOCK_ASSET_SUBTITLES,
  STOCK_ASSET_TITLES,
  STOCKS_MID_SOURCE_HINT,
  stocksPageHeader,
  stocksVenueSummaryLabel,
  tokenizedStocksBoard,
  type StocksBoardKind,
  type StocksLabelContext,
} from "@/config/sections/stocks";
import {
  isOrderbookVenue,
  venuesForAsset,
} from "@/config/sections/helpers";
import type { SectionConfig } from "@/config/sections/types";
import { useNotionalSize } from "@/hooks/useNotionalSize";
import { fetchAssets } from "@/lib/api";
import { formatNotional } from "@/lib/format";

/**
 * Full `/stocks` content (WHI-810): P0-A tokenized three-way + P0-B equity perps.
 * Owns section-config helpers so AssetSpreadBlock stays section-agnostic.
 *
 * WHI-841: one page-level size selector shared by both boards.
 * Boards must declare the same `notionals` / `defaultNotional` (asserted below).
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
  // Page-level `?size=` — both boards' SectionConfig fields must agree.
  if (
    process.env.NODE_ENV !== "production" &&
    (tokenizedStocksBoard.defaultNotional !==
      equityPerpsBoard.defaultNotional ||
      tokenizedStocksBoard.notionals.join(",") !==
        equityPerpsBoard.notionals.join(","))
  ) {
    console.warn(
      "[stocks] tokenized and equity boards disagree on size config; using tokenized board",
    );
  }
  const { notional, setNotional } = useNotionalSize({
    allowed: tokenizedStocksBoard.notionals,
    defaultNotional: tokenizedStocksBoard.defaultNotional,
  });

  const assetsQuery = useQuery({
    queryKey: ["assets"],
    queryFn: ({ signal }) => fetchAssets({ signal }),
    staleTime: 60_000,
  });

  const repsByAsset = useMemo(() => {
    const map = new Map<string, Readonly<Record<string, string>>>();
    for (const row of assetsQuery.data ?? []) {
      map.set(row.id.toUpperCase(), row.representations);
    }
    return map;
  }, [assetsQuery.data]);

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
            <SizeSelector
              tiers={tokenizedStocksBoard.notionals}
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
          spot TOB — WHI-799 §3.3). Each asset block highlights its mid source.
          Size{" "}
          <strong className="font-medium text-zinc-700 dark:text-zinc-300">
            {formatNotional(notional)}
          </strong>{" "}
          applies to both boards.
        </p>
      </header>

      <Board
        board={tokenizedStocksBoard}
        kind="tokenized"
        notional={notional}
        repsByAsset={repsByAsset}
        footnote={BSTOCKS_REBASE_FOOTNOTE}
      />

      <Board
        board={equityPerpsBoard}
        kind="equity_perp"
        notional={notional}
        repsByAsset={repsByAsset}
      />

      <footer className="space-y-2 border-t border-zinc-200 pt-4 text-xs text-zinc-500 dark:border-zinc-800">
        <p>
          <strong className="font-medium text-zinc-700 dark:text-zinc-300">
            Scope.
          </strong>{" "}
          P0-A is bStocks on BSC only. P0-B is exact-ticker equity perps — no
          SPY/QQQ Hyperliquid proxy rows (ETF cross-form is P1-lite). Cross-issuer
          basis (NVDAB / NVDAx / NVDAON) and xStocks paths are out of scope for
          this page (WHI-798 §4.5).
        </p>
        <p>
          <strong className="font-medium text-zinc-700 dark:text-zinc-300">
            Missing Tessera pools.
          </strong>{" "}
          Tessera BSC coverage is a subset of bStocks; a vanished pool returns{" "}
          <code className="text-[11px]">no_quote</code> and renders as &quot;—&quot;,
          not a page error.
        </p>
        <p>
          <strong className="font-medium text-zinc-700 dark:text-zinc-300">
            Summary.
          </strong>{" "}
          Best-venue sentences are point-in-time only at the selected size
          (status=ok and complete total_cost_bps; gas_unknown never wins —
          WHI-799 §5.2).
        </p>
      </footer>
    </div>
  );
}

function Board({
  board,
  kind,
  notional,
  repsByAsset,
  footnote,
}: {
  board: SectionConfig;
  kind: StocksBoardKind;
  notional: string;
  repsByAsset: Map<string, Readonly<Record<string, string>>>;
  footnote?: string;
}) {
  return (
    <section
      className="space-y-4"
      data-testid={`stocks-board-${kind}`}
      aria-labelledby={`stocks-board-${kind}-title`}
    >
      <div>
        <h2
          id={`stocks-board-${kind}-title`}
          className="text-lg font-semibold tracking-tight"
        >
          {board.title}
        </h2>
        <p className="mt-1 max-w-3xl text-sm text-zinc-600 dark:text-zinc-400">
          {board.description}
        </p>
        {footnote ? (
          <p
            className="mt-2 max-w-3xl rounded-md border border-sky-200 bg-sky-50/70 px-3 py-2 text-xs text-sky-950 dark:border-sky-900 dark:bg-sky-950/40 dark:text-sky-100"
            data-testid="bstocks-rebase-footnote"
            role="note"
          >
            <strong className="font-medium">bStocks rebase.</strong> {footnote}
          </p>
        ) : null}
      </div>

      <div className="space-y-8">
        {board.assets.map((asset) => (
          <StocksAssetBlock
            key={asset}
            board={board}
            kind={kind}
            asset={asset}
            notional={notional}
            representationOverrides={repsByAsset.get(asset)}
          />
        ))}
      </div>
    </section>
  );
}

function StocksAssetBlock({
  board,
  kind,
  asset,
  notional,
  representationOverrides,
}: {
  board: SectionConfig;
  kind: StocksBoardKind;
  asset: string;
  notional: string;
  representationOverrides?: Readonly<Record<string, string>>;
}) {
  const venues = useMemo(
    () => venuesForAsset(board, asset),
    [board, asset],
  );

  const labelContext: StocksLabelContext = useMemo(
    () => ({
      board: kind,
      asset,
      instrumentType: board.instrumentType,
      representationOverrides,
    }),
    [kind, asset, board.instrumentType, representationOverrides],
  );

  const venueLabels = useMemo(
    () => buildStocksVenueLabels(venues, labelContext),
    [venues, labelContext],
  );

  const summaryVenueLabels = useMemo(() => {
    const out: Record<string, string> = {};
    for (const slug of venues) {
      out[slug] = stocksVenueSummaryLabel(slug, labelContext);
    }
    return out;
  }, [venues, labelContext]);

  const orderbookVenues = useMemo(
    () => venues.filter((v) => isOrderbookVenue(v)),
    [venues],
  );

  return (
    <AssetSpreadBlock
      section={board}
      asset={asset}
      notional={notional}
      assetTitle={STOCK_ASSET_TITLES[asset] ?? asset}
      assetSubtitle={STOCK_ASSET_SUBTITLES[asset]}
      venues={venues}
      venueLabels={venueLabels}
      summaryVenueLabels={summaryVenueLabels}
      orderbookVenues={orderbookVenues}
      emphasizeMidSource
      midSourceHint={STOCKS_MID_SOURCE_HINT}
    />
  );
}
