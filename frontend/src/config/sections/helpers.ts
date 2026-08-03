import type {
  SectionConfig,
  VenueClass,
  VenueMeta,
} from "@/config/sections/types";
import type { InstrumentType } from "@/lib/api";

/**
 * Shared section helpers for WHI-809/810/811.
 * Lives outside any one section module so concurrent section PRs can share
 * venue metadata, label rendering, and filtering without importing a
 * sibling section's config.
 */

/** Orderbook venue classes that can produce TopOfBook (WHI-799 §6.3). */
export const ORDERBOOK_VENUE_CLASSES: ReadonlySet<VenueClass> = new Set([
  "cex",
  "perp_dex",
]);

/** On-chain venue classes that need wrapper / token representation labels. */
export const ON_CHAIN_VENUE_CLASSES: ReadonlySet<VenueClass> = new Set([
  "amm_dex",
  "prop_amm",
]);

/**
 * Human labels for venue classes — single map for fees table, simulate rows,
 * and any other chrome that shows a class badge.
 */
export const VENUE_CLASS_LABELS: Readonly<Record<VenueClass | "unknown", string>> =
  {
    cex: "CEX",
    perp_dex: "Perp DEX",
    amm_dex: "Public AMM",
    prop_amm: "Prop AMM",
    mock: "Mock",
    unknown: "Other",
  };

/**
 * Single venue metadata registry for every section (WHI-809/810/811).
 *
 * Display names mirror `spread_compare/venues.py` (GET /venues); quote
 * currency is FE-only annotation (WHI-798 §7.1). Sections pick which slugs
 * they show via their own `venues` array — this table is lookup only, so
 * adding a venue here does not put it on any board.
 */
export const VENUE_META: Readonly<Record<string, VenueMeta>> = {
  binance: {
    displayName: "Binance",
    venueClass: "cex",
    quoteCurrency: "USDT",
  },
  bybit: {
    displayName: "Bybit",
    venueClass: "cex",
    quoteCurrency: "USDT",
  },
  hyperliquid: {
    displayName: "Hyperliquid",
    venueClass: "perp_dex",
    // USDC-margined perps (not USDT).
    quoteCurrency: "USDC",
  },
  lighter: {
    displayName: "Lighter",
    venueClass: "perp_dex",
    quoteCurrency: "USDC",
  },
  apex: {
    displayName: "ApeX",
    venueClass: "perp_dex",
    quoteCurrency: "USDT",
  },
  uniswap_eth: {
    displayName: "Uniswap (Ethereum)",
    venueClass: "amm_dex",
    quoteCurrency: "USDC",
  },
  aerodrome_base: {
    displayName: "Aerodrome (Base)",
    venueClass: "amm_dex",
    quoteCurrency: "USDC",
  },
  pancakeswap_bsc: {
    displayName: "PancakeSwap (BSC)",
    venueClass: "amm_dex",
    quoteCurrency: "USDT",
  },
  humidifi: {
    displayName: "HumidiFi",
    venueClass: "prop_amm",
    quoteCurrency: "USDC",
  },
  tessera_solana: {
    displayName: "Tessera (Solana)",
    venueClass: "prop_amm",
    quoteCurrency: "USDC",
  },
  tessera_base: {
    displayName: "Tessera (Base)",
    venueClass: "prop_amm",
    quoteCurrency: "USDC",
  },
  tessera_bsc: {
    displayName: "Tessera (BSC)",
    venueClass: "prop_amm",
    quoteCurrency: "USDT",
  },
  bisonfi: {
    displayName: "BisonFi",
    venueClass: "prop_amm",
    quoteCurrency: "USDC",
  },
};

/** Merge section-level + per-asset hidden venues for one asset. */
export function hiddenVenuesForAsset(
  section: SectionConfig,
  asset: string,
): string[] {
  const global = section.hiddenVenues ?? [];
  const perAsset = section.hiddenVenuesByAsset?.[asset] ?? [];
  return [...new Set([...global, ...perAsset])];
}

/**
 * Visible venue row order for an asset: section venues minus hidden.
 * When `section.venues` is empty, returns [] (caller may fall back to API union).
 */
export function venuesForAsset(
  section: SectionConfig,
  asset: string,
): string[] {
  const hidden = new Set(hiddenVenuesForAsset(section, asset));
  if (section.venues.length === 0) {
    return [];
  }
  return section.venues.filter((v) => !hidden.has(v));
}

/** True when this venue's class can produce a TopOfBook row. */
export function isOrderbookVenue(slug: string): boolean {
  const cls = VENUE_META[slug]?.venueClass;
  return cls !== undefined && ORDERBOOK_VENUE_CLASSES.has(cls);
}

/**
 * Instrument word for a CEX / perp row label.
 *
 * `sectionInstrument` is the same `SectionConfig.instrumentType` that drives
 * `GET /quotes`, so a board's labels cannot disagree with its request shape
 * (equity perps pin `"perp"`; boards that omit it get the CEX spot default).
 */
export function instrumentLabelFor(
  venueClass: VenueClass | undefined,
  sectionInstrument?: InstrumentType,
): string | undefined {
  if (venueClass === "perp_dex") return "perp";
  if (venueClass === "cex") {
    if (sectionInstrument === "perp" || sectionInstrument === "spot") {
      return sectionInstrument;
    }
    // Default CEX books are spot when the board does not pin instrumentType.
    return "spot";
  }
  return undefined;
}

/**
 * Rendering options shared by both label builders. Sections resolve their own
 * representation data (static table merged under `GET /assets`) and pass the
 * result in — helpers own the label *shape*, sections own the *data*.
 */
export type VenueLabelOptions = {
  /** Venue slug → representation label for the asset being labelled. */
  representations?: Readonly<Record<string, string>>;
  /** Section `instrumentType`, forwarded so labels match the quotes request. */
  instrumentType?: InstrumentType;
  /**
   * Also show the venue symbol on CEX / perp rows (e.g. `TSLAUSDT`,
   * `xyz:TSLA`). Off for boards where the logical ticker already is the
   * symbol and repeating it adds nothing (WHI-809 crypto blue chips).
   */
  includeOrderbookSymbol?: boolean;
};

/** Quote currency is redundant when the shown symbol already spells it out. */
function quoteImpliedBy(
  shownSymbol: string | undefined,
  quote: string | undefined,
): boolean {
  return Boolean(
    shownSymbol && quote && shownSymbol.toUpperCase().endsWith(quote),
  );
}

/**
 * Build display labels for matrix / TOB rows.
 *
 * - On-chain (AMM / prop AMM): display name + representation + quote currency
 * - CEX / perp: display name + instrument type [+ symbol] + quote currency
 * - Representation never collapses to a bare logical ticker for wrappers
 * - Quote currency is dropped when the symbol already ends with it
 *   ("Binance · perp · TSLAUSDT", not "… · TSLAUSDT · USDT")
 */
export function buildVenueRowLabels(
  venues: readonly string[],
  options: VenueLabelOptions = {},
): Record<string, string> {
  const reps = options.representations ?? {};
  const out: Record<string, string> = {};

  for (const slug of venues) {
    const meta = VENUE_META[slug];
    const display = meta?.displayName ?? slug;
    const quote = meta?.quoteCurrency;
    const venueClass = meta?.venueClass;
    const rep = reps[slug];

    const parts: string[] = [display];
    let shownSymbol: string | undefined;

    if (venueClass && ON_CHAIN_VENUE_CLASSES.has(venueClass)) {
      if (rep) {
        parts.push(rep);
        shownSymbol = rep;
      }
    } else if (venueClass && ORDERBOOK_VENUE_CLASSES.has(venueClass)) {
      const instrument = instrumentLabelFor(venueClass, options.instrumentType);
      if (instrument) parts.push(instrument);
      // Venue symbol / HIP-3 coin so representation is not dropped from the row.
      if (rep && options.includeOrderbookSymbol) {
        parts.push(rep);
        shownSymbol = rep;
      }
    }

    if (quote && !quoteImpliedBy(shownSymbol, quote)) {
      parts.push(quote);
    }

    out[slug] = parts.join(" · ");
  }

  return out;
}

/**
 * Best-venue prose label: instrument word for CEX / perp ("Binance perp"),
 * plus a parenthesised representation so bridge/peg risk and HIP-3 / venue
 * symbols are not dropped from the sentence.
 */
export function buildVenueSummaryLabel(
  slug: string,
  options: VenueLabelOptions = {},
): string {
  const meta = VENUE_META[slug];
  const name = meta?.displayName ?? slug;
  if (!meta) return name;

  const rep = options.representations?.[slug];

  if (ORDERBOOK_VENUE_CLASSES.has(meta.venueClass)) {
    const instrument =
      instrumentLabelFor(meta.venueClass, options.instrumentType) ?? "spot";
    return rep && options.includeOrderbookSymbol
      ? `${name} ${instrument} (${rep})`
      : `${name} ${instrument}`;
  }
  if (rep && ON_CHAIN_VENUE_CLASSES.has(meta.venueClass)) {
    return `${name} (${rep})`;
  }
  return name;
}
