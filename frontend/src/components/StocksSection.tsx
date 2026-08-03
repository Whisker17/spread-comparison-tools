"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { AssetSpreadBlock } from "@/components/AssetSpreadBlock";
import { UsMarketHoursIndicator } from "@/components/UsMarketHoursIndicator";
import {
  BSTOKS_REBASE_FOOTNOTE,
  buildStocksVenueLabels,
  equityPerpsBoard,
  isStocksOrderbookVenue,
  STOCK_ASSET_SUBTITLES,
  STOCK_ASSET_TITLES,
  stocksSection,
  stocksVenueSummaryLabel,
  tokenizedStocksBoard,
  type StocksBoardKind,
} from "@/config/sections/stocks";
import { venuesForAsset } from "@/config/sections/helpers";
import type { SectionConfig } from "@/config/sections/types";
import { fetchAssets } from "@/lib/api";

/**
 * Full `/stocks` content (WHI-810): P0-A tokenized three-way + P0-B equity perps.
 * Owns section-config helpers so AssetSpreadBlock stays section-agnostic.
 */
export function StocksSection() {
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
              {stocksSection.title}
            </h1>
            <p className="mt-1 max-w-3xl text-sm text-zinc-600 dark:text-zinc-400">
              {stocksSection.description}
            </p>
          </div>
          <UsMarketHoursIndicator />
        </div>
        <p className="max-w-3xl text-xs text-zinc-500">
          Reference mids for stocks use a weaker chain than crypto P0 (
          <code className="text-[11px]">cex_tradfi_index</code>,{" "}
          <code className="text-[11px]">proxy_perp_mark_median</code>, or CEX
          spot TOB — WHI-799 §3.3). Each asset block highlights its mid source.
        </p>
      </header>

      <Board
        board={tokenizedStocksBoard}
        kind="tokenized"
        repsByAsset={repsByAsset}
        footnote={BSTOKS_REBASE_FOOTNOTE}
      />

      <Board
        board={equityPerpsBoard}
        kind="equity_perp"
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
          Best-venue sentences are point-in-time only (status=ok and complete
          total_cost_bps; gas_unknown never wins — WHI-799 §5.2).
        </p>
      </footer>
    </div>
  );
}

function Board({
  board,
  kind,
  repsByAsset,
  footnote,
}: {
  board: SectionConfig;
  kind: StocksBoardKind;
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
  representationOverrides,
}: {
  board: SectionConfig;
  kind: StocksBoardKind;
  asset: string;
  representationOverrides?: Readonly<Record<string, string>>;
}) {
  const venues = useMemo(
    () => venuesForAsset(board, asset),
    [board, asset],
  );

  const venueLabels = useMemo(
    () =>
      buildStocksVenueLabels(asset, venues, {
        board: kind,
        representationOverrides,
      }),
    [asset, venues, kind, representationOverrides],
  );

  const summaryVenueLabels = useMemo(() => {
    const out: Record<string, string> = {};
    for (const slug of venues) {
      out[slug] = stocksVenueSummaryLabel(slug, {
        board: kind,
        asset,
        representationOverrides,
      });
    }
    return out;
  }, [venues, kind, asset, representationOverrides]);

  const orderbookVenues = useMemo(
    () => venues.filter((v) => isStocksOrderbookVenue(v)),
    [venues],
  );

  return (
    <AssetSpreadBlock
      section={board}
      asset={asset}
      assetTitle={STOCK_ASSET_TITLES[asset] ?? asset}
      assetSubtitle={STOCK_ASSET_SUBTITLES[asset]}
      venues={venues}
      venueLabels={venueLabels}
      summaryVenueLabels={summaryVenueLabels}
      orderbookVenues={orderbookVenues}
      emphasizeMidSource
    />
  );
}
