import { NOTIONAL_TIERS_USD } from "@/config/notionals";
import type { SectionConfig } from "@/config/sections/types";

/**
 * Crypto blue chips section config (content fills in WHI-809).
 * Scaffold demo on /blue-chips uses the first asset (BTC) live.
 */
export const blueChipsSection: SectionConfig = {
  id: "blue-chips",
  title: "Crypto blue chips",
  description:
    "BTC / ETH / SOL across CEX, perp DEX, AMM, and prop AMM venues. Section content lands in WHI-809.",
  assets: ["BTC", "ETH", "SOL"],
  // Empty: show every venue the aggregator returns (mock-only is fine for scaffold).
  venues: [],
  notionals: [...NOTIONAL_TIERS_USD],
  defaultSideView: "buy",
  cellMetric: "total_cost_bps",
  showTopOfBook: true,
};
