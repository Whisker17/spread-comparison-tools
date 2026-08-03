"use client";

import { AssetSpreadBlock } from "@/components/AssetSpreadBlock";
import {
  blueChipsSection,
  hiddenVenuesForAsset,
  venuesForAsset,
} from "@/config/sections/blue-chips";

/**
 * Full `/blue-chips` content: BTC / ETH / SOL blocks with live data (WHI-809).
 */
export function BlueChipsSection() {
  const section = blueChipsSection;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">{section.title}</h1>
        <p className="mt-1 max-w-3xl text-sm text-zinc-600 dark:text-zinc-400">
          {section.description}
        </p>
      </header>

      <div className="space-y-8">
        {section.assets.map((asset) => {
          const venues = venuesForAsset(section, asset);
          const hidden = hiddenVenuesForAsset(section, asset);
          return (
            <AssetSpreadBlock
              key={asset}
              section={section}
              asset={asset}
              venues={venues}
              hiddenVenues={hidden}
            />
          );
        })}
      </div>

      <footer className="space-y-2 border-t border-zinc-200 pt-4 text-xs text-zinc-500 dark:border-zinc-800">
        <p>
          <strong className="font-medium text-zinc-700 dark:text-zinc-300">
            Representation labels.
          </strong>{" "}
          On-chain rows show the venue wrapper (e.g. cbBTC, WBTC, BTCB, wSOL) —
          these are different assets with different bridge and peg risk, not bare
          BTC/ETH/SOL. Cross-wrapper basis is not folded into total cost (WHI-798
          §3.3).
        </p>
        <p>
          <strong className="font-medium text-zinc-700 dark:text-zinc-300">
            Quote currency.
          </strong>{" "}
          CEX and perp legs are mostly USDT-settled; Solana prop AMM legs are
          typically USDC. Labels on each venue row annotate the quote leg.
        </p>
        <p>
          <strong className="font-medium text-zinc-700 dark:text-zinc-300">
            SOL coverage.
          </strong>{" "}
          EVM public AMM columns (Uniswap / Aerodrome / PancakeSwap) are hidden
          for SOL — no native SOL market on those venues.
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
