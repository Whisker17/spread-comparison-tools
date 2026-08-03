/**
 * Collect and format Quote.venue_symbol annotations (WHI-811 scaled memes).
 *
 * Backend already normalizes contract multipliers to 1× units. The UI only
 * surfaces the raw venue_symbol string — never parses a numeric multiplier
 * out of the symbol.
 */

import type { SizeQuotePair } from "@/lib/api";

/** First non-null venue_symbol per venue from quote pairs. */
export function venueSymbolsFromPairs(
  pairs: readonly SizeQuotePair[],
  venues?: readonly string[],
): Record<string, string> {
  const allowed =
    venues && venues.length > 0 ? new Set(venues) : null;
  const out: Record<string, string> = {};

  for (const pair of pairs) {
    if (allowed && !allowed.has(pair.venue)) continue;
    if (out[pair.venue]) continue;
    const q = pair.buy ?? pair.sell;
    const sym = q?.venue_symbol;
    if (typeof sym === "string" && sym.length > 0) {
      out[pair.venue] = sym;
    }
  }
  return out;
}

/**
 * Build prose like:
 * "Hyperliquid quotes kPEPE contracts; Binance quotes 1000PEPEUSDT;
 * prices shown normalized to 1× PEPE."
 */
export function formatVenueSymbolNote(
  asset: string,
  symbolsByVenue: Readonly<Record<string, string>>,
  venueDisplayNames: Readonly<Record<string, string>>,
): string | null {
  const entries = Object.entries(symbolsByVenue);
  if (entries.length === 0) return null;

  const clauses = entries.map(([slug, sym]) => {
    const name = venueDisplayNames[slug] ?? slug;
    return `${name} quotes ${sym} contracts`;
  });

  return `${clauses.join("; ")}; prices shown normalized to 1× ${asset.toUpperCase()}.`;
}
