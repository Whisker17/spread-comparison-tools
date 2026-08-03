import type { SideView } from "@/lib/summary";

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
  /** Venue slugs to hide (still may appear in raw API data). */
  hiddenVenues?: readonly string[];
  /** Notional tiers to show as columns. */
  notionals: readonly string[];
  /** Default side / round-trip view. */
  defaultSideView: SideView;
  /**
   * Which metric fills matrix cells. Section agents configure via props —
   * SpreadMatrix does not hardcode a product default beyond this config.
   */
  cellMetric: "total_cost_bps" | "spread_bps";
  /** Show TopOfBookRow under the matrix when TOB data exists. */
  showTopOfBook: boolean;
};
