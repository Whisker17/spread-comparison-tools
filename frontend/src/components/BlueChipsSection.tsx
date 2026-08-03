"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { AssetSpreadBlock } from "@/components/AssetSpreadBlock";
import {
  blueChipsSection,
  buildVenueLabels,
  isOrderbookVenue,
  venueSummaryLabel,
} from "@/config/sections/blue-chips";
import { venuesForAsset } from "@/config/sections/helpers";
import { fetchAssets } from "@/lib/api";

/**
 * Full `/blue-chips` content: BTC / ETH / SOL blocks with live data (WHI-809).
 * Owns section-config helpers so AssetSpreadBlock stays section-agnostic.
 * Representation labels prefer GET /assets (backend SSOT) with static fallback.
 */
export function BlueChipsSection() {
  const section = blueChipsSection;

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
      </header>

      <div className="space-y-8">
        {section.assets.map((asset) => (
          <BlueChipAssetBlock
            key={asset}
            asset={asset}
            representationOverrides={repsByAsset.get(asset)}
          />
        ))}
      </div>

      <footer className="space-y-2 border-t border-zinc-200 pt-4 text-xs text-zinc-500 dark:border-zinc-800">
        <p>
          <strong className="font-medium text-zinc-700 dark:text-zinc-300">
            Representation labels.
          </strong>{" "}
          On-chain rows show the venue wrapper (e.g. cbBTC, WBTC, BTCB, Wormhole
          WETH, wSOL) — these are different assets with different bridge and peg
          risk, not bare BTC/ETH/SOL. Labels prefer{" "}
          <code className="text-[11px]">GET /assets</code> (backend catalog);
          cross-wrapper basis is not folded into total cost (WHI-798 §3.3).
        </p>
        <p>
          <strong className="font-medium text-zinc-700 dark:text-zinc-300">
            Quote currency.
          </strong>{" "}
          CEX and most USDT-settled perps are labeled USDT; Hyperliquid/Lighter
          and Solana prop AMM legs are typically USDC. Each venue row annotates
          the quote leg.
        </p>
        <p>
          <strong className="font-medium text-zinc-700 dark:text-zinc-300">
            SOL coverage.
          </strong>{" "}
          EVM public AMM and Tessera Base/BSC columns are hidden for SOL — no
          native SOL market on those venues (WHI-798 §3.1).
        </p>
        <p>
          <strong className="font-medium text-zinc-700 dark:text-zinc-300">
            Summary.
          </strong>{" "}
          Best-venue sentences are point-in-time only (status=ok and complete
          total_cost_bps; gas_unknown never wins — WHI-799 §5.2). Historical
          stats land in WHI-818.
        </p>
      </footer>
    </div>
  );
}

function BlueChipAssetBlock({
  asset,
  representationOverrides,
}: {
  asset: string;
  representationOverrides?: Readonly<Record<string, string>>;
}) {
  const section = blueChipsSection;
  const venues = useMemo(
    () => venuesForAsset(section, asset),
    [section, asset],
  );

  const venueLabels = useMemo(
    () =>
      buildVenueLabels(asset, venues, {
        representationOverrides,
      }),
    [asset, venues, representationOverrides],
  );

  const summaryVenueLabels = useMemo(() => {
    const out: Record<string, string> = {};
    for (const slug of venues) {
      out[slug] = venueSummaryLabel(slug, {
        asset,
        representationOverrides,
      });
    }
    return out;
  }, [venues, asset, representationOverrides]);

  const orderbookVenues = useMemo(
    () => venues.filter((v) => isOrderbookVenue(v)),
    [venues],
  );

  return (
    <AssetSpreadBlock
      section={section}
      asset={asset}
      venues={venues}
      venueLabels={venueLabels}
      summaryVenueLabels={summaryVenueLabels}
      orderbookVenues={orderbookVenues}
    />
  );
}
