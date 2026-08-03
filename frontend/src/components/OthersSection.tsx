"use client";

import { useMemo } from "react";

import { AssetSpreadBlock } from "@/components/AssetSpreadBlock";
import {
  OTHER_ASSET_GROUPS,
  OTHER_P2_WATCHLIST,
  OTHER_VENUES,
  buildVenueLabels,
  isOrderbookVenue,
  otherVenuesDisplayList,
  otherVenuesQueryParam,
  othersSection,
  venueDisplayName,
  venueSummaryLabel,
  type OtherAssetGroup,
} from "@/config/sections/others";
import { venuesForAsset } from "@/config/sections/helpers";

/**
 * Full `/others` content: config-driven P0+P1 boards and a collapsed P2
 * watchlist (WHI-811). Venue filter is CEX + three perp DEXes only.
 */
export function OthersSection() {
  const section = othersSection;
  const venueList = otherVenuesDisplayList();
  const venueFilter = otherVenuesQueryParam();

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">{section.title}</h1>
        <p className="mt-1 max-w-3xl text-sm text-zinc-600 dark:text-zinc-400">
          {section.description}
        </p>
        <p className="mt-2 text-xs text-zinc-500">
          Venues: {venueList} ({OTHER_VENUES.length}-venue filter on every{" "}
          <code className="text-[11px]">/quotes</code> call). Prop AMM columns
          are omitted — coverage beyond blue chips is ≈ zero and would only burn
          Jupiter quota (WHI-798 §5). P0 uses CEX spot + perp DEX books; P1
          scaled memes force CEX perp so 1000× contracts surface.
        </p>
      </header>

      {OTHER_ASSET_GROUPS.map((group) => (
        <section
          key={group.id}
          className="space-y-8"
          aria-label={group.title}
        >
          <div>
            <h2 className="text-sm font-medium uppercase tracking-wide text-zinc-500">
              {group.title}
            </h2>
            {group.description ? (
              <p className="mt-1 text-xs text-zinc-500">{group.description}</p>
            ) : null}
          </div>
          {group.assets.map((asset) => (
            <OtherAssetBlock key={asset} asset={asset} group={group} />
          ))}
        </section>
      ))}

      <details
        className="rounded-xl border border-zinc-200 dark:border-zinc-800"
        data-testid="others-p2-watchlist"
      >
        <summary className="cursor-pointer select-none px-4 py-3 text-sm font-medium text-zinc-800 dark:text-zinc-100">
          P2 watchlist ({OTHER_P2_WATCHLIST.length}) — limited prop coverage,
          collapsed by default
        </summary>
        <div className="space-y-3 border-t border-zinc-200 px-4 py-4 dark:border-zinc-800">
          <p className="text-xs text-zinc-500">
            Observation labels only — no <code className="text-[11px]">/quotes</code>{" "}
            for these tickers (not on the Phase-1 CEX+perp board). Caveats document
            prop-side gaps.
          </p>
          <ul className="space-y-2">
            {OTHER_P2_WATCHLIST.map((row) => (
              <li
                key={row.id}
                className="rounded-lg border border-zinc-200 px-3 py-2 dark:border-zinc-800"
                data-testid={`watchlist-row-${row.id}`}
              >
                <div className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
                  {row.id}
                </div>
                <p className="mt-0.5 text-xs text-amber-800 dark:text-amber-200/90">
                  {row.caveat}
                </p>
              </li>
            ))}
          </ul>
        </div>
      </details>

      <footer className="space-y-2 border-t border-zinc-200 pt-4 text-xs text-zinc-500 dark:border-zinc-800">
        <p>
          <strong className="font-medium text-zinc-700 dark:text-zinc-300">
            Config-driven assets.
          </strong>{" "}
          Edit{" "}
          <code className="text-[11px]">OTHER_ASSET_GROUPS</code> /{" "}
          <code className="text-[11px]">OTHER_P2_WATCHLIST</code> in{" "}
          <code className="text-[11px]">config/sections/others.ts</code> — no
          component changes needed to add a ticker.
        </p>
        <p>
          <strong className="font-medium text-zinc-700 dark:text-zinc-300">
            No prop AMM.
          </strong>{" "}
          Every matrix pins{" "}
          <code className="text-[11px]">venues={venueFilter}</code>.
        </p>
        <p>
          <strong className="font-medium text-zinc-700 dark:text-zinc-300">
            Scaled contracts.
          </strong>{" "}
          PEPE / BONK use venue-specific contract sizes. Backend scales books to
          1× before bps; the UI only shows non-trivial{" "}
          <code className="text-[11px]">venue_symbol</code> values.
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
  group,
}: {
  asset: string;
  group: OtherAssetGroup;
}) {
  const section = othersSection;
  const preferPerp = group.preferPerp === true;
  const showNote = group.showVenueSymbolNote === true;

  const venues = useMemo(
    () => venuesForAsset(section, asset),
    [section, asset],
  );

  const venueLabels = useMemo(
    () =>
      buildVenueLabels(asset, venues, {
        instrument: preferPerp ? "perp" : undefined,
      }),
    [asset, venues, preferPerp],
  );

  const summaryVenueLabels = useMemo(() => {
    const out: Record<string, string> = {};
    for (const slug of venues) {
      out[slug] = venueSummaryLabel(slug, {
        instrument: preferPerp ? "perp" : "spot",
      });
    }
    return out;
  }, [venues, preferPerp]);

  const orderbookVenues = useMemo(
    () => venues.filter((v) => isOrderbookVenue(v)),
    [venues],
  );

  const displayNames = useMemo(() => {
    const out: Record<string, string> = {};
    for (const slug of venues) {
      out[slug] = venueDisplayName(slug);
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
      showVenueSymbolNote={showNote}
      venueDisplayNames={displayNames}
      instrumentType={preferPerp ? "perp" : undefined}
    />
  );
}
