"use client";

import type { TopOfBook } from "@/lib/api";
import { formatBps, formatPrice } from "@/lib/format";
import { cn } from "@/lib/utils";

export type TopOfBookRowProps = {
  /** TOB snapshots keyed by venue slug (orderbook venues only). */
  byVenue: Readonly<Record<string, TopOfBook | null | undefined>>;
  /** Venue row order (same as matrix). Missing venues render empty. */
  venues: readonly string[];
  /** Optional display-name map. */
  venueLabels?: Readonly<Record<string, string>>;
  className?: string;
};

/**
 * TOB spread strip for orderbook venues. AMM / prop AMM never produce TOB
 * (WHI-799 §6.3) — those cells stay blank.
 */
export function TopOfBookRow({
  byVenue,
  venues,
  venueLabels,
  className,
}: TopOfBookRowProps) {
  return (
    <div className={cn("overflow-x-auto", className)}>
      <table className="w-full min-w-[28rem] border-collapse text-sm">
        <caption className="mb-2 text-left text-xs font-medium uppercase tracking-wide text-zinc-500">
          Top of book (orderbook venues)
        </caption>
        <thead>
          <tr className="border-b border-zinc-200 text-left text-xs text-zinc-500 dark:border-zinc-800">
            <th className="py-1.5 pr-3 font-medium">Venue</th>
            <th className="py-1.5 pr-3 font-medium">Bid</th>
            <th className="py-1.5 pr-3 font-medium">Ask</th>
            <th className="py-1.5 pr-3 font-medium">TOB spread</th>
          </tr>
        </thead>
        <tbody>
          {venues.map((slug) => {
            const tob = byVenue[slug];
            const label = venueLabels?.[slug] ?? slug;
            if (!tob) {
              return (
                <tr
                  key={slug}
                  className="border-b border-zinc-100 dark:border-zinc-900"
                >
                  <td className="py-1.5 pr-3 font-medium text-zinc-700 dark:text-zinc-200">
                    {label}
                  </td>
                  <td colSpan={3} className="py-1.5 text-zinc-400">
                    —
                  </td>
                </tr>
              );
            }
            return (
              <tr
                key={slug}
                className="border-b border-zinc-100 dark:border-zinc-900"
                data-venue={slug}
              >
                <td className="py-1.5 pr-3 font-medium text-zinc-700 dark:text-zinc-200">
                  {label}
                </td>
                <td className="py-1.5 pr-3 tabular-nums">
                  {formatPrice(tob.best_bid)}
                </td>
                <td className="py-1.5 pr-3 tabular-nums">
                  {formatPrice(tob.best_ask)}
                </td>
                <td className="py-1.5 pr-3 tabular-nums">
                  {formatBps(tob.spread_bps)} bps
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
