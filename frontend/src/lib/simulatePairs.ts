/**
 * Pair-picker constraints for `/simulate` (WHI-815).
 *
 * Pair legs come from GET /simulate/pairs (WHI-833): exactly one leg must be a
 * tradeable USD stable and the other a catalogued non-stable asset. No
 * hardcoded stablecoin list lives in the frontend.
 */

export type SimulatePairMeta = {
  stables: readonly string[];
  assets: readonly string[];
};

export type SimulatePair = {
  sell: string;
  buy: string;
};

function upper(s: string): string {
  return s.trim().toUpperCase();
}

function setOf(ids: readonly string[]): Set<string> {
  return new Set(ids.map(upper));
}

/** True when `symbol` is in the tradeable-stable list from the API. */
export function isTradeableStable(
  symbol: string,
  meta: SimulatePairMeta,
): boolean {
  return setOf(meta.stables).has(upper(symbol));
}

/** True when `symbol` is a catalogued non-stable asset. */
export function isCatalogAsset(
  symbol: string,
  meta: SimulatePairMeta,
): boolean {
  return setOf(meta.assets).has(upper(symbol));
}

/**
 * Exactly one leg is a tradeable stable and the other is a catalog asset.
 * Mirrors POST /simulate pair validation without reimplementing backend rules
 * beyond the UI-enforced construction constraint.
 */
export function isValidSimulatePair(
  sell: string,
  buy: string,
  meta: SimulatePairMeta,
): boolean {
  if (!sell || !buy) return false;
  if (upper(sell) === upper(buy)) return false;
  const sellStable = isTradeableStable(sell, meta);
  const buyStable = isTradeableStable(buy, meta);
  const sellAsset = isCatalogAsset(sell, meta);
  const buyAsset = isCatalogAsset(buy, meta);
  // One stable + one catalog asset (either direction).
  return (sellStable && buyAsset) || (sellAsset && buyStable);
}

/** Swap sell/buy legs. */
export function swapSimulatePair(pair: SimulatePair): SimulatePair {
  return { sell: pair.buy, buy: pair.sell };
}

/**
 * Default pair for first paint: prefer SOL→first stable, else first asset →
 * first stable. Empty meta yields empty strings (selectors stay disabled).
 */
export function defaultSimulatePair(meta: SimulatePairMeta): SimulatePair {
  const stables = meta.stables.map(upper).filter(Boolean);
  const assets = meta.assets.map(upper).filter(Boolean);
  if (stables.length === 0 || assets.length === 0) {
    return { sell: "", buy: "" };
  }
  const preferred = assets.find((a) => a === "SOL") ?? assets[0]!;
  return { sell: preferred, buy: stables[0]! };
}

/**
 * Apply a selector change while preserving the one-stable-leg invariant.
 *
 * When the user picks a stable on one side, the other side is forced to a
 * catalog asset (kept if still valid, else first asset). When they pick a
 * non-stable, the other side is forced to a tradeable stable.
 */
export function constrainSimulateSelection(
  current: SimulatePair,
  field: "sell" | "buy",
  value: string,
  meta: SimulatePairMeta,
): SimulatePair {
  const nextValue = upper(value);
  if (!nextValue) return current;

  const stables = meta.stables.map(upper).filter(Boolean);
  const assets = meta.assets.map(upper).filter(Boolean);
  if (stables.length === 0 || assets.length === 0) {
    return current;
  }

  const firstStable = stables[0]!;
  const firstAsset = assets[0]!;
  const keepAsset = (prefer: string) =>
    isCatalogAsset(prefer, meta) ? upper(prefer) : firstAsset;
  const keepStable = (prefer: string) =>
    isTradeableStable(prefer, meta) ? upper(prefer) : firstStable;

  if (field === "sell") {
    if (isTradeableStable(nextValue, meta)) {
      // Sell stable → buy must be catalog asset.
      return { sell: nextValue, buy: keepAsset(current.buy) };
    }
    if (isCatalogAsset(nextValue, meta)) {
      // Sell non-stable → buy must be tradeable stable.
      return { sell: nextValue, buy: keepStable(current.buy) };
    }
    return current;
  }

  // field === "buy"
  if (isTradeableStable(nextValue, meta)) {
    return { sell: keepAsset(current.sell), buy: nextValue };
  }
  if (isCatalogAsset(nextValue, meta)) {
    return { sell: keepStable(current.sell), buy: nextValue };
  }
  return current;
}

/**
 * Options offered on one selector given the other leg.
 *
 * The free leg may be any catalog asset when the fixed leg is a stable, and
 * any tradeable stable when the fixed leg is a non-stable. When the other
 * leg is empty/unknown, both lists are offered (union) so the UI can recover.
 */
export function selectorOptionsFor(
  otherLeg: string,
  meta: SimulatePairMeta,
): string[] {
  const stables = meta.stables.map(upper).filter(Boolean);
  const assets = meta.assets.map(upper).filter(Boolean);
  if (!otherLeg) {
    return [...stables, ...assets];
  }
  if (isTradeableStable(otherLeg, meta)) {
    return assets;
  }
  if (isCatalogAsset(otherLeg, meta)) {
    return stables;
  }
  return [...stables, ...assets];
}

/** Positive finite amount string suitable for POST /simulate. */
export function isValidSimulateAmount(raw: string): boolean {
  const t = raw.trim();
  if (!t) return false;
  const n = Number(t);
  return Number.isFinite(n) && n > 0;
}
