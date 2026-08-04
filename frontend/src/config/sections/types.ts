import type { InstrumentType } from "@/lib/api";
import type { RankMetric, SideView } from "@/lib/summary";

/**
 * Per-section configuration. Each section agent owns its own module under
 * `config/sections/` — never a shared assets catalog — so concurrent WHI-809/810/811
 * PRs do not collide.
 */
export type SectionConfig = {
  /** Route slug, e.g. "blue-chips". */
  id: string;
  title: string;
  description: string;
  /** Logical asset ids shown on this section (placeholder can use a subset). */
  assets: readonly string[];
  /**
   * Venue rows for the matrix. Empty = use whatever the API returns.
   * Section pages pass this into SpreadMatrix so they never edit the component.
   */
  venues: readonly string[];
  /** Venue slugs to hide for every asset (still may appear in raw API data). */
  hiddenVenues?: readonly string[];
  /**
   * Per-asset venue hide list (merged with section-level `hiddenVenues`).
   * Used e.g. to drop EVM AMM rows for SOL (WHI-798 §3.1 / WHI-809).
   */
  hiddenVenuesByAsset?: Readonly<Record<string, readonly string[]>>;
  /**
   * Selectable notional tiers for the size selector (WHI-841).
   * May be a subset of `NOTIONAL_TIERS_USD` when a section hides large/small sizes.
   * The matrix fetches and renders only the currently selected tier.
   */
  notionals: readonly string[];
  /**
   * Default size when `?size=` is absent or invalid (WHI-841).
   * Prefer `DEFAULT_NOTIONAL_USD` from `config/notionals.ts` unless the section
   * needs a different default.
   */
  defaultNotional: string;
  /** Default side / round-trip view. */
  defaultSideView: SideView;
  /**
   * Which metric fills matrix cells + summary ranking. Section agents configure
   * via props — SpreadMatrix / SummaryStrip do not hardcode a product default.
   */
  cellMetric: RankMetric;
  /** Show TopOfBookRow under the matrix when TOB data exists. */
  showTopOfBook: boolean;
  /**
   * Auto-poll interval for live quotes (ms). Section pages pass this into
   * `useQuotesMatrix`; omit to use the hook default.
   */
  pollIntervalMs?: number;
  /**
   * Optional instrument filter forwarded to `GET /quotes` (union derived from
   * the generated OpenAPI types — see `lib/api.ts::InstrumentType`).
   * Equity-perp boards must pass `"perp"` so CEX adapters resolve TradFi
   * contracts instead of defaulting to spot (WHI-810 / WHI-826 `_perp_only`).
   * Omit to let the backend pick the venue-class default.
   */
  instrumentType?: InstrumentType;
};

/** Venue class used for label / instrument annotations (mirrors backend VenueClass). */
export type VenueClass =
  | "cex"
  | "perp_dex"
  | "amm_dex"
  | "prop_amm"
  | "mock";

export type VenueMeta = {
  displayName: string;
  venueClass: VenueClass;
  /** Stablecoin quote leg for UI annotation (WHI-798 §7.1). */
  quoteCurrency: "USDT" | "USDC";
};
