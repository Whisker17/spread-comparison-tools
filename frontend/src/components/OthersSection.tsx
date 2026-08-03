"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { AssetSpreadBlock } from "@/components/AssetSpreadBlock";
import {
  OTHER_P0_ASSETS,
  OTHER_P1_SCALED_ASSETS,
  OTHER_P2_WATCHLIST,
  OTHER_VENUE_META,
  buildVenueLabels,
  isOrderbookVenue,
  isScaledContractAsset,
  othersSection,
  venueSummaryLabel,
} from "@/config/sections/others";
import { venuesForAsset } from "@/config/sections/helpers";
import { fetchAssets } from "@/lib/api";

/**
 * Full `/others` content: P0 + scaled P1 boards and a collapsed P2 watchlist
 * (WHI-811). Venue filter is CEX + three perp DEXes only — never prop AMM.
 */
export function OthersSection() {
  const section = othersSection;

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
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">{section.title}</h1>
        <p className="mt-1 max-w-3xl text-sm text-zinc-600 dark:text-zinc-400">
          {section.description}
        </p>
        <p className="mt-2 text-xs text-zinc-500">
          Venues: Binance + Bybit (spot) · Hyperliquid · Lighter · ApeX. Prop
          AMM columns are omitted — coverage beyond blue chips is ≈ zero and
          would only burn Jupiter quota (WHI-798 §5).
        </p>
      </header>

      <section className="space-y-8" aria-label="P0 high-volume assets">
        <h2 className="text-sm font-medium uppercase tracking-wide text-zinc-500">
          P0 · high-volume intersection
        </h2>
        {OTHER_P0_ASSETS.map((asset) => (
          <OtherAssetBlock
            key={asset}
            asset={asset}
            representationOverrides={repsByAsset.get(asset)}
          />
        ))}
      </section>

      <section className="space-y-8" aria-label="P1 scaled memes">
        <div>
          <h2 className="text-sm font-medium uppercase tracking-wide text-zinc-500">
            P1 · scaled memes
          </h2>
          <p className="mt-1 text-xs text-zinc-500">
            Prices are backend-normalized to 1× units. Hover the badge for the
            raw venue contract symbol (
            <code className="text-[11px]">Quote.venue_symbol</code>
            ).
          </p>
        </div>
        {OTHER_P1_SCALED_ASSETS.map((asset) => (
          <OtherAssetBlock
            key={asset}
            asset={asset}
            representationOverrides={repsByAsset.get(asset)}
          />
        ))}
      </section>

      <details
        className="rounded-xl border border-zinc-200 dark:border-zinc-800"
        data-testid="others-p2-watchlist"
      >
        <summary className="cursor-pointer select-none px-4 py-3 text-sm font-medium text-zinc-800 dark:text-zinc-100">
          P2 watchlist ({OTHER_P2_WATCHLIST.length}) — limited prop coverage,
          collapsed by default
        </summary>
        <div className="space-y-6 border-t border-zinc-200 px-4 py-4 dark:border-zinc-800">
          <p className="text-xs text-zinc-500">
            Still quoted on CEX + perp DEX only. Caveats document prop-side
            gaps; this page never requests prop AMM venues.
          </p>
          {OTHER_P2_WATCHLIST.map((row) => (
            <OtherAssetBlock
              key={row.id}
              asset={row.id}
              representationOverrides={repsByAsset.get(row.id)}
              caveat={row.caveat}
            />
          ))}
        </div>
      </details>

      <footer className="space-y-2 border-t border-zinc-200 pt-4 text-xs text-zinc-500 dark:border-zinc-800">
        <p>
          <strong className="font-medium text-zinc-700 dark:text-zinc-300">
            No prop AMM.
          </strong>{" "}
          Asset list and venue filter are config-driven (
          <code className="text-[11px]">config/sections/others.ts</code>
          ). Adding a ticker does not require component edits.
        </p>
        <p>
          <strong className="font-medium text-zinc-700 dark:text-zinc-300">
            Scaled contracts.
          </strong>{" "}
          PEPE / BONK use venue-specific contract sizes (
          <code className="text-[11px]">1000PEPE</code>,{" "}
          <code className="text-[11px]">kPEPE</code>
          ). Backend scales books to 1× before bps; the UI only shows{" "}
          <code className="text-[11px]">venue_symbol</code>.
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

function OtherAssetBlock({
  asset,
  representationOverrides,
  caveat,
}: {
  asset: string;
  representationOverrides?: Readonly<Record<string, string>>;
  caveat?: string;
}) {
  const section = othersSection;
  const venues = useMemo(
    () => venuesForAsset(section, asset),
    [section, asset],
  );

  const venueLabels = useMemo(
    () =>
      buildVenueLabels(venues, {
        representationOverrides,
      }),
    [venues, representationOverrides],
  );

  const summaryVenueLabels = useMemo(() => {
    const out: Record<string, string> = {};
    for (const slug of venues) {
      out[slug] = venueSummaryLabel(slug);
    }
    return out;
  }, [venues]);

  const orderbookVenues = useMemo(
    () => venues.filter((v) => isOrderbookVenue(v)),
    [venues],
  );

  const venueDisplayNames = useMemo(() => {
    const out: Record<string, string> = {};
    for (const slug of venues) {
      out[slug] = OTHER_VENUE_META[slug]?.displayName ?? slug;
    }
    return out;
  }, [venues]);

  return (
    <AssetSpreadBlock
      section={section}
      asset={asset}
      venues={venues}
      venueLabels={venueLabels}
      summaryVenueLabels={summaryVenueLabels}
      orderbookVenues={orderbookVenues}
      subtitle={`CEX + perp DEX · ${section.notionals.length} notional tiers`}
      caveat={caveat}
      showVenueSymbolNote={isScaledContractAsset(asset)}
      venueDisplayNames={venueDisplayNames}
    />
  );
}
