import { NOTIONAL_TIERS_USD } from "@/config/notionals";
import type { SectionConfig } from "@/config/sections/types";

/** Stocks section config — content in WHI-810. */
export const stocksSection: SectionConfig = {
  id: "stocks",
  title: "Stocks",
  description:
    "bStocks BSC three-way + equity perps. Section content lands in WHI-810.",
  assets: [],
  venues: [],
  notionals: [...NOTIONAL_TIERS_USD],
  defaultSideView: "buy",
  cellMetric: "total_cost_bps",
  showTopOfBook: true,
};
